import logging

import numpy as np

from server.nodes.skymap.server.integrator import ReconstructionVolume
import open3d as o3d


voxel_size = ReconstructionVolume.VOXEL_SIZE
max_correspondence_distance_coarse = voxel_size * 15
max_correspondence_distance_fine = voxel_size * 1.5
intrinsics = ReconstructionVolume.INTRINSICS


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


def combine_pcd(
    source: o3d.geometry.PointCloud,
    target: o3d.geometry.PointCloud,
) -> o3d.geometry.PointCloud:
    result_icp = cls.pt2pt_pcd_combine(source, target)

    if result_icp:
        source: o3d.geometry.PointCloud = source.transform(result_icp.transformation)
        combined: o3d.geometry.PointCloud = source + target
    else:
        if np.asarray(target.points).size > np.asarray(source.points).size:
            combined = target
        else:
            combined = source
        logging.debug("failed to combine")
    combine, _ = combined.remove_statistical_outlier(16, 3)
    return combined.voxel_down_sample(voxel_size=cls.VOXEL_SIZE)
