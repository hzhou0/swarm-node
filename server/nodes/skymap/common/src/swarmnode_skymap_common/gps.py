import logging
import math
import struct
import zlib
from enum import IntEnum
from typing import ClassVar, Literal, Self

import msgspec
import numpy as np

# 848x480 is the most accurate resolution on the D455: https://github.com/IntelRealSense/librealsense/issues/11180
rgbd_stream_width = 848
rgbd_stream_height = 480
rgbd_stream_framerate = 5
macroblock_size = 5
min_depth_meters = 0.15
max_depth_meters = 6.0
depth_units = 0.0001  # 0 – 6.5535 meters


_max_height_blocks = rgbd_stream_height // macroblock_size


class ChecksumMismatchError(Exception):
    pass


class GPSQuality(IntEnum):
    INVALID = 0
    SINGLE = 1
    DIFFERENTIAL = 2
    PPS = 3
    RTK_INT = 4
    RTK_FLOAT = 5
    DEAD_RECKONING = 6
    MANUAL = 7
    SIMULATOR = 8


class GPSPose(msgspec.Struct):
    epoch_seconds: float
    latitude: float | None = None  # North is positive
    longitude: float | None = None  # The East is Positive
    altitude: float | None = None
    pitch: float | None = None
    roll: float | None = None
    yaw: float | None = None
    quality: GPSQuality = GPSQuality.INVALID
    byte_length: ClassVar[Literal[44]] = 44
    bit_per_macroblock: ClassVar[int] = 4
    macroblocks_required: ClassVar[int] = byte_length * bit_per_macroblock
    width_blocks: ClassVar[int] = math.ceil(macroblocks_required / _max_height_blocks)
    height_blocks: ClassVar[int] = macroblocks_required // width_blocks

    def __post_init__(self):
        assert GPSPose.macroblocks_required % self.width_blocks == 0

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
        assert len(buf) == self.byte_length
        return buf

    @classmethod
    def from_bytes(cls, buf):
        assert len(buf) == cls.byte_length
        (data, crc32) = buf[:-4], buf[-4:]
        (crc32,) = struct.unpack("!I", crc32)
        if zlib.crc32(data) != crc32:
            raise ChecksumMismatchError((data, crc32))
        (epoch_seconds, latitude, longitude, altitude, pitch, roll, yaw) = struct.unpack(
            "!dddffff", data
        )
        return cls(epoch_seconds, latitude, longitude, altitude, pitch, roll, yaw)

    def to_macroblocks(self) -> np.ndarray:
        arr = np.frombuffer(self.to_bytes(), dtype=np.uint8)
        stacked_arr = np.stack((arr >> 6, arr >> 4 & 0b11, arr >> 2 & 0b11, arr & 0b11), axis=-1)

        color_map = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [255, 255, 0],
                [0, 0, 255],
            ],
            dtype=np.uint8,  # Red, Green, Yellow, Blue in RGB
        )

        # Initialize the output array with shape (44, 4, 3)
        pixels = color_map[stacked_arr]
        pixels = pixels.reshape((self.height_blocks, self.width_blocks, -1))
        # encode into 16 x 16 macroblocks
        macroblocks = np.repeat(np.repeat(pixels, macroblock_size, axis=0), macroblock_size, axis=1)
        return macroblocks

    @classmethod
    def from_macroblocks(cls, macroblocks: np.ndarray) -> Self | None:
        # Define the color mapping (same as before)
        color_map = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [255, 255, 0],
                [0, 0, 255],
            ],
            dtype=np.int16,  # Red, Green, Yellow, Blue in RGB
        )

        # Create a mask where the middle pixel (8,8) in each macroblock is compared to each entry in color_map
        # We sum the absolute errors over the color dimension (axis=3), creating a 44x4x4 error array
        mask = np.sum(
            np.abs(
                macroblocks[
                    (macroblock_size // 2) :: macroblock_size,
                    (macroblock_size // 2) :: macroblock_size,
                    np.newaxis,
                    :,
                ].astype(np.int16)
                - color_map
            ),
            axis=3,
        )
        # Find the index (0,1,2,3) of the colormap entry that is closest to the pixel
        inverted_array = np.argmin(mask, axis=-1).astype(np.uint8)
        inverted_array = inverted_array.reshape((cls.byte_length, 4))

        decoded_bytes = (
            (inverted_array[..., 0] << 6)
            | (inverted_array[..., 1] << 4)
            | (inverted_array[..., 2] << 2)
            | inverted_array[..., 3]
        ).tobytes()
        try:
            return cls.from_bytes(decoded_bytes)
        except ChecksumMismatchError as e:
            logging.exception(e)
            return None

    @classmethod
    def read_from_color_frame(
        cls, frame: np.ndarray, clear_macroblocks: bool = False
    ) -> Self | None:
        ret = cls.from_macroblocks(
            frame[
                : GPSPose.height_blocks * macroblock_size,
                : GPSPose.width_blocks * macroblock_size,
                :,
            ]
        )
        if clear_macroblocks:
            frame[
                : GPSPose.height_blocks * macroblock_size,
                : GPSPose.width_blocks * macroblock_size,
            ] = 0
        return ret

    def write_to_color_frame(self, frame: np.ndarray) -> None:
        frame[
            : GPSPose.height_blocks * macroblock_size, : GPSPose.width_blocks * macroblock_size, :
        ] = self.to_macroblocks()


if __name__ == "__main__":
    import time

    pose = GPSPose(time.time(), 0, 0, 0, 0, 0, 0)
    assert pose.defined()
    start = time.time()
    result = pose.to_macroblocks()
    assert pose == GPSPose.from_macroblocks(result)
