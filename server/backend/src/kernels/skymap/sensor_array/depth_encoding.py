import math
import time

import numpy as np
from matplotlib import pyplot as plt
from numba import guvectorize, float64, uint16, uint8, njit, prange

# Adapted from the paper by the University College London at http://reality.cs.ucl.ac.uk/projects/depth-streaming/depth-streaming.pdf
# In YUV420, there are two bits used for each of the U and V samples. In selecting n_p, the integer period for H_a and H_b, the paper
# states n_p must be at most twice the number of output quantization levels, which in the case of YUV420 is channel dependent. Thus,
w = 2 ** 16
n_p = 1024
p = n_p / w
# webrtc can sometimes use limited yuv, but this is configurable
# yuv_min = 16
# yuv_max = 235
norm_to_8bit = 2 ** 8 - 1

depth2yuv_lookup = np.empty((w, 3), dtype=np.uint8)


def build_depth2yuv_lookup(lookup):
    for i in range(lookup.shape[0]):
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


def depth_to_yuv(x: np.ndarray) -> np.ndarray:
    return _depth_to_yuv(x, depth2yuv_lookup)


@guvectorize([(uint16[:, :], uint16[:, :], uint8[:, :, :])], "(i,j),(z,k)->(i,j,k)", nopython=True)
def _depth_to_yuv(x: np.ndarray, lookup: np.ndarray, y: np.ndarray):
    for i in range(x.shape[0]):
        for j in range(x.shape[1]):
            y[i, j] = lookup[x[i, j]]


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


def yuv_to_depth(x: np.ndarray):
    return _yuv_to_depth(x, yuv2depth_lookup)


@guvectorize([(uint8[:, :, :], uint16[:, :, :], uint16[:, :])], "(i,j,k),(a,a,a)->(i,j)", nopython=True)
def _yuv_to_depth(x: np.ndarray, lookup: np.ndarray, _y: np.ndarray):
    for i in range(x.shape[0]):
        for j in range(x.shape[1]):
            y, u, v = x[i, j]
            _y[i, j] = lookup[y, u, v]


print("Building depth2yuv lookup")
start = time.time()
build_depth2yuv_lookup(depth2yuv_lookup)
build_yuv2depth_lookup(yuv2depth_lookup)
print(f"Building depth2yuv lookup done: {time.time() - start}")


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

    test_arr = (np.random.rand(1280, 720) * (2 ** 16 - 1)).astype(np.uint16)
    start = time.time()
    yuv_encoded = depth_to_yuv(test_arr)
    print(time.time() - start)

    start = time.time()
    yuv_decoded = yuv_to_depth(yuv_encoded)
    print(time.time() - start)
    delta = np.absolute(yuv_decoded.astype(np.int32) - test_arr.astype(np.int32)).astype(np.uint16)
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(figsize=(13, 4), ncols=4)

    ax1.imshow(test_arr)
    ax2.imshow(yuv_encoded)
    ax3.imshow(yuv_decoded)

    print(np.average(delta))
    graph = ax4.imshow(delta, cmap='gray')
    fig.colorbar(graph)
    plt.show()
