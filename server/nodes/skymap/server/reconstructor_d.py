import logging
import sys
import timeit
from multiprocessing import connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Lock

import numpy as np
import open3d as o3d

from ipc import write_state
from kernels.skymap.sensor_array.sensors import RGBDStream
from util import configure_root_logger


class CameraPose:
    def __init__(self, meta, mat):
        self.metadata = meta
        self.pose = mat

    def __str__(self):
        return (
                "Metadata : "
                + " ".join(map(str, self.metadata))
                + "\n"
                + "Pose : "
                + "\n"
                + np.array_str(self.pose)
        )


def read_trajectory(filename):
    traj = []
    with open(filename, "r") as f:
        metastr = f.readline()
        while metastr:
            metadata = list(map(int, metastr.split()))
            mat = np.zeros(shape=(4, 4))
            for i in range(4):
                matstr = f.readline()
                mat[i, :] = np.fromstring(matstr, dtype=float, sep=" \t")
            traj.append(CameraPose(metadata, mat))
            metastr = f.readline()
    return traj


def get_open3d_object_size(obj: o3d.geometry.PointCloud):
    size = sys.getsizeof(obj)  # Base object size
    if hasattr(obj, "points"):
        size += sys.getsizeof(obj.points) + obj.points.nbytes()
    if hasattr(obj, "colors"):
        size += sys.getsizeof(obj.colors) + obj.colors.nbytes()
    if hasattr(obj, "normals"):
        size += sys.getsizeof(obj.normals) + obj.normals.nbytes()
    return size


_state = None
_state_mem: SharedMemory | None = None
_state_lock: Lock | None = None


def _commit_state():
    global _state_mem, _state_lock, _state
    _state_mem = write_state(_state_mem, _state_lock, _state)


def main(state_mem: SharedMemory,
         state_lock: Lock,
         pipe: connection.Connection):
    global _state_mem, _state_lock
    _state_mem, _state_lock = state_mem, state_lock
    configure_root_logger()

    vis = o3d.visualization.Visualizer()
    vis.create_window()
    intrinsics = o3d.camera.PinholeCameraIntrinsic(width=1280, height=720, fx=641.162, fy=641.162, cx=639.135,
                                                   cy=361.356)
    pcd = None

    while True:
        try:
            if not pipe.poll():
                vis.poll_events()
                vis.update_renderer()
                continue
            mutation = pipe.recv()
            if mutation is None:
                continue
            rgb, d, pose = mutation
            if pose is None:
                continue
            im1 = o3d.geometry.Image(rgb)
            im2 = o3d.geometry.Image(d)
            rgbd_img: o3d.geometry.RGBDImage = (o3d.geometry.RGBDImage
                                                .create_from_color_and_depth(im1, im2,
                                                                             convert_rgb_to_intensity=False,
                                                                             depth_scale=1 / RGBDStream.depth_units,
                                                                             depth_trunc=RGBDStream.max_depth_meters))
            if pcd is None:
                pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
                vis.add_geometry(pcd)
            else:
                vis.remove_geometry(pcd, reset_bounding_box=False)
                pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd_img, intrinsics)
                vis.add_geometry(pcd, reset_bounding_box=False)
        except Exception as e:
            logging.exception(e)


if __name__ == "__main__":
    redwood_rgbd = o3d.data.SampleRedwoodRGBDImages()
    camera_poses = read_trajectory(redwood_rgbd.odometry_log_path)
    volume = o3d.pipeline_tmpls.integration.ScalableTSDFVolume(
        voxel_length=4.0 / 512.0,
        sdf_trunc=0.04,
        color_type=o3d.pipeline_tmpls.integration.TSDFVolumeColorType.RGB8,
    )

    for i in range(len(camera_poses)):
        print("Integrate {:d}-th image into the volume.".format(i))
        color = o3d.io.read_image(redwood_rgbd.color_paths[i])
        depth = o3d.io.read_image(redwood_rgbd.depth_paths[i])
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            color, depth, depth_trunc=4.0, convert_rgb_to_intensity=False
        )
        start = timeit.default_timer()
        # o3d.visualization.draw_geometries([rgbd])
        volume.integrate(
            rgbd,
            o3d.camera.PinholeCameraIntrinsic(
                o3d.camera.PinholeCameraIntrinsicParameters.PrimeSenseDefault
            ),
            np.linalg.inv(camera_poses[i].pose),
        )
        end = timeit.default_timer()
        print(end - start)

    mesh: o3d.geometry.TriangleMesh = volume.extract_triangle_mesh()
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh("test.glb", mesh, compressed=True)
    # o3d.visualization.draw_geometries([pcd])

    # print("Extract a triangle mesh from the volume and visualize it.")
    # mesh = volume.extract_triangle_mesh()
    # mesh.compute_vertex_normals()
    # o3d.visualization.draw_geometries(
    #     [mesh],
    #     front=[0.5297, -0.1873, -0.8272],
    #     lookat=[2.0712, 2.0312, 1.7251],
    #     up=[-0.0558, -0.9809, 0.1864],
    #     zoom=0.47,
    # )
