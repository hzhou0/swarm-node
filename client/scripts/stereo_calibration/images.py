import cv2 as cv

from depth_camera import DepthCamera

if __name__ == '__main__':
    depth_camera = DepthCamera()
    n = 0
    while depth_camera.video_stream.isOpened():
        ret, img = depth_camera.video_stream.read()
        if not ret:
            break
        k = cv.waitKey(1000 // 30)
        if k == ord('q'):
            break
        elif k == ord('s'):
            cv.imwrite(f'../../static/stereo{n}.png', img)
            n += 1
        cv.imshow('frame', img)
