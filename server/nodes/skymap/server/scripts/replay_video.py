import cv2
import numpy as np
import open3d as o3d

from server.nodes.skymap.server.integrator import ReconstructionVolume
from swarmnode_skymap_common import (
    ZhouDepthEncoder,
    depth_units,
    min_depth_meters,
    max_depth_meters,
    GPSPose,
    macroblock_size,
)

voxel_size = ReconstructionVolume.VOXEL_SIZE
max_correspondence_distance_fine = voxel_size * 1.5
intrinsics = ReconstructionVolume.INTRINSICS

option = o3d.pipelines.odometry.OdometryOption(
    depth_max=max_depth_meters, depth_min=min_depth_meters
)
odo_init = np.identity(4)
print(option)

if __name__ == "__main__":
    video_path = "/home/henry/skymap-server/2025-03-09T19-29-21/video/rgbd-video.avi"

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("Error opening video file")

    decoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)

    target_rgbd: o3d.geometry.RGBDImage | None = None
    src_rgbd: o3d.geometry.RGBDImage | None = None
    while cap.isOpened():
        target_rgbd = src_rgbd
        ret, frame = cap.read()
        if not ret:
            break
        gps_blocks = frame[
            : GPSPose.height_blocks * macroblock_size,
            : GPSPose.width_blocks * macroblock_size,
            :,
        ]
        GPSPose.read_from_color_frame(frame, clear_macroblocks=True)
        rgb, d = decoder.yuv420p2rgbd(cv2.cvtColor(frame, cv2.COLOR_RGB2YUV_I420))

        src_rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(rgb),
            o3d.geometry.Image(d),
            depth_scale=1 / depth_units,
            depth_trunc=6,
            convert_rgb_to_intensity=False,
        )
        if target_rgbd is None:
            continue
        else:
            success, trans, _ = o3d.pipelines.odometry.compute_rgbd_odometry(
                src_rgbd,
                target_rgbd,
                intrinsics,
                odo_init,
                o3d.pipelines.odometry.RGBDOdometryJacobianFromHybridTerm(),
                option,
            )
            if not success:
                print("alignment failed")
                continue
            print("Using Hybrid RGB-D Odometry")
            print(trans)
            src_pcd = o3d.geometry.PointCloud.create_from_rgbd_image(src_rgbd, intrinsics)
            target_pcd = o3d.geometry.PointCloud.create_from_rgbd_image(target_rgbd, intrinsics)
            src_pcd.transform(trans)
            o3d.visualization.draw_geometries(
                [src_pcd, src_rgbd],
                zoom=0.48,
                front=[0.0999, -0.1787, -0.9788],
                lookat=[0.0345, -0.0937, 1.8033],
                up=[-0.0067, -0.9838, 0.1790],
            )

    cap.release()
    cv2.destroyAllWindows()
