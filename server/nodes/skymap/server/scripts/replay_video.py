import cv2

from swarmnode_skymap_common import (
    ZhouDepthEncoder,
    depth_units,
    min_depth_meters,
    max_depth_meters,
    GPSPose,
    macroblock_size,
)

video_path = "/home/henry/skymap-server/2025-03-09T19-19-44/video/rgbd-video.avi"

cap = cv2.VideoCapture(video_path)
if not cap.isOpened():
    raise ValueError("Error opening video file")

decoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)


while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
    gps_blocks = frame[
        : GPSPose.height_blocks * macroblock_size,
        : GPSPose.width_blocks * macroblock_size,
        :,
    ]
    gps = GPSPose.read_from_color_frame(frame, clear_macroblocks=False)
    if gps is None:
        continue
    print(gps)
    # Process the frame here if needed
    cv2.imshow("Frame", frame)
    if cv2.waitKey(0) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
