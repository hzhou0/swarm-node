import logging
import math
from pathlib import Path
from typing import Protocol, ClassVar

import numba.core.types.containers
import numpy as np
import pyrealsense2 as rs
from av.video.frame import VideoFrame
from av.video.reformatter import ColorRange, Colorspace
from matplotlib import pyplot as plt
from numba import guvectorize, float64, uint16, uint8, njit, prange

from kernels.skymap.common import rgbd_stream_width, GPSPose


class DepthEncoder(Protocol):
    pixel_format: ClassVar[str]
    depth_units: float
    min_depth_meters: float
    max_depth_meters: float

    def __init__(self, depth_units: float, min_depth_meters: float, max_depth_meters: float):
        self.depth_units = depth_units
        self.min_depth_meters = min_depth_meters
        self.max_depth_meters = max_depth_meters

    def rgbd_to_video_frame(self, color: rs.frame, depth: rs.frame, pose: GPSPose) -> VideoFrame:
        ...

    def video_frame_to_rgbd(self, vf: VideoFrame) -> tuple[np.ndarray, np.ndarray, GPSPose | None]:
        ...


@guvectorize(
    [(uint8[:, :, :], float64, float64, uint16[:, :])],
    "(i,j,k),(),()->(i,j)",
    cache=True,
    nopython=True,
)
def rgb_to_depth(x: np.ndarray, min_dist: float, max_dist: float, y):
    """
    Adapted from intel's documentation:
    https://dev.intelrealsense.com/docs/depth-image-compression-by-colorization-for-intel-realsense-depth-cameras#32-depth-image-recovery-from-colorized-depth-images-in-c
    """
    for i in range(x.shape[0]):
        for j in range(x.shape[1]):
            r, g, b = x[i, j]
            y[i, j] = 0
            if b + g + r < 256:
                y[i, j] = 0
            elif r >= g and r >= b:
                if g >= b:
                    y[i, j] = g - b
                else:
                    y[i, j] = g - b + 1529
            elif g >= r and g >= b:
                y[i, j] = b - r + 510
            elif b >= g and b >= r:
                y[i, j] = r - g + 1020
            if y[i, j] > 0:
                y[i, j] = (min_dist + (max_dist - min_dist) * y[i, j] / 1529) * 1000 + 0.5


class HueDepthEncoder(DepthEncoder, Protocol):
    pixel_format: ClassVar[str] = "rgb24"

    # noinspection PyProtocol
    def __init__(self, depth_units: float, min_depth_meters: float, max_depth_meters: float):
        super().__init__(depth_units, min_depth_meters, max_depth_meters)
        color_scheme_hue = 9
        histogram_equalization_disable = 0
        self.filter_colorizer = rs.colorizer()
        self.filter_colorizer.set_option(rs.option.histogram_equalization_enabled, histogram_equalization_disable)
        self.filter_colorizer.set_option(rs.option.color_scheme, color_scheme_hue)
        self.filter_colorizer.set_option(rs.option.min_distance, min_depth_meters)
        self.filter_colorizer.set_option(rs.option.max_distance, max_depth_meters)

    def rgbd_to_video_frame(self, color: rs.frame, depth: rs.frame, pose: GPSPose) -> VideoFrame:
        depth = self.filter_colorizer.process(depth)
        depth_ndarray = np.asanyarray(depth.get_data())
        rgb_ndarray = np.asanyarray(color.get_data())
        pose.write_to_color_frame(rgb_ndarray)
        return VideoFrame.from_ndarray(np.hstack((rgb_ndarray, depth_ndarray)), self.pixel_format)

    def video_frame_to_rgbd(self, vf: VideoFrame) -> tuple[np.ndarray, np.ndarray, GPSPose | None]:
        frame = vf.to_ndarray(format=self.pixel_format)
        rgb, d = frame[:, :rgbd_stream_width], frame[:, rgbd_stream_width:]
        d: np.ndarray = rgb_to_depth(d, self.min_depth_meters - 0.01, self.max_depth_meters)
        pose = GPSPose.read_from_color_frame(rgb, clear_macroblocks=True)
        return rgb, d, pose


