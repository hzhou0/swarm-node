import asyncio
import collections
import datetime
import logging
import math
import numbers
import os
import sys
import time
from collections import deque
from datetime import timezone
from enum import IntEnum
from typing import Literal

import cv2
import pyrealsense2 as rs
import pyudev
import serial
import uvloop
from msgspec import field
from pynmeagps import NMEAReader
from pynmeagps.nmeatypes_core import DE, HX, TM, IN

from leapseconds import utc_to_gps
from swarmnode_skymap_common import (
    rgbd_stream_width,
    rgbd_stream_height,
    rgbd_stream_framerate,
    GPSPose,
    DepthEncoder,
    ZhouDepthEncoder,
    GPSQuality,
)


class WTRTK982:
    baud_rate: Literal[b"460800"] = b"460800"
    board_specific_messages = {
        "HPR": {
            "utc": TM,
            "heading": DE,
            "pitch": DE,
            "roll": DE,
            "QF": IN,
            "satNo": DE,
            "age": DE,
            "stnID": HX,
        }
    }

    def __init__(self):
        self._serial: serial.Serial | None = None
        self._nmr: NMEAReader | None = None
        self.configure()
        if self._serial is None:
            self._serial, self._nmr = self.connect()
        if "DUMMY_GPS" in os.environ:
            return
        now = utc_to_gps(datetime.datetime.utcnow())
        self._serial.write(
            f"$AIDTIME,{now.year},{now.month},{now.day},{now.hour},{now.minute},{now.second},{round(now.microsecond / 100)},0\r\n".encode(
                "ascii"
            )
        )
        if os.environ.get("AIDPOS"):
            self._serial.write(os.environ["AIDPOS"].strip().encode("ascii") + b"\r\n")

    poses: deque[GPSPose] = field(default_factory=lambda: collections.deque([], maxlen=5))
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
                    quality=GPSQuality.FIX,
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
            pose.quality = GPSQuality(parsed_data.QF)
        elif parsed_data.msgID == "VTG":
            if isinstance(parsed_data.sogk, numbers.Number):
                self.speed_ms = parsed_data.sogk * 5 / 18  # km/h to m/s

    @classmethod
    def connect(cls) -> tuple[serial.Serial, NMEAReader] | None:
        if "DUMMY_GPS" in os.environ:
            return None
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

    def write_rtcm(self, rtcm: bytes):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            self._serial, self._nmr = self.connect()
        assert self._serial.writable()
        self._serial.write(rtcm)
        self._serial.flush()

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


class FrameError(Exception):
    pass


class GPSError(Exception):
    pass


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
        self.width: int = rgbd_stream_width
        assert self.width % 4 == 0
        self.height: int = rgbd_stream_height
        assert self.height % 4 == 0
        self.framerate = rgbd_stream_framerate
        assert self.device_fps % self.framerate == 0
        # process a frame every frame_quotient frames received
        self.frame_quotient: int = self.device_fps // self.framerate

        rs_ctx = rs.context()
        self.pipeline = rs.pipeline(rs_ctx)
        self.pipeline.start()
        self.pipeline.stop()
        sensors: list[rs.sensor] = rs_ctx.query_all_sensors()
        for s in sensors:
            if s.is_depth_sensor():
                s.set_option(rs.option.visual_preset, self.preset)
                s.set_option(rs.option.depth_units, self.depth_units)
                s.set_option(rs.option.enable_auto_exposure, 1)
            elif s.is_color_sensor():
                s.set_option(rs.option.enable_auto_exposure, 1)
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

        self.destroyed = False
        self.creation_time = time.time()

    def destroy(self):
        if not self.destroyed:
            self.pipeline.stop()
            self.destroyed = True

    async def gather_frame_data(self, gps: WTRTK982) -> tuple[rs.frame, rs.frame, GPSPose]:
        frame_i = 0
        depth, color = None, None
        early = time.time() < self.creation_time + 5
        while frame_i < self.frame_quotient or (early and not (depth and color)):
            frames = await asyncio.to_thread(self.pipeline.poll_for_frames)
            _depth, _color = frames.get_depth_frame(), frames.get_color_frame()
            if _depth and _color:
                depth, color = _depth, _color
            frame_i += 1
        if not (depth and color):
            raise FrameError("No frames received")
        # Use the depth timestamp as the canonical frame time
        # Even synchronized frames are slightly off, the depth timestamp is more reliable for depth data
        gps.pull_messages()
        frame_time = depth.timestamp / 1000
        if not len(gps.poses):
            raise GPSError("No GPS data received")
        pose = gps.poses[0]
        min_td = math.inf
        for p in gps.poses:
            if not p.defined():
                continue
            td = abs(frame_time - p.epoch_seconds)
            if td < min_td:
                pose = p
                min_td = td
            if p.epoch_seconds <= frame_time:
                break
        if pose.quality != GPSQuality.FIX:
            raise GPSError(f"Bad GPS Fix Type {pose.quality.name}")
        # todo: synchronization mechanism improvement
        # https://dev.intelrealsense.com/docs/depth-image-compression-by-colorization-for-intel-realsense-depth-cameras
        depth = self.filter_threshold.process(depth)
        depth = self.filter_spatial.process(depth)
        return color, depth, pose


if __name__ == "__main__":
    os.environ["DUMMY_GPS"] = "1"

    async def main():
        stream = RGBDStream()
        now = time.time()
        while time.time() < now + 50:
            data = await stream.gather_frame_data(gps=WTRTK982())
            if data is None:
                continue
            rgd, depth, pose = data
            frame = stream.depth_encoder.rgbd_to_video_frame(rgd, depth, pose)
            cv2.imshow("Video Frame", cv2.cvtColor(frame, cv2.COLOR_YUV420P2RGB))
            cv2.waitKey(1)
        sys.exit()

    uvloop.run(main())
