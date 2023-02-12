import numpy as np
import cv2 as cv
import glob


def find_points():
    ################ FIND CHESSBOARD CORNERS - OBJECT POINTS AND IMAGE POINTS #############################
    chessboard_size = (8, 6)
    # termination criteria
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    # prepare object points, like (0,0,0), (1,0,0), (2,0,0) ....,(6,5,0)
    objp = np.zeros((chessboard_size[0] * chessboard_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:chessboard_size[0], 0:chessboard_size[1]].T.reshape(-1, 2)
    size_of_chessboard_squares_mm = 37.5
    objp = objp * size_of_chessboard_squares_mm
    # Arrays to store object points and image points from all the images.
    obj_points = []  # 3d point in real world space
    img_points_l = []  # 2d points in image plane.
    img_points_r = []  # 2d points in image plane.
    stereo_images = sorted(glob.glob("../../static/*.png"))
    assert len(stereo_images) > 0
    for stereo_image in stereo_images:
        grayscale_l = cv.cvtColor(cv.imread(stereo_image)[:, :1280], cv.COLOR_BGR2GRAY)
        grayscale_r = cv.cvtColor(cv.imread(stereo_image)[:, 1280:], cv.COLOR_BGR2GRAY)

        # Find the chess board corners
        ret_l, corners_l = cv.findChessboardCorners(grayscale_l, chessboard_size, None)
        ret_r, corners_r = cv.findChessboardCorners(grayscale_r, chessboard_size, None)

        # If found, add object points, image points (after refining them)
        if ret_l and ret_r == True:
            obj_points.append(objp)

            corners_l = cv.cornerSubPix(grayscale_l, corners_l, (11, 11), (-1, -1), criteria)
            img_points_l.append(corners_l)

            corners_r = cv.cornerSubPix(grayscale_r, corners_r, (11, 11), (-1, -1), criteria)
            img_points_r.append(corners_r)

            # Draw and display the corners
            cv.drawChessboardCorners(grayscale_l, chessboard_size, corners_l, ret_l)
            cv.imshow('img left', grayscale_l)
            cv.drawChessboardCorners(grayscale_r, chessboard_size, corners_r, ret_r)
            cv.imshow('img right', grayscale_r)
            cv.waitKey(100)
    cv.destroyAllWindows()
    return obj_points, img_points_l, img_points_r, grayscale_l.shape[::-1], grayscale_r.shape[::-1]


def stereo_calibrate(obj_points, img_points_l, img_points_r, img_shape_l, img_shape_r):
    # Individual camera calibration
    ret, camera_matrix_l, dist_l, _, _ = cv.calibrateCamera(obj_points, img_points_l, img_shape_l, None, None)
    assert ret
    opt_matrix_l, _ = cv.getOptimalNewCameraMatrix(camera_matrix_l, dist_l, img_shape_l, 1, img_shape_l)

    ret, camera_matrix_r, dist_r, _, _ = cv.calibrateCamera(obj_points, img_points_r, img_shape_r, None, None)
    assert ret
    opt_matrix_r, _ = cv.getOptimalNewCameraMatrix(camera_matrix_r, dist_r, img_shape_r, 1, img_shape_r)
    # Stereo Vision Calibration
    flags = 0
    flags |= cv.CALIB_FIX_INTRINSIC
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    # This step is performed to transformation between the two cameras and calculate Essential and Fundamental matrix
    ret, opt_matrix_l, dist_l, opt_matrix_r, dist_r, r, t, e, f = cv.stereoCalibrate(obj_points, img_points_l,
                                                                                     img_points_r, opt_matrix_l, dist_l,
                                                                                     opt_matrix_r, dist_r, img_shape_l,
                                                                                     criteria, flags)
    assert ret
    return opt_matrix_l, opt_matrix_r, dist_l, dist_r, r, t, e, f


if __name__ == '__main__':
    op, ipl, ipr, isl, isr = find_points()

    oml, omr, dl, dr, r, t, e, f = stereo_calibrate(op, ipl, ipr, isl, isr)

    print("Saving intrinsic camera info")
    datafile = cv.FileStorage("../../static/camera_intrinsic_properties1.yml", cv.FILE_STORAGE_WRITE)
    datafile.write('newCameraMatrixL', oml)
    datafile.write('distL', dl)
    datafile.write('newCameraMatrixR', omr)
    datafile.write('distR', dr)

    ########## Stereo Rectification #################################################  #
    # rectifyScale = 1
    # rectL, rectR, projMatrixL, projMatrixR, Q, roi_L, roi_R = cv.stereoRectify(newCameraMatrixL, distL,
    #                                                                            newCameraMatrixR, distR,
    #                                                                            grayL.shape[::-1], rot, trans,
    #                                                                            rectifyScale, (0, 0))
    # stereoMapL = cv.initUndistortRectifyMap(newCameraMatrixL, distL, rectL, projMatrixL, grayL.shape[::-1], cv.CV_16SC2)
    # stereoMapR = cv.initUndistortRectifyMap(newCameraMatrixR, distR, rectR, projMatrixR, grayR.shape[::-1], cv.CV_16SC2)
    # print("Saving parameters!")  # cv_file = cv.FileStorage('../../static/stereoMap.xml', cv.FILE_STORAGE_WRITE)
    # cv_file.write('stereoMapL_x', stereoMapL[0])
    # cv_file.write('stereoMapL_y', stereoMapL[1])
    # cv_file.write('stereoMapR_x', stereoMapR[0])
    # cv_file.write('stereoMapR_y', stereoMapR[1])
    # cv_file.release()