class TriangleDepthEncoder(DepthEncoder, Protocol):
    pixel_format: ClassVar[str] = "yuv420p"
    # Adapted from the paper by the University College London at http://reality.cs.ucl.ac.uk/projects/depth-streaming/depth-streaming.pdf
    # In YUV420, there are two bits used for each of the U and V samples. In selecting n_p, the integer period for H_a and H_b, the paper
    # states n_p must be at most twice the number of output quantization levels, which in the case of YUV420 is channel dependent. Thus,
    w = 2**16
    n_p = 512
    p = n_p / w
    # webrtc can sometimes use limited yuv, but this is configurable
    # yuv_min = 16
    # yuv_max = 235
    norm_to_8bit = 2**8 - 1
    depth2yuv_lookup: np.ndarray | None = None
    yuv2depth_lookup: np.ndarray | None = None

    # noinspection PyProtocol
    def __init__(self, depth_units: float, min_depth_meters: float, max_depth_meters: float):
        super().__init__(depth_units, min_depth_meters, max_depth_meters)
        self.min_valid_depth = round(min_depth_meters / depth_units)
        self.max_valid_depth = round(max_depth_meters / depth_units)
        if self.depth2yuv_lookup is None or self.yuv2depth_lookup is None:
            this_dir = Path(__file__).parent
            lookups_file = this_dir / "triangle_depth_encoding_lookup_tables.npz"
            if lookups_file.exists():
                with np.load(lookups_file) as lookups:
                    self.depth2yuv_lookup = lookups["depth2yuv_lookup"]
                    self.yuv2depth_lookup = lookups["yuv2depth_lookup"]
            else:
                logging.warning(f"Building yuv<=>depth lookup file: {lookups_file}")
                start = time.time()
                self.depth2yuv_lookup = self.build_depth2yuv_lookup(self.w, self.p, self.norm_to_8bit)
                self.yuv2depth_lookup = self.build_yuv2depth_lookup(self.w, self.p, self.norm_to_8bit)
                np.savez_compressed(
                    lookups_file,
                    depth2yuv_lookup=self.depth2yuv_lookup,
                    yuv2depth_lookup=self.yuv2depth_lookup,
                )
                logging.warning(f"Done: {time.time() - start}")

    @staticmethod
    @njit(parallel=True, cache=True)
    def build_depth2yuv_lookup(w, p, norm_to_8bit):
        lookup = np.empty((w, 3), dtype=np.uint8)
        for i in prange(lookup.shape[0]):
            d = i
            L = (d + (1 / 2)) / w

            H_a = (L / (p / 2)) % 2
            if H_a > 1:
                H_a = 2 - H_a

            H_b = ((L - (p / 4)) / (p / 2)) % 2
            if H_b > 1:
                H_b = 2 - H_b

            lookup[i, 0] = round(L * norm_to_8bit)
            lookup[i, 1] = round(H_a * norm_to_8bit)
            lookup[i, 2] = round(H_b * norm_to_8bit)
        return lookup

    @staticmethod
    @njit(parallel=True, cache=True)
    def build_yuv2depth_lookup(w, p, norm_to_8bit):
        lookup = np.empty((norm_to_8bit + 1, norm_to_8bit + 1, norm_to_8bit + 1), dtype=np.uint16)
        for i in prange(lookup.shape[0]):
            for j in prange(lookup.shape[1]):
                for k in prange(lookup.shape[2]):
                    L = i / norm_to_8bit
                    H_a = j / norm_to_8bit
                    H_b = k / norm_to_8bit
                    m_L = math.floor((4 * (L / p)) - 0.5) % 4
                    L_0 = L - ((L - (p / 8)) % p) + ((p / 4) * m_L) - (p / 8)
                    if m_L == 0:
                        delta = (p / 2) * H_a
                    elif m_L == 1:
                        delta = (p / 2) * H_b
                    elif m_L == 2:
                        delta = (p / 2) * (1 - H_a)
                    else:
                        delta = (p / 2) * (1 - H_b)
                    lookup[i, j, k] = round(w * (L_0 + delta))
        return lookup

    @staticmethod
    @njit(
        [uint8[:, :](uint8[:, :, :], uint16[:, :], uint8[:, :])],
        cache=True,
        parallel=True,
        nogil=True,
        fastmath=True,
    )
    def rgbd2yuv420p_averaged(rgb: np.ndarray, d: np.ndarray, depth2yuv_lookup: np.ndarray) -> np.ndarray:
        height = rgb.shape[0]
        width = rgb.shape[1] * 2  # stack the frames horizontally: [rgb][d]
        chroma_height = height // 4
        ret = np.empty((height + chroma_height * 2, width), dtype=np.uint8)
        for _i in prange(height // 2):
            for _j in prange(width // 2):
                i = _i * 2
                j = _j * 2
                u = v = 0.0
                for k in range(2):
                    for l in range(2):
                        if j < width // 2:
                            # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                            r, g, b = rgb[i + k, j + l]
                            y = max(min(round(0.299 * r + 0.587 * g + 0.114 * b), 255), 0)
                            u += max(min(128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b, 255), 0)
                            v += max(min(128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b, 255), 0)
                        else:
                            y, _u, _v = depth2yuv_lookup[d[i + k, j + l - width // 2]]
                            u += _u
                            v += _v
                        ret[i + k, j + l] = y
                chroma_x = j // 2
                if i % 4 >= 2:
                    chroma_x += width // 2
                chroma_y = height + i // 4
                ret[chroma_y, chroma_x] = round(u / 4)
                ret[chroma_y + chroma_height, chroma_x] = round(v / 4)
        return ret

    @staticmethod
    @njit(
        [uint8[:, :](uint8[:, :, :], uint16[:, :], uint8[:, :])],
        cache=True,
        parallel=True,
        nogil=True,
    )
    def rgbd2yuv420p_sampled(rgb: np.ndarray, d: np.ndarray, depth2yuv_lookup: np.ndarray) -> np.ndarray:
        height = rgb.shape[0]
        width = rgb.shape[1] * 2  # stack the frames horizontally: [rgb][d]
        chroma_height = height // 4
        ret = np.empty((height + chroma_height * 2, width), dtype=np.uint8)
        for i in prange(height):
            for j in prange(width):
                if j < width // 2:
                    # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                    r, g, b = rgb[i, j]
                    y = max(min(round(0.299 * r + 0.587 * g + 0.114 * b), 255), 0)
                    u = max(min(round(128 - 0.168736 * r - 0.331264 * g + 0.5 * b), 255), 0)
                    v = max(min(round(128 + 0.5 * r - 0.418688 * g - 0.081312 * b), 255), 0)
                else:
                    y, u, v = depth2yuv_lookup[d[i, j - width // 2]]
                ret[i, j] = y
                if i % 2 == j % 2 == 0:
                    offset = 0
                    if i % 4 >= 2:
                        offset = width // 2
                    chroma_x = offset + j // 2
                    chroma_y = height + i // 4
                    ret[chroma_y, chroma_x] = u
                    ret[chroma_y + chroma_height, chroma_x] = v
        return ret

    @staticmethod
    @njit(
        [numba.types.Tuple((uint8[:, :, :], uint16[:, :]))(uint8[:, :], uint16[:, :, :])],
        cache=True,
        parallel=True,
        nogil=True,
        fastmath=True,
    )
    def yuv420p2rgbd(x: np.ndarray, yuv2depth_lookup: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        width = x.shape[1]
        height = x.shape[0] * 2 // 3
        chroma_height = height // 4
        depth = np.empty((height, width // 2), dtype=np.uint16)
        rgb = np.empty((height, width // 2, 3), dtype=np.uint8)
        for i in prange(height):
            for j in prange(width):
                y = x[i, j]
                offset = 0
                if i % 4 >= 2:
                    offset = width // 2
                chroma_x = offset + j // 2
                chroma_y = height + i // 4
                u = x[chroma_y, chroma_x]
                v = x[chroma_y + chroma_height, chroma_x]
                if j < width // 2:
                    # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                    u -= 128
                    v -= 128
                    r = max(min(round(y + 1.402 * v), 255), 0)
                    g = max(min(round(y - 0.344136 * u - 0.714136 * v), 255), 0)
                    b = max(min(round(y + 1.772 * u), 255), 0)
                    rgb[i, j] = r, g, b
                else:
                    depth[i, j - width // 2] = yuv2depth_lookup[y, u, v]
        return rgb, depth

    def rgbd_to_video_frame(self, color: rs.frame, depth: rs.frame, pose: GPSPose) -> VideoFrame:
        rgb = np.asanyarray(color.get_data())
        d = np.asanyarray(depth.get_data())
        pose.write_to_color_frame(rgb)
        assert rgb.shape[:2] == d.shape
        vf = VideoFrame.from_ndarray(self.rgbd2yuv420p_averaged(rgb, d, self.depth2yuv_lookup), self.pixel_format)
        vf.color_range = ColorRange.JPEG  # Force full range color instead of limited (16-235)
        vf.colorspace = Colorspace.ITU601
        return vf

    def video_frame_to_rgbd(self, vf: VideoFrame) -> tuple[np.ndarray, np.ndarray, GPSPose | None]:
        vf.color_range = ColorRange.JPEG  # Force full range color instead of limited (16-235)
        vf.colorspace = Colorspace.ITU601
        frame = vf.to_ndarray(format=self.pixel_format)
        rgb, d = self.yuv420p2rgbd(frame, self.yuv2depth_lookup)
        pose = GPSPose.read_from_color_frame(rgb, clear_macroblocks=True)
        d[(d < self.min_valid_depth) | (d > self.max_valid_depth)] = 0
        return rgb, d, pose


class MultiWavelengthDepthEncoder(DepthEncoder, Protocol):
    pixel_format: ClassVar[str] = "yuv420p"

    # noinspection PyProtocol
    def __init__(self, depth_units: float, min_depth_meters: float, max_depth_meters: float):
        super().__init__(depth_units, min_depth_meters, max_depth_meters)
        self.min_valid_depth = round(min_depth_meters / depth_units)
        self.max_valid_depth = round(max_depth_meters / depth_units)
        self.stairs = 256
        self.p = math.ceil(self.max_valid_depth / self.stairs)

    @staticmethod
    @njit(
        [uint8[:, :](uint8[:, :, :], uint16[:, :], uint16, uint16)],
        cache=True,
        parallel=True,
        nogil=True,
        fastmath=True,
    )
    def rgbd2yuv420p(rgb: np.ndarray, d: np.ndarray, max_z: int, p: int) -> np.ndarray:
        height = rgb.shape[0]
        width = rgb.shape[1] * 2  # stack the frames horizontally: [rgb][d]
        chroma_height = height // 4
        norm_to_8bit = 2**8 - 1
        ret = np.empty((height + chroma_height * 2, width), dtype=np.uint8)
        for i in prange(height):
            for j in prange(width):
                if j < width // 2:
                    # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                    r, g, b = rgb[i, j]
                    y = max(min(round(0.299 * r + 0.587 * g + 0.114 * b), 255), 0)
                    u = max(min(round(128 - 0.168736 * r - 0.331264 * g + 0.5 * b), 255), 0)
                    v = max(min(round(128 + 0.5 * r - 0.418688 * g - 0.081312 * b), 255), 0)
                else:
                    z = d[i, j - width // 2]
                    I_b = z / max_z
                    I_r = 0.5 * (1 + math.sin(math.tau * z / p))
                    I_g = 0.5 * (1 + math.cos(math.tau * z / p))
                    y = round(I_b * norm_to_8bit)
                    u = round(I_r * norm_to_8bit)
                    v = round(I_g * norm_to_8bit)
                ret[i, j] = y
                if i % 2 == j % 2 == 0:
                    offset = 0
                    if i % 4 >= 2:
                        offset = width // 2
                    chroma_x = offset + j // 2
                    chroma_y = height + i // 4
                    ret[chroma_y, chroma_x] = u
                    ret[chroma_y + chroma_height, chroma_x] = v
        return ret

    @staticmethod
    @njit(
        [numba.types.Tuple((uint8[:, :, :], uint16[:, :]))(uint8[:, :], uint16, uint16)],
        cache=True,
        parallel=True,
        nogil=True,
        fastmath=True,
    )
    def yuv420p2rgbd(x: np.ndarray, max_z: int, p: int) -> tuple[np.ndarray, np.ndarray]:
        width = x.shape[1]
        height = x.shape[0] * 2 // 3
        chroma_height = height // 4
        norm_to_8bit = 2**8 - 1
        depth = np.empty((height, width // 2), dtype=np.uint16)
        rgb = np.empty((height, width // 2, 3), dtype=np.uint8)
        for i in prange(height):
            for j in prange(width):
                y = x[i, j]
                offset = 0
                if i % 4 >= 2:
                    offset = width // 2
                chroma_x = offset + j // 2
                chroma_y = height + i // 4
                u = x[chroma_y, chroma_x]
                v = x[chroma_y + chroma_height, chroma_x]
                if j < width // 2:
                    # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                    u -= 128
                    v -= 128
                    r = max(min(round(y + 1.402 * v), 255), 0)
                    g = max(min(round(y - 0.344136 * u - 0.714136 * v), 255), 0)
                    b = max(min(round(y + 1.772 * u), 255), 0)
                    rgb[i, j] = r, g, b
                else:
                    I_b = y / norm_to_8bit
                    I_r = u / norm_to_8bit
                    I_g = v / norm_to_8bit
                    phi_rg = math.atan2((I_r - 0.5), (I_g - 0.5))
                    phi_b = I_b * math.tau
                    K = (phi_b * max_z / p - phi_rg) / math.tau
                    phi = phi_rg + math.tau * round(K)
                    depth[i, j - width // 2] = round(phi * p / math.tau)
        return rgb, depth

    def rgbd_to_video_frame(self, color: rs.frame, depth: rs.frame, pose: GPSPose) -> VideoFrame:
        rgb = np.asanyarray(color.get_data())
        d = np.asanyarray(depth.get_data())
        pose.write_to_color_frame(rgb)
        assert rgb.shape[:2] == d.shape
        vf = VideoFrame.from_ndarray(self.rgbd2yuv420p(rgb, d, self.max_valid_depth, self.p), self.pixel_format)
        vf.color_range = ColorRange.JPEG  # Force full range color instead of limited (16-235)
        vf.colorspace = Colorspace.ITU601
        return vf

    def video_frame_to_rgbd(self, vf: VideoFrame) -> tuple[np.ndarray, np.ndarray, GPSPose | None]:
        vf.color_range = ColorRange.JPEG  # Force full range color instead of limited (16-235)
        vf.colorspace = Colorspace.ITU601
        frame = vf.to_ndarray(format=self.pixel_format)
        rgb, d = self.yuv420p2rgbd(frame, self.max_valid_depth, self.p)
        pose = GPSPose.read_from_color_frame(rgb, clear_macroblocks=True)
        d[(d < self.min_valid_depth) | (d > self.max_valid_depth)] = 0
        return rgb, d, pose


class ZhouDepthEncoder(DepthEncoder, Protocol):
    pixel_format: ClassVar[str] = "yuv420p"

    # noinspection PyProtocol
    def __init__(self, depth_units: float, min_depth_meters: float, max_depth_meters: float):
        super().__init__(depth_units, min_depth_meters, max_depth_meters)
        self.min_valid_depth = round(min_depth_meters / depth_units)
        self.max_valid_depth = round(max_depth_meters / depth_units)

    @staticmethod
    @njit(
        [uint8[:, :](uint8[:, :, :], uint16[:, :])],
        cache=True,
        parallel=True,
        nogil=True,
        fastmath=True,
    )
    def rgbd2yuv420p(rgb: np.ndarray, d: np.ndarray) -> np.ndarray:
        height = rgb.shape[0]
        width = rgb.shape[1] * 2  # stack the frames horizontally: [rgb][d]
        chroma_height = height // 4
        ret = np.empty((height + chroma_height * 2, width), dtype=np.uint8)
        for _i in prange(height // 2):
            for _j in prange(width // 2):
                i = _i * 2
                j = _j * 2
                chroma_x = j // 2
                if i % 4 >= 2:
                    chroma_x += width // 2
                chroma_y = height + i // 4
                if j < width // 2:
                    u = v = 0.0
                    for k in range(2):
                        for l in range(2):
                            # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                            r, g, b = rgb[i + k, j + l]
                            y = max(min(round(0.299 * r + 0.587 * g + 0.114 * b), 255), 0)
                            u += max(min(128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b, 255), 0)
                            v += max(min(128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b, 255), 0)
                            ret[i + k, j + l] = y
                    ret[chroma_y, chroma_x] = round(u / 4)
                    ret[chroma_y + chroma_height, chroma_x] = round(v / 4)
                else:
                    z = 0
                    for k in range(2):
                        for l in range(2):
                            z += d[i + k, j + l - width // 2]
                    z_mean = round(z / 4)
                    z = z_mean
                    for k in range(2):
                        for l in range(2):
                            if (
                                abs(z_mean - z) < abs(z_mean - d[i + k, j + l - width // 2])
                                and d[i + k, j + l - width // 2] > 0
                            ):
                                z = d[i + k, j + l - width // 2]
                    period = 2**8
                    z_upper = z >> 8
                    z_lower = z & 0xFF
                    phi_upper = (z_upper - 127) * math.tau / period
                    phi_lower = (z_lower - 127) * math.tau / period

                    ret[i, j] = round((period - 1) * 0.5 * (1 + math.cos(phi_upper - 2 * math.pi / 3)))
                    ret[chroma_y, chroma_x] = round((period - 1) * 0.5 * (1 + math.cos(phi_upper)))
                    ret[chroma_y + chroma_height, chroma_x] = round(
                        (period - 1) * 0.5 * (1 + math.cos(phi_upper + 2 * math.pi / 3))
                    )

                    ret[i + 1, j + 1] = round((period - 1) * 0.5 * (1 + math.cos(phi_lower - 2 * math.pi / 3)))
                    ret[i, j + 1] = round((period - 1) * 0.5 * (1 + math.cos(phi_lower)))
                    ret[i + 1, j] = round((period - 1) * 0.5 * (1 + math.cos(phi_lower + 2 * math.pi / 3)))
        return ret

    @staticmethod
    @njit(
        [numba.types.Tuple((uint8[:, :, :], uint16[:, :]))(uint8[:, :])],
        cache=True,
        parallel=True,
        nogil=True,
        fastmath=True,
    )
    def yuv420p2rgbd(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        width = x.shape[1]
        height = x.shape[0] * 2 // 3
        chroma_height = height // 4
        period = 2**8
        depth = np.empty((height, width // 2), dtype=np.uint16)
        rgb = np.empty((height, width // 2, 3), dtype=np.uint8)
        for _i in prange(height // 2):
            for _j in prange(width // 2):
                i = _i * 2
                j = _j * 2
                offset = 0
                if i % 4 >= 2:
                    offset = width // 2
                chroma_x = offset + j // 2
                chroma_y = height + i // 4
                u = x[chroma_y, chroma_x]
                v = x[chroma_y + chroma_height, chroma_x]
                if j < width // 2:
                    u -= 128
                    v -= 128
                    for k in range(2):
                        for l in range(2):
                            y = x[i + k, j + l]
                            # full-range YCbCr (BT601) color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                            r = max(min(round(y + 1.402 * v), 255), 0)
                            g = max(min(round(y - 0.344136 * u - 0.714136 * v), 255), 0)
                            b = max(min(round(y + 1.772 * u), 255), 0)
                            rgb[i + k, j + l] = r, g, b
                else:
                    I1 = np.int32(x[i, j])
                    I2 = np.int32(u)
                    I3 = np.int32(v)
                    z_upper = (
                        round((math.atan2(math.sqrt(3) * (I1 - I3), (2 * I2 - I1 - I3))) / math.tau * period) + 127
                    )
                    I1 = np.int32(x[i + 1, j + 1])
                    I2 = np.int32(x[i, j + 1])
                    I3 = np.int32(x[i + 1, j])
                    z_lower = (
                        round((math.atan2(math.sqrt(3) * (I1 - I3), (2 * I2 - I1 - I3))) / math.tau * period) + 127
                    )
                    for k in range(2):
                        for l in range(2):
                            depth[i + k, j + l - width // 2] = (z_upper << 8) + z_lower
        return rgb, depth

    def rgbd_to_video_frame(self, color: rs.frame, depth: rs.frame, pose: GPSPose) -> VideoFrame:
        rgb = np.asanyarray(color.get_data())
        d = np.asanyarray(depth.get_data())
        pose.write_to_color_frame(rgb)
        assert rgb.shape[:2] == d.shape
        vf = VideoFrame.from_ndarray(self.rgbd2yuv420p(rgb, d), self.pixel_format)
        vf.color_range = ColorRange.JPEG  # Force full range color instead of limited (16-235)
        vf.colorspace = Colorspace.ITU601
        return vf

    def video_frame_to_rgbd(self, vf: VideoFrame) -> tuple[np.ndarray, np.ndarray, GPSPose | None]:
        vf.color_range = ColorRange.JPEG  # Force full range color instead of limited (16-235)
        vf.colorspace = Colorspace.ITU601
        frame = vf.to_ndarray(format=self.pixel_format)
        rgb, d = self.yuv420p2rgbd(frame)
        pose = GPSPose.read_from_color_frame(rgb, clear_macroblocks=True)
        d[(d < self.min_valid_depth) | (d > self.max_valid_depth)] = 0
        return rgb, d, pose


if __name__ == "__main__":
    import time
    from PIL import Image

    test_d = np.random.randint(1500, 60000, (360, 640), dtype=np.uint16)
    test_d = test_d.repeat(2, axis=0).repeat(2, axis=1)
    # test_d = (np.full((720, 1280), 12000)).astype(np.uint16)

    iters = 10
    test_rgb = np.random.randint(0, 256, size=(test_d.shape[0], test_d.shape[1], 3), dtype=np.uint8)
    # with Image.open("/home/henry/Downloads/ghostrunner_poster_4k_hd_games-1280x720.jpg") as im:
    #     test_rgb = np.array(im)

    depth_encoder = TriangleDepthEncoder(0.0001, 0.15, 6)
    start = time.time()
    for _ in range(iters):
        yuv_encoded_rgbd_triangle = depth_encoder.rgbd2yuv420p_averaged(
            test_rgb, test_d, depth_encoder.depth2yuv_lookup
        )
    print(f"triangle rgbd2yuv420p: {time.time() - start}")
    start = time.time()
    for _ in range(iters):
        recovered_rgb_triangle, recovered_d_triangle = depth_encoder.yuv420p2rgbd(
            yuv_encoded_rgbd_triangle, depth_encoder.yuv2depth_lookup
        )
    print(f"triangle yuv420p2rgbd: {time.time() - start}")
    rgb_delta = np.absolute(test_rgb.astype(np.int32) - recovered_rgb_triangle.astype(np.int32))
    print(f"rgb delta: {np.average(rgb_delta)}")
    depth_delta = np.absolute(test_d.astype(np.int32) - recovered_d_triangle.astype(np.int32))
    print(f"depth delta: {np.average(depth_delta)}")

    depth_encoder = MultiWavelengthDepthEncoder(0.0001, 0.15, 6)
    start = time.time()
    for _ in range(iters):
        yuv_encoded_rgbd = depth_encoder.rgbd2yuv420p(test_rgb, test_d, depth_encoder.max_valid_depth, depth_encoder.p)
    print(f"multiwavelength rgbd2yuv420p: {time.time() - start}")
    start = time.time()
    for _ in range(iters):
        recovered_rgb, recovered_d = depth_encoder.yuv420p2rgbd(
            yuv_encoded_rgbd, depth_encoder.max_valid_depth, depth_encoder.p
        )
    print(f"multiwavelength yuv420p2rgbd: {time.time() - start}")
    rgb_delta = np.absolute(test_rgb.astype(np.int32) - recovered_rgb.astype(np.int32))
    print(f"rgb delta: {np.average(rgb_delta)}")
    depth_delta = np.absolute(test_d.astype(np.int32) - recovered_d.astype(np.int32))
    print(f"depth delta: {np.average(depth_delta)}")

    depth_encoder = ZhouDepthEncoder(0.0001, 0.15, 6)
    start = time.time()
    for _ in range(iters):
        yuv_encoded_rgbd = depth_encoder.rgbd2yuv420p(test_rgb, test_d)
    print(f"zhou rgbd2yuv420p: {time.time() - start}")
    start = time.time()
    for _ in range(iters):
        recovered_rgb, recovered_d = depth_encoder.yuv420p2rgbd(yuv_encoded_rgbd)
    print(f"zhou yuv420p2rgbd: {time.time() - start}")
    # assert np.array_equal(recovered_rgb, recovered_rgb_triangle)
    rgb_delta = np.absolute(test_rgb.astype(np.int32) - recovered_rgb.astype(np.int32))
    print(f"rgb delta: {np.average(rgb_delta)}")
    depth_delta = np.absolute(test_d.astype(np.int32) - recovered_d.astype(np.int32))
    print(f"depth delta: {np.average(depth_delta)}")

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(figsize=(13, 4), ncols=4)

    ax1.imshow(test_rgb)
    ax2.imshow(test_d)
    ax3.imshow(recovered_rgb)
    graph = ax4.imshow(depth_delta, cmap="gray")
    fig.colorbar(graph)
    plt.show()
