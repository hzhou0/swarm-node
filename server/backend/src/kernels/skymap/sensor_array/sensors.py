import collections
import datetime
import logging
import math
import numbers
import os
import time
from collections import deque
from datetime import timezone
from enum import IntEnum
from typing import Literal, ClassVar

import msgspec
import numpy as np
import pyrealsense2 as rs
import pyudev
import serial
from matplotlib import pyplot as plt
from msgspec import field
from pynmeagps import NMEAReader
from pynmeagps.nmeatypes_core import DE, HX, TM

from kernels.skymap.common import rgbd_stream_width, rgbd_stream_height, rgbd_stream_framerate, GPSPose, macroblock_size
from kernels.skymap.sensor_array.depth_encoding import rgb_to_depth, depth2yuv


class WTRTK982(msgspec.Struct):
    _serial: serial.Serial | None = None
    _nmr: NMEAReader | None = None

    baud_rate: ClassVar[Literal[b"460800"]] = b"460800"
    board_specific_messages: ClassVar[dict] = {
        "HPR": {
            "utc": TM,
            "heading": DE,
            "pitch": DE,
            "roll": DE,
            "QF": DE,
            "satNo": DE,
            "age": DE,
            "stnID": HX,
        }
    }

    poses: deque[GPSPose] = field(
        default_factory=lambda: collections.deque([], maxlen=20)
    )
    speed_ms: float | None = None

    def pull_messages(self):
        if "DUMMY_GPS" in os.environ:
            self.poses.appendleft(
                GPSPose(epoch_seconds=time.time(), latitude=53.2734, longitude=-7.7783, altitude=52, pitch=0, roll=0,
                        yaw=0))
            return
        if self._serial is None or self._nmr is None:
            self._serial, self._nmr = self.connect()
        try:
            while self._serial.in_waiting:
                self._pull_message()
        except serial.SerialException as e:
            logging.exception(e)
            self.disconnect()
            return

    def _pull_message(self):
        _, parsed_data = self._nmr.read()
        if not parsed_data:
            return
        if parsed_data.msgID == "HPR":
            time = datetime.datetime.combine(
                datetime.datetime.now(timezone.utc).date(),
                parsed_data.utc,
                tzinfo=timezone.utc,
            ).timestamp()
            if not self.poses or self.poses[0].epoch_seconds < time:
                self.poses.appendleft(GPSPose(epoch_seconds=time))
            pose = self.poses[0]
            pose.yaw = parsed_data.heading
            pose.pitch = parsed_data.pitch
            pose.roll = parsed_data.roll
        elif parsed_data.msgID == "GGA":
            time = datetime.datetime.combine(
                datetime.datetime.now(timezone.utc).date(),
                parsed_data.time,
                tzinfo=timezone.utc,
            ).timestamp()
            if not self.poses or self.poses[0].epoch_seconds < time:
                self.poses.appendleft(GPSPose(epoch_seconds=time))
            pose = self.poses[0]
            pose.latitude = parsed_data.lat
            pose.longitude = parsed_data.lon
            pose.altitude = parsed_data.alt
        elif parsed_data.msgID == "VTG":
            if isinstance(parsed_data.sogk, numbers.Number):
                self.speed_ms = parsed_data.sogk * 5 / 18  # km/h to m/s

    @classmethod
    def connect(cls) -> tuple[serial.Serial, NMEAReader] | None:
        if "DUMMY_GPS" in os.environ:
            return
        try:
            context = pyudev.Context()
            ch340_serial = list(
                context.list_devices(
                    subsystem="tty", ID_VENDOR_ID="1a86", ID_MODEL_ID="7523"
                )
            )
            assert len(ch340_serial) == 1
            assert ch340_serial[0].device_node is not None
            # ch340_serial requires 115200 baud rate
            s = serial.Serial(
                port=ch340_serial[0].device_node,
                baudrate=115200,
                timeout=5,
                write_timeout=1,
            )
            assert s.is_open
            s.flush()
            return s, NMEAReader(s, userdefined=cls.board_specific_messages)
        except Exception as e:
            logging.exception(e)
        return None

    def disconnect(self):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            pass
        try:
            self._serial.close()
        finally:
            self._serial = None

    def configure(self):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            self._serial, self._nmr = self.connect()
        assert self._serial.writable()
        # USB is on COM3
        self._serial.write(b"MODE ROVER SURVEY DEFAULT\r\n")  # precision surveying mode
        self._serial.write(b"GNGGA COM3 0.05\r\n")
        self._serial.write(b"GPHPR COM3 0.05\r\n")
        self._serial.write(b"GPVTG COM3 1\r\n")
        self._serial.write(b"SAVECONFIG\r\n")

    def reset(self):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            self._serial, self._nmr = self.connect()
        assert self._serial.writable()
        self._serial.write(b"FRESET\r\n")


