import asyncio
import cv2 as cv
import numpy as np


class DepthCamera:
    def __init__(self):
        self.video_stream = cv.VideoCapture(0)
        if not self.video_stream.isOpened():
            print("Cannot open camera")
        self.video_stream.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*"MJPG"))
        self.video_stream.set(cv.CAP_PROP_FRAME_HEIGHT, 720)
        self.video_stream.set(cv.CAP_PROP_FRAME_WIDTH, 2560)

    def __del__(self):
        self.video_stream.release()
        cv.destroyAllWindows()

    async def read(self):
        while self.video_stream.isOpened():
            ret, frame = self.video_stream.read()
            if not ret:
                break
            cv.imshow('frame', frame)
            cv.waitKey(1000 // 30)

