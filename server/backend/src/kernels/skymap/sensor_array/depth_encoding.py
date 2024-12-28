import math
import time
from pathlib import Path

import numba.core.types.containers
import numpy as np
from matplotlib import pyplot as plt
from numba import guvectorize, float64, uint16, uint8, njit, prange

# Adapted from the paper by the University College London at http://reality.cs.ucl.ac.uk/projects/depth-streaming/depth-streaming.pdf
# In YUV420, there are two bits used for each of the U and V samples. In selecting n_p, the integer period for H_a and H_b, the paper
# states n_p must be at most twice the number of output quantization levels, which in the case of YUV420 is channel dependent. Thus,
w = 2 ** 16
n_p = 512
p = n_p / w
# webrtc can sometimes use limited yuv, but this is configurable
# yuv_min = 16
# yuv_max = 235
norm_to_8bit = 2 ** 8 - 1

depth2yuv_lookup = np.empty((w, 3), dtype=np.uint8)


@njit(parallel=True, cache=True)
def build_depth2yuv_lookup(lookup):
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


yuv2depth_lookup = np.empty((norm_to_8bit + 1, norm_to_8bit + 1, norm_to_8bit + 1), dtype=np.uint16)


@njit(parallel=True, cache=True)
def build_yuv2depth_lookup(lookup):
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


this_dir = Path(__file__).parent
lookups_file = this_dir / "depth_encoding_lookup_tables.npz"

if lookups_file.exists():
    with np.load(lookups_file) as lookups:
        depth2yuv_lookup = lookups["depth2yuv_lookup"]
        yuv2depth_lookup = lookups["yuv2depth_lookup"]
else:
    print(f"Building yuv<=>depth lookup file: {lookups_file}")
    start = time.time()
    build_depth2yuv_lookup(depth2yuv_lookup)
    build_yuv2depth_lookup(yuv2depth_lookup)
    np.savez_compressed(lookups_file, yuv2depth_lookup=yuv2depth_lookup, depth2yuv_lookup=depth2yuv_lookup)
    print(f"Done: {time.time() - start}")


@njit([uint8[:, :, :](uint16[:, :], uint8[:, :])], cache=True, parallel=True, nogil=True)
def depth2yuv(x: np.ndarray, lookup: np.ndarray) -> np.ndarray:
    y = np.empty((x.shape[0], x.shape[1], 3), dtype=np.uint8)
    for i in prange(x.shape[0]):
        for j in prange(x.shape[1]):
            y[i, j] = lookup[x[i, j]]
    return y


@njit([uint16[:, :](uint8[:, :, :], uint16[:, :, :])], cache=True, parallel=True, nogil=True)
def yuv2depth(x: np.ndarray, lookup: np.ndarray) -> np.ndarray:
    ret = np.empty((x.shape[0], x.shape[1]), dtype=np.uint16)
    for i in prange(x.shape[0]):
        for j in prange(x.shape[1]):
            y, u, v = x[i, j]
            ret[i, j] = lookup[y, u, v]
    return ret


