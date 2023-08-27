import asyncio
import pickle
from dataclasses import dataclass
from typing import Literal

import cv2 as cv
import numpy as np
from nptyping import NDArray, Float, Int
import matplotlib.pyplot as plt


@dataclass()
class BoundingBox:
    x: int
    y: int
    w: int
    h: int


@dataclass()
class RectifySystem:
    @dataclass()
    class Props:
        rectifier: NDArray[Literal["3,3"], Float]
        projector: NDArray[Literal["3,4"], Float]
        undistort_map: tuple[NDArray[Literal["*,*,2"], Int], NDArray[Literal["*,*"], Int]]
        # bounding box
        bb: BoundingBox

    l: Props
    r: Props
    # image dimensions
    dims: tuple[int, int]
    # disparity -> depth map
    dd_map: NDArray[Literal["4,4"], Float]


class DepthCamera:
    def __init__(self):
        with open("static/rectify_system.pkl", 'rb') as f:
            self.rs: RectifySystem = pickle.load(f)
        self.vid_stream = cv.VideoCapture(0)
        if not self.vid_stream.isOpened():
            print("Cannot open camera")
        self.vid_stream.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*"MJPG"))
        self.vid_stream.set(cv.CAP_PROP_FRAME_HEIGHT, 720)
        self.vid_stream.set(cv.CAP_PROP_FRAME_WIDTH, 2560)
        self.bm = cv.StereoBM_create(128, 19)
        self.bm.setSpeckleWindowSize(200)
        self.bm.setSpeckleRange(1)
        self.bm.setUniquenessRatio(12)


    def __del__(self):
        self.vid_stream.release()
        cv.destroyAllWindows()

    def read(self):
        while self.vid_stream.isOpened():
            ret, frame = self.vid_stream.read()
            if not ret:
                break
            frame = cv.cvtColor(frame, cv.COLOR_RGB2GRAY)

            frame_l = frame[:, :self.rs.dims[0]]
            frame_l = cv.remap(frame_l, *self.rs.l.undistort_map, cv.INTER_LANCZOS4, cv.BORDER_CONSTANT)
            frame_r = frame[:, self.rs.dims[0]:]
            frame_r = cv.remap(frame_r, *self.rs.r.undistort_map, cv.INTER_LANCZOS4, cv.BORDER_CONSTANT)
            frame_disp = self.bm.compute(frame_l, frame_r)
            frame_disp = cv.normalize(frame_disp, frame_disp, 0, 255, cv.NORM_MINMAX, cv.CV_8U)
            #s = cv.reprojectImageTo3D(frame_disp.astype(np.float32) / 16, self.rs.dd_map)
            # s = cv.cvtColor(s, cv.COLOR_RGB2GRAY)
            cv.imshow('f', frame_r)
            cv.imshow('disp', frame_disp)
            cv.waitKey(1000 // 30)


if __name__ == '__main__':
    depth_camera = DepthCamera()
    depth_camera.read()
