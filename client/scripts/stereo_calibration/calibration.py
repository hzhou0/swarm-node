import pickle
from typing import List, Literal, NamedTuple
from dataclasses import dataclass, field
from nptyping import NDArray, Float, Int
import numpy as np
import cv2 as cv
import glob

from depth_camera import RectifySystem, BoundingBox


@dataclass()
class PointsInfo:
    @dataclass()
    class FramePoints:
        points: List[NDArray[Literal["2,*"], Float]] = field(default_factory=list)
        dims: tuple[int, int] = None, None  # image dimensions

    obj_points: List[NDArray[Literal["3,*"], Float]] = field(default_factory=list)
    l: FramePoints = field(default_factory=FramePoints)
    r: FramePoints = field(default_factory=FramePoints)


def find_points(stereo_img_paths: List[str], chessboard_size: tuple[int, int], chessboard_square_mm: float,
                show: bool = True) -> PointsInfo:
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    objp = np.zeros((chessboard_size[0] * chessboard_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:chessboard_size[0], 0:chessboard_size[1]].T.reshape(-1, 2)
    objp = objp * chessboard_square_mm
    points_info = PointsInfo()
    for stereo_img in stereo_img_paths:
        grayscale_l = cv.cvtColor(cv.imread(stereo_img)[:, :1280], cv.COLOR_BGR2GRAY)
        grayscale_r = cv.cvtColor(cv.imread(stereo_img)[:, 1280:], cv.COLOR_BGR2GRAY)

        # Find the chess board corners
        ret_l, corners_l = cv.findChessboardCorners(grayscale_l, chessboard_size, None)
        corners_l = np.squeeze(corners_l)
        ret_r, corners_r = cv.findChessboardCorners(grayscale_r, chessboard_size, None)
        corners_r = np.squeeze(corners_r)

        # If found, add object points, image points (after refining them)
        if ret_l and ret_r:
            points_info.obj_points.append(objp)
            points_info.l.points.append(cv.cornerSubPix(grayscale_l, corners_l, (11, 11), (-1, -1), criteria))
            points_info.r.points.append(cv.cornerSubPix(grayscale_r, corners_r, (11, 11), (-1, -1), criteria))

            # Draw and display the corners
            if show:
                cv.drawChessboardCorners(grayscale_l, chessboard_size, points_info.l.points[-1], ret_l)
                cv.imshow('img left', grayscale_l)
                cv.drawChessboardCorners(grayscale_r, chessboard_size, points_info.r.points[-1], ret_r)
                cv.imshow('img right', grayscale_r)
                while cv.waitKey(100) != ord('n'):
                    pass
    points_info.l.dims, points_info.r.dims = grayscale_l.shape[::-1], grayscale_r.shape[::-1]
    cv.destroyAllWindows()
    return points_info


@dataclass()
class FrameSystem:
    @dataclass()
    class FrameProps:
        optimal: NDArray[Literal["3,3"], Float] = None
        distortion: NDArray[Literal["5"], Float] = None

    l: FrameProps = field(default_factory=FrameProps)
    r: FrameProps = field(default_factory=FrameProps)
    # Rotation matrix
    R: NDArray[Literal["3,3"], Float] = None
    # Translation matrix
    T: NDArray[Literal["3,1"], Float] = None
    # Essential matrix
    E: NDArray[Literal["3,3"], Float] = None
    # Fundamental matrix
    F: NDArray[Literal["3,3"], Float] = None


def stereo_calibrate(p: PointsInfo) -> FrameSystem:
    fs = FrameSystem()
    # Individual camera calibration
    ret, fs.l.optimal, fs.l.distortion, *_ = cv.calibrateCamera(p.obj_points, p.l.points, p.l.dims, None, None)
    assert ret
    fs.l.optimal, _ = cv.getOptimalNewCameraMatrix(fs.l.optimal, fs.l.distortion, p.l.dims, 1)

    ret, fs.r.optimal, fs.r.distortion, *_ = cv.calibrateCamera(p.obj_points, p.r.points, p.r.dims, None, None)
    assert ret
    fs.r.optimal, _ = cv.getOptimalNewCameraMatrix(fs.r.optimal, fs.r.distortion, p.r.dims, 1)

    # Stereo Vision Calibration
    flags = 0
    flags |= cv.CALIB_FIX_INTRINSIC
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    # This step is performed to transformation between the two cameras and calculate Essential and Fundamental matrix
    x = cv.stereoCalibrate(p.obj_points, p.l.points, p.r.points, fs.l.optimal, fs.l.distortion, fs.r.optimal,
                           fs.r.distortion, p.l.dims, criteria, flags)
    ret, fs.l.optimal, fs.l.distortion, fs.r.optimal, fs.r.distortion, fs.R, fs.T, fs.E, fs.F = x
    assert ret
    return fs


def rectify(fs: FrameSystem, dims: tuple[int, int], rectify_scale: int = 1, map_type=cv.CV_16SC2):
    x = cv.stereoRectify(fs.l.optimal, fs.l.distortion, fs.r.optimal, fs.r.distortion, dims, fs.R, fs.T, rectify_scale)
    rect_l, rect_r, proj_l, proj_r, disparity_depth, roi_l, roi_r = x
    map_l = cv.initUndistortRectifyMap(fs.l.optimal, fs.l.distortion, rect_l, proj_l, dims, map_type)
    map_r = cv.initUndistortRectifyMap(fs.r.optimal, fs.r.distortion, rect_r, proj_r, dims, map_type)
    return RectifySystem(RectifySystem.Props(rect_l, proj_l, map_l, BoundingBox(*roi_l)),
                         RectifySystem.Props(rect_r, proj_r, map_r, BoundingBox(*roi_r)), dims, disparity_depth)


if __name__ == '__main__':
    # object points, image points (left), image points (right), image size (left), image size (right)
    points = find_points(sorted(glob.glob("../../static/*.png")), (8, 6), 37.5, False)
    frame_system = stereo_calibrate(points)
    rectify_system = rectify(frame_system, points.l.dims, 1)
    # crop the image
    print("Saving intrinsic camera info")
    with open("../../static/rectify_system.pkl", 'wb') as f:
        pickle.dump(rectify_system, f)
