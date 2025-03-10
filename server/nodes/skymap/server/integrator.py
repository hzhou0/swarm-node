import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import open3d as o3d
from numpy.linalg import LinAlgError


class Chunk:
    def __init__(self, pcd: o3d.geometry.PointCloud):
        self.pcd = pcd
        self.lock = threading.Lock()


class ReconstructionVolume:
    IMAGE_THRESHOLD = 500
    IN_MEMORY_CHUNKS = 300
    CHUNK_SIZE = 5
    VOXEL_SIZE = 0.02
    INTRINSICS = o3d.camera.PinholeCameraIntrinsic(848, 480, 424.770, 424.770, 423.427, 240.898)

    def __init__(self, output_base_path: Path):
        self.volume = o3d.pipelines.integration.ScalableTSDFVolume(
            voxel_length=self.VOXEL_SIZE,
            sdf_trunc=self.VOXEL_SIZE * 5,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
        )
        self.num_images = 0
        self.chunks: dict[tuple[int, int, int], Chunk] = {}
        self.pcd_queue: asyncio.Queue[o3d.geometry.PointCloud] = asyncio.Queue(maxsize=2)
        self.active = True
        self.process_pcd_task_alive = asyncio.Event()
        self.write_to_disk_task_alive = asyncio.Event()
        self.vis_task_alive = asyncio.Event()
        self.output = output_base_path
        self.output.mkdir(exist_ok=True, parents=True)
        assert output_base_path.is_dir()
        self.vis = o3d.visualization.Visualizer()
        asyncio.create_task(self.process_pcd_task())
        asyncio.create_task(self.write_to_disk_task())

    def start_visualization(self):
        if self.vis_task_alive.is_set():
            return
        self.vis_task_alive.set()
        self.vis.create_window()
        asyncio.create_task(self.vis_task())

    async def vis_task(self):
        async def rerender():
            while self.active:
                self.vis.poll_events()
                self.vis.update_renderer()
                await asyncio.sleep(0.1)

        asyncio.create_task(rerender())
        pcd: o3d.geometry.PointCloud | None = None
        once = True
        while self.active:
            last_pcd = pcd
            pcd = await asyncio.to_thread(self.volume.extract_point_cloud)
            if pcd.has_points():
                if once:
                    reset = True
                    once = False
                else:
                    reset = False
                self.vis.remove_geometry(last_pcd, reset_bounding_box=reset)
                self.vis.add_geometry(pcd, reset_bounding_box=reset)
                logging.debug(f"rendering pcd with {np.asarray(pcd.points).shape[0]} points")
                self.vis.update_renderer()
            await asyncio.sleep(5)
        self.vis.destroy_window()
        self.vis_task_alive.clear()

    @classmethod
    def combine_pcd(
        cls,
        box: o3d.geometry.AxisAlignedBoundingBox,
        source: o3d.geometry.PointCloud,
        target: o3d.geometry.PointCloud,
    ) -> o3d.geometry.PointCloud:
        result_icp = cls.pt2pt_pcd_combine(source, target)

        if result_icp:
            source: o3d.geometry.PointCloud = source.transform(result_icp.transformation)
            combined: o3d.geometry.PointCloud = (source + target).crop(box)
        else:
            if np.asarray(target.points).size > np.asarray(source.points).size:
                combined = target
            else:
                combined = source
            logging.debug("failed to combine")
        combine, _ = combined.remove_statistical_outlier(16, 3)
        return combined.voxel_down_sample(voxel_size=cls.VOXEL_SIZE)

    @classmethod
    def pt2pt_pcd_combine(cls, source, target):
        result_icp: o3d.pipelines.registration.RegistrationResult
        try:
            result_icp = o3d.pipelines.registration.registration_icp(
                source,
                target,
                max_correspondence_distance=1,
                estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPlane(
                    o3d.pipelines.registration.TukeyLoss(cls.VOXEL_SIZE / 2)
                ),
                criteria=o3d.pipelines.registration.ICPConvergenceCriteria(
                    relative_fitness=1e-8, relative_rmse=1e-8, max_iteration=3000
                ),
            )
            return result_icp
        except:
            return None

    @classmethod
    def colored_pcd_combine(cls, source, target):
        result_icp: o3d.pipelines.registration.RegistrationResult | None = None
        voxel_radius = [cls.VOXEL_SIZE, cls.VOXEL_SIZE / 2, cls.VOXEL_SIZE / 4]
        max_iter = [50, 30, 14]
        current_transformation = np.identity(4)
        for scale in range(3):
            i = max_iter[scale]
            radius = voxel_radius[scale]

            source_down = source.voxel_down_sample(radius)
            target_down = target.voxel_down_sample(radius)

            source_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius * 2, max_nn=30))
            target_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius * 2, max_nn=30))
            try:
                result_icp: o3d.pipelines.registration.RegistrationResult = (
                    o3d.pipelines.registration.registration_colored_icp(
                        source_down,
                        target_down,
                        radius,
                        current_transformation,
                        o3d.pipelines.registration.TransformationEstimationForColoredICP(),
                        o3d.pipelines.registration.ICPConvergenceCriteria(
                            relative_fitness=1e-4, relative_rmse=1e-4, max_iteration=i
                        ),
                    )
                )
            except Exception as e:
                break
        return result_icp

    async def add_image(self, rgbd_image: o3d.geometry.RGBDImage, extrinsic: np.ndarray):
        if not self.active:
            return
        try:
            extrinsic = np.linalg.inv(extrinsic)
        except LinAlgError:
            logging.error("Image Extrinsic not invertible")
            return
        self.volume.integrate(rgbd_image, self.INTRINSICS, extrinsic)
        self.num_images += 1
        if self.num_images >= self.IMAGE_THRESHOLD:
            await self.rollover()

    async def rollover(self):
        logging.info("reconstructor roll over")
        start = time.time()
        pc = self.volume.extract_point_cloud()
        logging.info(f"rollover time:{time.time() - start}")
        await self.pcd_queue.put(pc)
        self.num_images = 0
        self.volume.reset()

    async def close(self):
        self.active = False
        await self.rollover()
        while (
            self.process_pcd_task_alive.is_set()
            or self.write_to_disk_task_alive.is_set()
            or self.vis_task_alive.is_set()
        ):
            await asyncio.sleep(0.1)
        logging.info("reconstructor closed, all files saved to disk.")

    def _slice_point_cloud(self, pc: o3d.geometry.PointCloud):
        min_box_coords = pc.get_min_bound()
        max_box_coords = pc.get_max_bound()

        rounded_mins = np.floor(min_box_coords / self.CHUNK_SIZE) * self.CHUNK_SIZE
        rounded_mins = rounded_mins.astype(np.int64)
        rounded_maxes = np.ceil(max_box_coords / self.CHUNK_SIZE) * self.CHUNK_SIZE
        rounded_maxes = rounded_maxes.astype(np.int64)

        logging.debug(f"MIN X: {rounded_mins[0]}, MAX X: {rounded_maxes[0]}")

        def process_sliced_point_cloud(
            pc: o3d.geometry.PointCloud, box: o3d.geometry.AxisAlignedBoundingBox, _x, _y, _z
        ):
            cropped_points = pc.crop(box)
            cropped_array = np.asarray(cropped_points.points)
            if not (cropped_array.size and cropped_array.ndim):
                return

            chunk = self.chunks.get((_x, _y, _z), None)
            if chunk is not None:
                with chunk.lock:
                    chunk.pcd = self.combine_pcd(box, cropped_points, chunk.pcd)
                    logging.debug(f"combined in memory {chunk}")
            else:
                pcd_file = self._file_for_pcd((_x, _y, _z))
                try:
                    if not Path(pcd_file).exists():
                        raise FileNotFoundError
                    old_chunk: o3d.geometry.PointCloud = o3d.io.read_point_cloud(pcd_file)
                    if not old_chunk.has_points():
                        raise FileNotFoundError
                    chunk = Chunk(self.combine_pcd(box, cropped_points, old_chunk))
                    logging.debug(f"combined from disk {chunk}")
                except FileNotFoundError:
                    chunk = Chunk(cropped_points)
                except Exception as e:
                    logging.exception(e)
                # Since the file will either be in memory or is unreadable/nonexistent, always try to remove it
                try:
                    os.remove(pcd_file)
                except FileNotFoundError:
                    pass
                self.chunks[(_x, _y, _z)] = chunk

        with ThreadPoolExecutor() as exe:
            for x in range(rounded_mins[0], rounded_maxes[0], self.CHUNK_SIZE):
                for y in range(rounded_mins[1], rounded_maxes[1], self.CHUNK_SIZE):
                    for z in range(rounded_mins[2], rounded_maxes[2], self.CHUNK_SIZE):
                        box = o3d.geometry.AxisAlignedBoundingBox(
                            np.array([[x], [y], [z]]),
                            np.array(
                                [
                                    [x + self.CHUNK_SIZE],
                                    [y + self.CHUNK_SIZE],
                                    [z + self.CHUNK_SIZE],
                                ]
                            ),
                        )
                        exe.submit(process_sliced_point_cloud, pc, box, x, y, z)
        logging.debug("done slicing point cloud")

    async def process_pcd_task(self):
        if self.process_pcd_task_alive.is_set():
            return
        try:
            self.process_pcd_task_alive.set()
            while self.active or not self.pcd_queue.empty():
                try:
                    pcd = await asyncio.wait_for(self.pcd_queue.get(), 1)
                except TimeoutError:
                    continue
                try:
                    await asyncio.to_thread(self._slice_point_cloud, pcd)
                except Exception as e:
                    logging.exception(e)
        finally:
            logging.debug("finish process pcd task")
            self.process_pcd_task_alive.clear()

    def _file_for_pcd(self, index: tuple[int, int, int]) -> str:
        return (self.output / f"chunk_{index[0]}_{index[1]}_{index[2]}.pcd").absolute().as_posix()

    async def write_to_disk_task(self):
        if self.write_to_disk_task_alive.is_set():
            return
        try:
            self.write_to_disk_task_alive.set()
            while self.active or self.process_pcd_task_alive.is_set() or len(self.chunks.keys()):
                if len(self.chunks.keys()) < self.IN_MEMORY_CHUNKS and self.process_pcd_task_alive.is_set():
                    await asyncio.sleep(0.1)
                    continue
                try:
                    key, chunk = next(iter(self.chunks.items()))
                except StopIteration:
                    await asyncio.sleep(0.1)
                    continue

                with chunk.lock:
                    logging.debug(f"writing to disk: {self._file_for_pcd(key)}")
                    o3d.io.write_point_cloud(
                        self._file_for_pcd(key),
                        chunk.pcd,
                        format="pcd",
                        write_ascii=False,
                        compressed=True,
                    )
                    del self.chunks[key]
                await asyncio.sleep(0)
        finally:
            logging.debug("finish write to disk task")
            self.write_to_disk_task_alive.clear()


