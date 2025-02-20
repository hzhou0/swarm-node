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
from pathlib import Path
from typing import Literal, ClassVar

import msgspec
import numpy as np
import pyrealsense2 as rs
import pyudev
import serial
from msgspec import field
from pynmeagps import NMEAReader
from pynmeagps.nmeatypes_core import DE, HX, TM

from swarmnode_skymap_common import (
    rgbd_stream_width,
    rgbd_stream_height,
    rgbd_stream_framerate,
    GPSPose,
)
from .depth_encoding import (
    DepthEncoder,
    ZhouDepthEncoder,
)


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

    poses: deque[GPSPose] = field(default_factory=lambda: collections.deque([], maxlen=20))
    speed_ms: float | None = None

    def pull_messages(self):
        if "DUMMY_GPS" in os.environ:
            self.poses.appendleft(
                GPSPose(
                    epoch_seconds=1735460258.7933,
                    latitude=53.2734,
                    longitude=-7.7783,
                    altitude=52,
                    pitch=0,
                    roll=0,
                    yaw=0,
                )
            )
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
                context.list_devices(subsystem="tty", ID_VENDOR_ID="1a86", ID_MODEL_ID="7523")
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

    device_fps = 60
    preset: Preset = Preset.HIGH_ACCURACY_PRESET
    depth_units = 0.0001  # 0 – 6.5535 meters
    min_depth_meters: float = 0.15
    max_depth_meters: float = 6
    depth_encoder: DepthEncoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)

    def __init__(self):
        self.gps = WTRTK982()
        self.gps.connect()
        self.width: int = rgbd_stream_width
        assert self.width % 4 == 0
        self.height: int = rgbd_stream_height
        assert self.height % 4 == 0
        self.framerate = rgbd_stream_framerate
        assert self.device_fps % self.framerate == 0
        # process a frame every frame_quotient frames received
        self.frame_quotient: int = self.device_fps // self.framerate
        self.frame_i = 0

        sensors: list[rs.sensor] = rs.context().query_all_sensors()
        for s in sensors:
            if s.is_depth_sensor():
                s.set_option(rs.option.visual_preset, self.preset)
                s.set_option(rs.option.depth_units, self.depth_units)
                s.set_option(rs.option.enable_auto_exposure, 1)
            elif s.is_color_sensor():
                s.set_option(rs.option.enable_auto_exposure, 1)
        self.pipeline = rs.pipeline()
        self.pipeline.start()
        self.pipeline.stop()
        self.config = rs.config()
        self.config.enable_stream(
            rs.stream.depth, self.width, self.height, rs.format.z16, self.device_fps
        )
        self.config.enable_stream(
            rs.stream.color, self.width, self.height, rs.format.rgb8, self.device_fps
        )
        assert self.config.can_resolve(rs.pipeline_wrapper(self.pipeline))
        self.profile: rs.pipeline_profile = self.pipeline.start(self.config)
        self.intrinsics = (
            self.profile.get_stream(rs.stream.depth).as_video_stream_profile().get_intrinsics()
        )

        # Filters
        self.filter_threshold = rs.threshold_filter(self.min_depth_meters, self.max_depth_meters)
        self.filter_spatial = rs.spatial_filter()
        self.filter_spatial.set_option(rs.option.filter_magnitude, 5)
        self.filter_spatial.set_option(rs.option.filter_smooth_alpha, 0.25)
        self.filter_spatial.set_option(rs.option.filter_smooth_delta, 1)

    def destroy(self):
        self.pipeline.stop()
        self.gps.disconnect()

    def gather_frame_data(self) -> tuple[rs.frame, rs.frame, GPSPose] | None:
        frames = self.pipeline.poll_for_frames()
        depth, color = frames.get_depth_frame(), frames.get_color_frame()
        self.gps.pull_messages()
        if not (depth and color):
            return None
        self.frame_i += 1
        if self.frame_i >= self.frame_quotient:
            self.frame_i = 0
        else:
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
        # https://dev.intelrealsense.com/docs/depth-image-compression-by-colorization-for-intel-realsense-depth-cameras
        depth = self.filter_threshold.process(depth)
        depth = self.filter_spatial.process(depth)
        return color, depth, pose


