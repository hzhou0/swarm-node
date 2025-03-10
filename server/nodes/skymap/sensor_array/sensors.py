import asyncio
import collections
import datetime
import logging
import math
import os
import re
import sys
import time
from collections import deque
from datetime import timezone
from enum import IntEnum

import cv2
import httpx
import pyrealsense2 as rs
import pyudev
import serial
import uvloop

from swarmnode_skymap_common import (
    rgbd_stream_width,
    rgbd_stream_height,
    rgbd_stream_framerate,
    GPSPose,
    DepthEncoder,
    ZhouDepthEncoder,
    GPSQuality,
    min_depth_meters,
    max_depth_meters,
    depth_units,
)


class WTRTK982:
    def __init__(self):
        self._serial: serial.Serial | None = None
        self.poses: deque[GPSPose] = collections.deque([], maxlen=10)
        self.speed_ms: float | None = None
        self.position_type: str = "NONE"
        self.sat_num: int = 0
        self.configure()
        if self._serial is None:
            self._serial = self.connect()
        if "DUMMY_GPS" in os.environ:
            return
        if os.environ.get("AIDPOS"):
            self._serial.write(os.environ["AIDPOS"].strip().encode("ascii") + b"\r\n")

    def pull_messages(self):
        if "DUMMY_GPS" in os.environ:
            self.poses.appendleft(
                GPSPose(
                    epoch_seconds=1735460258.7933,
                    latitude=53.2734,
                    longitude=-7.7783,
                    altitude=52,
                    pitch=189.25,
                    quality=GPSQuality.RTK_INT,
                    roll=-24.489,
                    yaw=39.589,
                )
            )
            return
        if self._serial is None:
            self._serial = self.connect()
        try:
            while self._serial.in_waiting:
                self._pull_message()
        except serial.SerialException as e:
            logging.exception(e)
            self.disconnect()
            return

    def _pull_message(self):
        def parse_hhmmss_ss(utc: str):
            if re.match("\d{6}\.\d\d", utc):
                return datetime.datetime.combine(
                    datetime.datetime.now(timezone.utc).date(),
                    datetime.time(
                        hour=int(utc[:2]),
                        minute=int(utc[2:4]),
                        second=int(utc[4:6]),
                        microsecond=int(utc[7:9]) * 10000,
                    ),
                    tzinfo=timezone.utc,
                ).timestamp()
            else:
                return None

        try:
            line = self._serial.readline()
        except UnicodeDecodeError:
            return
        logging.debug(line)
        if line.startswith(b"$command"):
            logging.info(line)
            return
        elif line.startswith(b"$"):
            contents, checksum = line.split(b"*", 1)
            computed_checksum = 0
            for c in contents[1:]:
                computed_checksum ^= c
            received_checksum = int(checksum[:2].decode("ascii"), 16)
            if received_checksum != computed_checksum:
                logging.warning(f"Invalid checksum: {line}, {received_checksum}")
                return
        elif line.startswith(b"#"):
            contents, _ = line.split(b"*", 1)
        else:
            logging.warning(f"Invalid message: {line}")
            return
        if contents.startswith(b"$GNHPR"):
            content_str = contents.decode("ascii")
            _, utc, heading, pitch, roll, QF, *_ = content_str.split(",")
            time = parse_hhmmss_ss(utc)
            if time is None:
                logging.debug(f"Invalid time: {time}")
                return
            if not self.poses or self.poses[0].epoch_seconds < time:
                self.poses.appendleft(GPSPose(epoch_seconds=time))
            pose = self.poses[0]
            try:
                pose.yaw = float(heading)
                pose.pitch = float(pitch)
                pose.roll = float(roll)
            except ValueError:
                pose.yaw = None
                pose.pitch = None
                pose.roll = None
        elif contents.startswith(b"$GNGGA"):
            content_str = contents.decode("ascii")
            _, utc, lat, lat_dir, lon, lon_dir, qual, sats, _, alt, *_ = content_str.split(",")
            time = parse_hhmmss_ss(utc)
            if time is None:
                logging.debug(f"Invalid time: {time}")
                return
            if not self.poses or self.poses[0].epoch_seconds < time:
                self.poses.appendleft(GPSPose(epoch_seconds=time))
            pose = self.poses[0]
            try:
                if lat_dir == "S":
                    pose.latitude = -float(lat) / 100
                elif lat_dir == "N":
                    pose.latitude = float(lat) / 100
                else:
                    raise ValueError
                if lon_dir == "W":
                    pose.longitude = -float(lon) / 100
                elif lon_dir == "E":
                    pose.longitude = float(lon) / 100
                else:
                    raise ValueError
                pose.altitude = float(alt)
                pose.quality = GPSQuality(int(qual))
            except ValueError:
                pose.latitude = None
                pose.longitude = None
                pose.altitude = None
                pose.quality = GPSQuality.INVALID
            try:
                self.sat_num = int(sats)
            except ValueError:
                self.sat_num = 0
        elif contents.startswith(b"$GNVTG"):
            content_str = contents.decode("ascii")
            try:
                speed_over_ground_km = float(content_str.split(",")[7])
                self.speed_ms = speed_over_ground_km * 5 / 18  # km/h to m/s
            except ValueError:
                return
        elif contents.startswith(b"#RTKSTATUSA"):
            content_str = contents.decode("ascii")
            _, body = content_str.split(";")
            self.position_type = body.split(",")[11]

    @classmethod
    def connect(cls) -> serial.Serial | None:
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
            return s
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

    async def write_rtcm_task(self, ntrip_username: str, ntrip_password: str):
        auth = httpx.BasicAuth(ntrip_username, ntrip_password)
        client = httpx.AsyncClient()
        while True:
            if "DUMMY_GPS" in os.environ:
                await asyncio.sleep(1)
                continue
            try:
                async with client.stream(
                    "GET",
                    url="http://rtk2go.com:2101/AVRIL",
                    auth=auth,
                    headers={
                        "Ntrip-Version": "Ntrip/2.0",
                        "User-Agent": "NTRIP pygnssutils/1.1.9",
                        "Accept": "*/*",
                        "Connection": "close",
                    },
                ) as response:
                    async for chunk in response.aiter_bytes():
                        self.write_rtcm(chunk)
            except httpx.HTTPError:
                logging.error("RTK stream timed out")
            except Exception as e:
                logging.exception(e)
            await asyncio.sleep(1)

    def write_rtcm(self, rtcm: bytes):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            self._serial = self.connect()
        assert self._serial.writable()
        self._serial.write(rtcm)
        self._serial.flush()

    def configure(self):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            self._serial = self.connect()
        assert self._serial.writable()
        # USB is on COM3
        self._serial.write(b"MODE UAV SURVEY DEFAULT\r\n")  # precision surveying mode
        self._serial.write(b"GNGGA COM3 0.05\r\n")
        self._serial.write(b"GPHPR COM3 0.05\r\n")
        self._serial.write(b"GPGSA COM3 1\r\n")
        self._serial.write(b"GPVTG COM3 1\r\n")
        self._serial.write(b"RTKSTATUSA COM3 1\r\n")
        self._serial.write(b"CONFIG HEADING FIXLENGTH\r\n")
        self._serial.write(b"SAVECONFIG\r\n")

    def reset(self):
        if "DUMMY_GPS" in os.environ:
            return
        if self._serial is None:
            self._serial = self.connect()
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
    preset: Preset = Preset.HIGH_DENSITY_PRESET
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
                s.set_option(rs.option.depth_units, depth_units)
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
        self.filter_threshold = rs.threshold_filter(min_depth_meters, max_depth_meters)
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
        if time.time() < self.creation_time + 5:
            await asyncio.sleep(self.creation_time + 5 - time.time())
        while frame_i < self.frame_quotient:
            frames = await asyncio.to_thread(self.pipeline.wait_for_frames)
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
        if pose.quality not in {GPSQuality.RTK_INT}:
            raise GPSError(f"Bad GPS Fix Type {pose.quality.name}")
        # todo: synchronization mechanism improvement
        # https://dev.intelrealsense.com/docs/depth-image-compression-by-colorization-for-intel-realsense-depth-cameras
        depth = self.filter_threshold.process(depth)
        depth = self.filter_spatial.process(depth)
        return color, depth, pose


if __name__ == "__main__":

    async def gps_test():
        os.environ["AIDPOS"] = "$AIDPOS,43.475721,N,08056.061653,W,382.173*"
        logging.basicConfig(level=logging.INFO)
        gps = WTRTK982()
        asyncio.create_task(gps.write_rtcm_task("h285zhou@uwaterloo.ca", "none"))
        while True:
            gps.pull_messages()
            await asyncio.sleep(1)
            print(gps.position_type)
            if gps.poses:
                print(gps.poses[0])
        gps.disconnect()

    async def main():
        stream = RGBDStream()
        gps = WTRTK982()
        asyncio.create_task(gps.write_rtcm_task("h285zhou@uwaterloo.ca", "none"))
        while True:
            data = await stream.gather_frame_data(gps=gps)
            if data is None:
                continue
            rgd, depth, pose = data
            frame = stream.depth_encoder.rgbd_to_video_frame(rgd, depth, pose)
            cv2.imshow("Video Frame", cv2.cvtColor(frame, cv2.COLOR_YUV420P2RGB))
            cv2.waitKey(1)
        sys.exit()

    uvloop.run(main())