class RGBDStream:
    class Preset(IntEnum):
        HIGH_DENSITY_PRESET = 1
        HIGH_ACCURACY_PRESET = 3

    class DepthEncoding(IntEnum):
        HUE = 1
        EURO_GRAPHICS_2011 = 2

    preset: Preset = Preset.HIGH_ACCURACY_PRESET
    depth_encoding: DepthEncoding = DepthEncoding.EURO_GRAPHICS_2011
    threshold: tuple[float, float] = (0.15, 6.)
    pixel_format = "yuv420p"

    def __init__(self):
        self.gps = WTRTK982()
        self.gps.connect()
        self.width: int = rgbd_stream_width
        self.height: int = rgbd_stream_height
        self.framerate = rgbd_stream_framerate

        sensors: list[rs.sensor] = rs.context().query_all_sensors()
        for s in sensors:
            if s.is_depth_sensor():
                s.set_option(rs.option.visual_preset, self.preset)

        self.pipeline = rs.pipeline()
        self.pipeline.start()
        self.pipeline.stop()
        self.config = rs.config()
        self.config.enable_stream(
            rs.stream.depth, self.width, self.height, rs.format.z16, self.framerate
        )
        self.config.enable_stream(
            rs.stream.color, self.width, self.height, rs.format.rgb8, self.framerate
        )
        assert self.config.can_resolve(rs.pipeline_wrapper(self.pipeline))
        self.profile: rs.pipeline_profile = self.pipeline.start(self.config)

        device: rs.device = self.profile.get_device()
        depth_sensor: rs.depth_sensor = device.first_depth_sensor()
        self.depth_scale = depth_sensor.get_depth_scale()
        self.intrinsics = (
            self.profile.get_stream(rs.stream.depth)
            .as_video_stream_profile()
            .get_intrinsics()
        )

        # Filters
        min_dist, max_dist = self.threshold
        color_scheme_hue = 9
        histogram_equalization_disable = 0
        self.filter_threshold = rs.threshold_filter(min_dist, max_dist)
        self.filter_colorizer = rs.colorizer()
        self.filter_colorizer.set_option(
            rs.option.histogram_equalization_enabled, histogram_equalization_disable
        )
        self.filter_colorizer.set_option(rs.option.color_scheme, color_scheme_hue)
        self.filter_colorizer.set_option(rs.option.min_distance, min_dist)
        self.filter_colorizer.set_option(rs.option.max_distance, max_dist)

    def destroy(self):
        self.pipeline.stop()
        self.gps.disconnect()

    def get_frame(self) -> None | np.ndarray:
        frames = self.pipeline.poll_for_frames()
        depth, color = frames.get_depth_frame(), frames.get_color_frame()
        self.gps.pull_messages()
        if not (depth and color):
            return None
        # Use the depth timestamp as the canonical frame time
        # Even synchronized frames are slightly off, the depth timestamp is more reliable for depth data
        frame_time = depth.timestamp / 1000
        if not len(self.gps.poses):
            return None
        pose = self.gps.poses[0]
        min_td = math.inf
        for p in self.gps.poses:
            if not p.defined():
                continue
            td = abs(frame_time - p.epoch_seconds)
            if td < min_td:
                pose = p
                min_td = td
            if p.epoch_seconds <= frame_time:
                break
        # todo: synchronization mechanism improvement
        blocks = pose.to_macroblocks()

        # https://dev.intelrealsense.com/docs/depth-image-compression-by-colorization-for-intel-realsense-depth-cameras
        depth = self.filter_threshold.process(depth)
        if self.depth_encoding == self.DepthEncoding.HUE:
            depth = self.filter_colorizer.process(depth)
            depth_image = np.asanyarray(depth.get_data())
        elif self.depth_encoding == self.DepthEncoding.EURO_GRAPHICS_2011:
            depth_image = np.asanyarray(depth.get_data())
            yuv_encoded = depth2yuv(depth_image)

        color_image = np.asanyarray(color.get_data())
        depth_image[0:blocks.shape[0], 0:blocks.shape[1], :] = blocks
        return np.vstack((color_image, depth_image))

    @classmethod
    def decolorize_depth_frame(cls, frame: np.ndarray) -> np.ndarray:
        if cls.depth_encoding == cls.DepthEncoding.HUE:
            min_dist, max_dist = cls.threshold
            min_dist -= 0.01  # Offset to avoid depth inversion. See Figure 7
            frame = rgb_to_depth(frame, min_dist, max_dist)
        elif cls.depth_encoding == cls.DepthEncoding.EURO_GRAPHICS_2011:
            pass
        np.save("prezero.npy", frame)
        frame[0:GPSPose.height_blocks * macroblock_size, 0:GPSPose.width_blocks * macroblock_size] = 0
        np.save("postzero.npy", frame)
        return frame


if __name__ == "__main__":
    import open3d as o3d

    os.environ["DUMMY_GPS"] = "1"
    stream = RGBDStream()


    def test():
        _frame = stream.get_frame()
        while _frame is None:
            _frame = stream.get_frame()
        _frame = stream.get_frame()
        color_frame, depth_frame = _frame[:rgbd_stream_height, :], _frame[rgbd_stream_height:, :]
        decolored = RGBDStream.decolorize_depth_frame(depth_frame)
        plt.imshow(decolored, cmap="gray")
        plt.show()


    def integration_test():
        vis = o3d.visualization.Visualizer()
        vis.create_window()
        intrinsics = o3d.camera.PinholeCameraIntrinsic(width=1280, height=720, fx=641.162, fy=641.162, cx=639.135,
                                                       cy=361.356)
        pcd = None
        while True:
            _frame = stream.get_frame()
            if _frame is None:
                vis.poll_events()
                vis.update_renderer()
                continue
            color_frame, depth_frame = _frame[:rgbd_stream_height, :], _frame[rgbd_stream_height:, :]
            depth_intensity_frame = RGBDStream.decolorize_depth_frame(depth_frame)
            im1 = o3d.geometry.Image(color_frame)
            im2 = o3d.geometry.Image(depth_intensity_frame)
            rgbd_img: o3d.geometry.RGBDImage = o3d.geometry.RGBDImage.create_from_color_and_depth(im1, im2,
                                                                                                  convert_rgb_to_intensity=False)
            o3d.visualization.draw_geometries([rgbd_img])
            if pcd is None:
                pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
                vis.add_geometry(pcd)
            else:
                vis.remove_geometry(pcd, reset_bounding_box=False)
                pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
                vis.add_geometry(pcd, reset_bounding_box=False)


    test()