if __name__ == "__main__":
    import open3d as o3d
    import av

    os.environ["DUMMY_GPS"] = "1"
    stream = RGBDStream()
    now = time.time()
    while time.time() < now + 5:
        stream.gather_frame_data()

    def gen_mp4(output_file: Path):
        container = av.open(output_file, "w", format="mp4")
        av_stream = container.add_stream("h264", rgbd_stream_framerate)
        av_stream.height = rgbd_stream_height
        av_stream.width = rgbd_stream_width * 2
        av_stream.bit_rate = 5000000
        av_stream.pix_fmt = "yuv420p"
        av_stream.options = {"profile": "baseline", "level": "31", "tune": "grain"}
        i = 0
        source_data = []
        while True:
            f = stream.gather_frame_data()
            if f is None:
                # vis.poll_events()
                # vis.update_renderer()
                continue
            i += 1
            if i > 10:
                break
            rgb, d, pose = f
            source_data.append([np.asanyarray(rgb.get_data()), np.asanyarray(d.get_data()), pose])
            _frame = stream.depth_encoder.rgbd_to_video_frame(*f)
            for packet in av_stream.encode(_frame):
                container.mux(packet)
        for packet in av_stream.encode():
            container.mux(packet)
        container.close()
        return source_data

    output_file = root_dir.joinpath(datetime.datetime.now().strftime("%Y.%m.%d-%H.%M.%S") + ".mp4")
    source_data = gen_mp4(output_file)
    # output_file = Path("/home/henry/swarmnode/2024.12.30-20.28.10.mp4")

    correct_pose = GPSPose(
        epoch_seconds=1735460258.7933,
        latitude=53.2734,
        longitude=-7.7783,
        altitude=52,
        pitch=0,
        roll=0,
        yaw=0,
    )
    correct_bytes = correct_pose.to_bytes()
    print(correct_bytes)
    playback = av.open(output_file)
    recovered_data = []
    for frame in playback.decode(video=0):
        rgb, d, _pose = RGBDStream.depth_encoder.video_frame_to_rgbd(frame)
        recovered_data.append((rgb, d, _pose))

    assert len(recovered_data) == len(source_data)
    acc_rmse = 0
    acc_mean_dist = 0
    data_i = len(recovered_data)
    acc_max_error = 0
    for i in range(data_i):
        _, src_d, _ = source_data[i]
        _, dest_d, _ = recovered_data[i]
        nonzero_mask = (src_d != 0) & (dest_d != 0)
        delta = np.abs(
            src_d.astype(np.float32)[nonzero_mask] - dest_d.astype(np.float32)[nonzero_mask]
        )
        max_error = np.max(delta)
        acc_max_error = max(max_error, acc_max_error)
        empty_pixels = np.sum(src_d == 0)
        rmse = np.sqrt(np.mean(delta**2))
        acc_rmse += rmse
        acc_mean_dist += np.mean(src_d[nonzero_mask])
        print(f"frame {i} rmse: {rmse}")
        print(f"frame {i} max_error: {max_error}")
    print(
        f"average rmse: {acc_rmse / data_i}. mean dist: {acc_mean_dist / data_i}. percentage rmse: {acc_rmse / data_i / (acc_mean_dist / data_i) * 100}"
    )
    print(f"max error: {acc_max_error}")
    intrinsics = o3d.camera.PinholeCameraIntrinsic(
        width=848, height=480, fx=424.770, fy=424.770, cx=423.427, cy=240.898
    )

    volume = o3d.pipeline_tmpls.integration.ScalableTSDFVolume(
        voxel_length=4 / 512.0,
        sdf_trunc=0.04,
        color_type=o3d.pipeline_tmpls.integration.TSDFVolumeColorType.RGB8,
    )
    for data in recovered_data:
        rgb, d, _ = data
        im1 = o3d.geometry.Image(np.ascontiguousarray(rgb))
        im2 = o3d.geometry.Image(np.ascontiguousarray(d))
        rgbd_img: o3d.geometry.RGBDImage = o3d.geometry.RGBDImage.create_from_color_and_depth(
            im1,
            im2,
            depth_scale=1 / RGBDStream.depth_units,
            depth_trunc=RGBDStream.max_depth_meters,
            convert_rgb_to_intensity=False,
        )
        pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
        volume.integrate(rgbd_img, intrinsics, np.linalg.inv(np.identity(4)))
        print("integrated")
    mesh = volume.extract_triangle_mesh()
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(
        output_file.parent.joinpath(output_file.name.removesuffix(".mp4") + ".glb").as_posix(),
        mesh,
        compressed=True,
    )  # GLB
    o3d.io.write_triangle_mesh(
        output_file.parent.joinpath(output_file.name.removesuffix(".mp4") + ".obj").as_posix(),
        mesh,
        compressed=True,
    )  # OBJ
    o3d.io.write_triangle_mesh(
        output_file.parent.joinpath(output_file.name.removesuffix(".mp4") + ".stl").as_posix(),
        mesh,
        compressed=True,
    )

    vis = o3d.visualization.Visualizer()
    vis.create_window()
    src_pcd = None
    pcd = None
    last_update = time.time()
    i = 0
    once = True
    while True:
        vis.poll_events()
        vis.update_renderer()
        if last_update < time.time() - 2:
            i += 1
            if i >= len(recovered_data):
                i = 0
            rgb, d, _ = recovered_data[i]
            src_rgb, src_d, _ = source_data[i]
            src_im1 = o3d.geometry.Image(np.ascontiguousarray(src_rgb))
            src_im2 = o3d.geometry.Image(np.ascontiguousarray(src_d))
            src_rgbd_img: o3d.geometry.RGBDImage = (
                o3d.geometry.RGBDImage.create_from_color_and_depth(
                    src_im1,
                    src_im2,
                    depth_scale=1 / RGBDStream.depth_units,
                    depth_trunc=RGBDStream.max_depth_meters,
                )
            )
            im1 = o3d.geometry.Image(np.ascontiguousarray(rgb))
            im2 = o3d.geometry.Image(np.ascontiguousarray(d))
            rgbd_img: o3d.geometry.RGBDImage = o3d.geometry.RGBDImage.create_from_color_and_depth(
                im1,
                im2,
                depth_scale=1 / RGBDStream.depth_units,
                depth_trunc=RGBDStream.max_depth_meters,
                convert_rgb_to_intensity=False,
            )
            if pcd is None:
                pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
                src_pcd = o3d.geometry.PointCloud.create_from_rgbd_image(src_rgbd_img, intrinsics)
                src_pcd.paint_uniform_color([1, 0, 0])
                vis.add_geometry(pcd)
                vis.add_geometry(src_pcd)
            else:
                vis.remove_geometry(pcd, reset_bounding_box=False)
                vis.remove_geometry(src_pcd, reset_bounding_box=False)
                pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
                src_pcd = o3d.geometry.PointCloud.create_from_rgbd_image(src_rgbd_img, intrinsics)
                src_pcd.paint_uniform_color([1, 0, 0])
                vis.add_geometry(pcd, reset_bounding_box=False)
                vis.add_geometry(src_pcd, reset_bounding_box=False)
            last_update = time.time()