def yuv2yuv420p(x: np.ndarray) -> np.ndarray:
    # Extract Y, U, V channels
    y = x[:, :, 0]
    u = x[:, :, 1]
    v = x[:, :, 2]

    height, width, _ = x.shape
    # Subsample U and V for 4:2:0
    u = u[::2, ::2].reshape(height // 4, width)
    v = v[::2, ::2].reshape(height // 4, width)

    return np.vstack((y, u, v))


def yuv420p2yuv(x: np.ndarray) -> np.ndarray:
    height = x.shape[0] * 2 // 3
    width = x.shape[1]
    chroma_height = height // 4

    y = x[:height, :]
    u = x[height:height + chroma_height, :].reshape(height // 2, width // 2)
    v = x[height + chroma_height:height + 2 * chroma_height, :].reshape(height // 2, width // 2)

    u = u.repeat(2, axis=0).repeat(2, axis=1)
    v = v.repeat(2, axis=0).repeat(2, axis=1)
    return np.dstack((y, u, v))


@njit([uint8[:, :](uint16[:, :], uint8[:, :])], cache=True, parallel=True, nogil=True)
def depth2yuv420p(x: np.ndarray, lookup: np.ndarray) -> np.ndarray:
    height, width = x.shape
    chroma_height = height // 4
    ret = np.empty((height + chroma_height * 2, width), dtype=np.uint8)
    for i in prange(height):
        for j in prange(width):
            y, u, v = lookup[x[i, j]]
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


@njit([uint16[:, :](uint8[:, :], uint16[:, :, :])], cache=True, parallel=True, nogil=True)
def yuv420p2depth(x: np.ndarray, lookup: np.ndarray) -> np.ndarray:
    width = x.shape[1]
    height = x.shape[0] * 2 // 3
    chroma_height = height // 4
    ret = np.empty((height, width), dtype=np.uint16)
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
            ret[i, j] = lookup[y, u, v]
    return ret


@njit([uint8[:, :](uint8[:, :, :], uint16[:, :], uint8[:, :])], cache=True, parallel=True, nogil=True, fastmath=True)
def rgbd2yuv420p(rgb: np.ndarray, d: np.ndarray, depth2yuv_lookup: np.ndarray) -> np.ndarray:
    assert rgb.shape[:2] == d.shape
    height = rgb.shape[0]
    width = rgb.shape[1] * 2  # stack the frames horizontally: [rgb][d]
    chroma_height = height // 4
    ret = np.empty((height + chroma_height * 2, width), dtype=np.uint8)
    for _i in prange(height // 2):
        for _j in prange(width // 2):
            i = _i * 2
            j = _j * 2
            u = v = .0
            for k in range(2):
                for l in range(2):
                    if j < width // 2:
                        # full-range YCbCr color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                        r, g, b = rgb[i + k, j + l]
                        y = round(0.299 * r + 0.587 * g + 0.114 * b)
                        u += 128. - 0.168736 * r - 0.331264 * g + 0.5 * b
                        v += 128. + 0.5 * r - 0.418688 * g - 0.081312 * b
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


@njit([numba.types.Tuple((uint8[:, :, :], uint16[:, :]))(uint8[:, :], uint16[:, :, :])], cache=True, parallel=True,
      nogil=True, fastmath=True)
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
                # full-range YCbCr color conversion from https://en.wikipedia.org/wiki/YCbCr#JPEG_conversion
                u -= 128
                v -= 128
                r = max(min(round(y + 1.402 * v), 255), 0)
                g = max(min(round(y - 0.344136 * u - 0.714136 * v), 255), 0)
                b = max(min(round(y + 1.772 * u), 255), 0)
                rgb[i, j] = r, g, b
            else:
                depth[i, j - width // 2] = yuv2depth_lookup[y, u, v]
    return rgb, depth


@guvectorize([(uint8[:, :, :], float64, float64, uint16[:, :])], "(i,j,k),(),()->(i,j)", cache=True, nopython=True)
def rgb_to_depth(x, min_dist, max_dist, y):
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
                y[i, j] = ((min_dist + (max_dist - min_dist) * y[i, j] / 1529) * 1000 + 0.5)


if __name__ == "__main__":
    import time
    from PIL import Image

    test_d = (np.random.rand(720, 1280) * (2 ** 16 - 1)).astype(np.uint16)

    iters = 100
    start = time.time()
    for _ in range(iters):
        yuv_encoded = depth2yuv(test_d, depth2yuv_lookup)
        yuv420p_2step = yuv2yuv420p(yuv_encoded)
    print(f"2 step depth2yuv: {time.time() - start}")

    start = time.time()
    for _ in range(iters):
        yuv420p_1step = depth2yuv420p(test_d, depth2yuv_lookup)
    print(f"1 step depth2yuv: {time.time() - start}")

    assert np.array_equal(yuv420p_1step, yuv420p_2step)

    start = time.time()
    for _ in range(iters):
        yuv_recovered = yuv420p2yuv(yuv420p_1step)
        depth_decoded_2step = yuv2depth(yuv_recovered, yuv2depth_lookup)
    print(f"2 step yuv2depth: {time.time() - start}")

    start = time.time()
    for _ in range(iters):
        depth_decoded_1step = yuv420p2depth(yuv420p_1step, yuv2depth_lookup)
    print(f"1 step yuv2depth: {time.time() - start}")

    assert np.array_equal(depth_decoded_1step, depth_decoded_2step)

    delta = np.absolute(depth_decoded_2step.astype(np.int32) - test_d.astype(np.int32)).astype(np.uint16)
    print(np.average(delta))

    test_rgb = np.random.randint(0, 256, size=(test_d.shape[0], test_d.shape[1], 3), dtype=np.uint8)
    # with Image.open("/home/henry/Downloads/ghostrunner_poster_4k_hd_games-1280x720.jpg") as im:
    #     test_rgb = np.array(im)
    start = time.time()
    for _ in range(iters):
        yuv_encoded_rgbd = rgbd2yuv420p(test_rgb, test_d, depth2yuv_lookup)
    print(f"1 step rgbd2yuv420p: {time.time() - start}")

    start = time.time()
    for _ in range(iters):
        recovered_rgb, recovered_d = yuv420p2rgbd(yuv_encoded_rgbd, yuv2depth_lookup)
    print(f"1 step yuv420p2rgbd: {time.time() - start}")

    rgb_delta = np.absolute(test_rgb.astype(np.int32) - recovered_rgb.astype(np.int32))
    print(np.average(rgb_delta))
    depth_delta = np.absolute(test_d.astype(np.int32) - recovered_d.astype(np.int32))
    print(np.average(depth_delta))

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(figsize=(13, 4), ncols=4)

    ax1.imshow(test_rgb)
    ax2.imshow(recovered_rgb)
    ax3.imshow(test_d)
    graph = ax4.imshow(depth_delta, cmap='gray')
    fig.colorbar(graph)
    plt.show()
