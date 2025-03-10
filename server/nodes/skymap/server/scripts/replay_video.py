import time
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
import os

from server.nodes.skymap.server.integrator import ReconstructionVolume
from swarmnode_skymap_common import (
    ZhouDepthEncoder,
    depth_units,
    min_depth_meters,
    max_depth_meters,
    GPSPose,
    macroblock_size,
)

intrinsics = ReconstructionVolume.INTRINSICS


if __name__ == "__main__":
    frame_path = Path("/home/henry/skymap-server/drone1/frames")

    decoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)

    target_rgbd: o3d.geometry.RGBDImage | None = None
    src_rgbd: o3d.geometry.RGBDImage | None = None

    npz_files = []
    for file_name in sorted(os.listdir(frame_path)):
        if file_name.endswith(".npz"):
            npz_files.append(file_name)

    vis = o3d.visualization.VisualizerWithKeyCallback()
    vis.create_window()
    once = True
    next_frame = False

    def next_frame_callback(_):
        global next_frame
        next_frame = True

    vis.register_key_callback(32, next_frame_callback)
    for file_name in npz_files:
        with np.load(frame_path / file_name) as npz_file:
            npz_file: np.lib.npyio.NpzFile
            for i in range(30):  # Process arrays from array_0.npy to array_29.npy
                vis.clear_geometries()
                array_name = f"arr_{i}"
                frame = npz_file.get(array_name)
                if frame is None:
                    break
                rgb, d, gps = decoder.video_frame_to_rgbd(frame)

                src_rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                    o3d.geometry.Image(rgb),
                    o3d.geometry.Image(d),
                    depth_scale=1 / depth_units,
                    depth_trunc=max_depth_meters,
                    convert_rgb_to_intensity=False,
                )
                src_pcd = o3d.geometry.PointCloud.create_from_rgbd_image(src_rgbd, intrinsics)

                vis.add_geometry(src_pcd, reset_bounding_box=True)
                vis.add_geometry(src_rgbd)
                vis.get_view_control().set_zoom(0.48)
                vis.get_view_control().set_front([0.0999, -0.1787, -0.9788])
                vis.get_view_control().set_lookat([0.0345, -0.0937, 1.8033])
                vis.get_view_control().set_up([-0.0067, -0.9838, 0.1790])
                vis.update_renderer()
                while not next_frame:
                    vis.poll_events()
                    vis.update_renderer()
                    time.sleep(0.01)
                next_frame = False
    vis.destroy_window()
