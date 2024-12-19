import collections
import datetime
import logging
import numbers
import os
import struct
import time
import zlib
from collections import deque
from datetime import timezone
from typing import Literal, ClassVar

import cv2
import msgspec
import numpy as np
import pyrealsense2 as rs
import pyudev
import serial
from msgspec import field
from pynmeagps import NMEAReader
from pynmeagps.nmeatypes_core import DE, HX, TM


class GPSPose(msgspec.Struct):
    epoch_seconds: float
    latitude: float | None = None  # North is positive
    longitude: float | None = None  # The East is Positive
    altitude: float | None = None
    pitch: float | None = None
    roll: float | None = None
    yaw: float | None = None

    def defined(self):
        return not (self.latitude is None or self.pitch is None)

    def to_bytes(self):
        assert self.defined()
        buf = struct.pack(
            "!dddffff",
            self.epoch_seconds,
            self.latitude,
            self.longitude,
            self.altitude,
            self.pitch,
            self.roll,
            self.yaw,
        )
        buf += struct.pack("!I", zlib.crc32(buf))
        assert len(buf) == 44
        return buf

    def to_macroblocks(self) -> np.ndarray[np.uint8, (704, 64, 3)]:
        arr = np.frombuffer(self.to_bytes(), dtype=np.uint8)
        stacked_arr = np.stack(
            (arr >> 6, arr >> 4 & 0b11, arr >> 2 & 0b11, arr & 0b11), axis=-1
        )

        color_map = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [0, 255, 255],
                [0, 0, 255],
            ],
            dtype=np.uint8,  # Blue, Green, Yellow, Red in BGR (opencv's native format)
        )

        # Initialize the output array with shape (44, 4, 3)
        pixels = color_map[stacked_arr]
        # encode into 16 x 16 macroblocks
        macroblocks = np.repeat(np.repeat(pixels, 16, axis=0), 16, axis=1)
        return macroblocks

    def from_macroblocks(
            self, macroblocks: np.ndarray[np.uint8, (704, 64, 3)]
    ) -> bytes:
        # Define the color mapping (same as before)
        color_map = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [0, 255, 255],
                [0, 0, 255],
            ],
            dtype=np.int16,  # Blue, Green, Yellow, Red in BGR (opencv's native format)
        )

        # Create a mask where the middle pixel (8,8) in each macroblock is compared to each entry in color_map
        # We sum the absolute errors over the color dimension (axis=3), creating a 44x4x4 error array
        mask = np.sum(
            np.abs(
                macroblocks[8::16, 8::16, np.newaxis, :].astype(np.int16) - color_map
            ),
            axis=3,
        )
        # Find the index (0,1,2,3) of the colormap entry that is closest to the pixel
        inverted_array = np.argmin(mask, axis=-1).astype(np.uint8)

        decoded_bytes = (
                (inverted_array[..., 0] << 6)
                | (inverted_array[..., 1] << 4)
                | (inverted_array[..., 2] << 2)
                | inverted_array[..., 3]
        )

        return decoded_bytes.tobytes()


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
            self.poses.appendleft(GPSPose(epoch_seconds=time.time(), latitude=53.2734, longitude=-7.7783, altitude=52, pitch=0, roll=0, yaw=0))
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
    def __init__(self, framerate: int = 15):
        self.gps = WTRTK982()
        self.gps.connect()
        self.width: int = 1280
        self.height: int = 720
        self.framerate = framerate

        HIGH_DENSITY_PRESET = 1
        HIGH_ACCURACY_PRESET = 3
        sensors: list[rs.sensor] = rs.context().query_all_sensors()
        for s in sensors:
            if s.is_depth_sensor():
                s.set_option(rs.option.visual_preset, HIGH_ACCURACY_PRESET)


        self.pipeline = rs.pipeline()
        self.pipeline.start()
        self.pipeline.stop()
        self.config = rs.config()
        self.config.enable_stream(
            rs.stream.depth, self.width, self.height, rs.format.z16, framerate
        )
        self.config.enable_stream(
            rs.stream.color, self.width, self.height, rs.format.bgr8, framerate
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
        MIN_DIST, MAX_DIST = 0.15, 6
        COLOR_SCHEME_HUE = 9
        HISTOGRAM_EQUALIZATION_DISABLE = 0
        self.filter_threshold = rs.threshold_filter(MIN_DIST, MAX_DIST)
        self.filter_colorizer = rs.colorizer()
        self.filter_colorizer.set_option(
            rs.option.histogram_equalization_enabled, HISTOGRAM_EQUALIZATION_DISABLE
        )
        self.filter_colorizer.set_option(rs.option.color_scheme, COLOR_SCHEME_HUE)
        self.filter_colorizer.set_option(rs.option.min_distance, MIN_DIST)
        self.filter_colorizer.set_option(rs.option.max_distance, MAX_DIST)

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
        min_td = 10
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
        depth = self.filter_colorizer.process(depth)

        depth_image = np.asanyarray(depth.get_data())
        color_image = np.asanyarray(color.get_data())
        depth_image[0:704, 0:64, :] = blocks
        return np.vstack((color_image, depth_image))

    def visualize_frame(self):
        frame = self.get_frame()
        if frame is None:
            return
        cv2.namedWindow("RealSense", cv2.WINDOW_NORMAL)
        cv2.imshow("RealSense", frame)
        cv2.waitKey(1)


if __name__ == "__main__":
    os.environ["DUMMY_GPS"]="1"
    stream = RGBDStream()
    while True:
        stream.visualize_frame()
