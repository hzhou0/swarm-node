import sys
from pathlib import Path

import open3d as o3d

import argparse


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize point cloud files from a directory.")
    parser.add_argument("output_dir", type=str, help="Path to the directory containing the .pcd files")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_dir():
        raise ValueError(f"The provided path '{output_dir}' is not a valid directory.")

    samples: list[o3d.geometry.PointCloud] = [o3d.io.read_point_cloud(p) for p in output_dir.glob("*.pcd")]
    if not samples:
        sys.exit("No .pcd files found in the specified directory.")
    center = samples[0].get_center()
    o3d.visualization.draw_geometries(
        samples,
        zoom=0.3412,
        lookat=[center[0], center[1], center[2]],
    )