class CameraPose:
    def __init__(self, meta, mat):
        self.metadata = meta
        self.pose = mat

    def __str__(self):
        return "Metadata : " + " ".join(map(str, self.metadata)) + "\n" + "Pose : " + "\n" + np.array_str(self.pose)


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


async def main():
    output_dir = Path(__file__).parent / "data"
    logging.basicConfig(level=logging.DEBUG)
    lounge_rgbd = o3d.data.LoungeRGBDImages()
    camera_poses = read_trajectory(lounge_rgbd.trajectory_log_path)

    ReconstructionVolume.INTRINSICS = o3d.camera.PinholeCameraIntrinsic(
        o3d.camera.PinholeCameraIntrinsicParameters.PrimeSenseDefault
    )
    volume = ReconstructionVolume(output_dir)
    volume.start_visualization()
    for i in range(len(camera_poses) - 1):
        color = o3d.io.read_image(lounge_rgbd.color_paths[i])
        depth = o3d.io.read_image(lounge_rgbd.depth_paths[i])
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            color, depth, depth_trunc=6.0, convert_rgb_to_intensity=False
        )
        await volume.add_image(rgbd, camera_poses[i].pose)
        await asyncio.sleep(0)
    await volume.close()

    samples = [o3d.io.read_point_cloud(p) for p in output_dir.glob("*.pcd")]
    o3d.visualization.draw_geometries(
        samples,
        zoom=0.3412,
        front=[0.4257, -0.2125, -0.8795],
        lookat=[2.6172, 2.0475, 1.532],
        up=[-0.0694, -0.9768, 0.2024],
    )

    # Convert point clouds into meshes
    combined = o3d.geometry.PointCloud()
    for sample in samples:
        combined += sample
    combined.estimate_normals()
    mesh: o3d.geometry.TriangleMesh
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(combined, depth=9)
    mesh.remove_vertices_by_mask(densities < np.quantile(densities, 0.02))

    # Visualize the generated meshes
    o3d.visualization.draw_geometries(
        [mesh],
        zoom=0.3412,
        front=[0.4257, -0.2125, -0.8795],
        lookat=[2.6172, 2.0475, 1.532],
        up=[-0.0694, -0.9768, 0.2024],
    )

    mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
        combined, o3d.utility.DoubleVector([0.005, 0.01, 0.02, 0.04, 0.08])
    )

    o3d.visualization.draw_geometries(
        [mesh],
        zoom=0.3412,
        front=[0.4257, -0.2125, -0.8795],
        lookat=[2.6172, 2.0475, 1.532],
        up=[-0.0694, -0.9768, 0.2024],
    )


if __name__ == "__main__":
    asyncio.run(main())
