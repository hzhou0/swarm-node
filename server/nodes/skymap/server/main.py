import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
import uvloop
from scipy.spatial.transform import Rotation

from gps_cartesian import ENUCoordinateSystem
from integrator import ReconstructionVolume
from swarmnode_skymap_common import (
    cloudflare_turn,
    ZhouDepthEncoder,
    depth_units,
    min_depth_meters,
    max_depth_meters,
)
from webrtc_proxy import (
    webrtc_proxy_client,
    pb,
    webrtc_proxy_media_reader,
)


def create_transformation_matrix(
    x: float, y: float, z: float, pitch: float, roll: float, yaw: float, degrees=True
):
    """
    Creates a 4x4 transformation matrix (extrinsic matrix) from translation and Euler angles.

    Parameters:
        :param x
        :param y
        :param z
            Translation components.
        :param pitch
        :param roll
        :param yaw
            Euler angles representing rotations around the axes.
        :param degrees
            If True, the provided angles are in degrees.

    Returns:
        extrinsic : numpy.ndarray
            4x4 transformation (extrinsic) matrix.
    """

    # Define the Euler angle order.
    # The choice of order ('xyz', 'zyx', etc.) depends on your application's convention.
    # In this example, we assume that the rotation is applied in the 'zyx' order:
    # first yaw (around Z), then pitch (around Y), then roll (around X).
    rotation = Rotation.from_euler("zyx", [yaw, pitch, roll], degrees=degrees)

    # Get the rotation matrix (3x3)
    R_mat = rotation.as_matrix()

    # Create the 4x4 transformation matrix initialized to identity
    extrinsic = np.eye(4)

    # Insert the rotation into the 3x3 upper-left submatrix
    extrinsic[:3, :3] = R_mat

    # Insert the translation vector into the matrix (last column)
    extrinsic[:3, 3] = np.array([x, y, z])

    return extrinsic


async def video_processor(
    mime_type: str, port_future: asyncio.Future[int], frame_queue: asyncio.Queue[np.ndarray]
):
    media_reader = webrtc_proxy_media_reader(mime_type)
    async with media_reader as media:
        port, pipeline = media
        port_future.set_result(port)
        video_src = await pipeline()

        fourcc = cv2.VideoWriter.fourcc(*"XVID")
        out = cv2.VideoWriter(
            "output.avi", fourcc, float(video_src.fps), (video_src.width, video_src.height)
        )

        try:
            while True:
                frame = await asyncio.wait_for(video_src.get(), timeout=5)
                await frame_queue.put(frame)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_YUV420P2RGB)
                cv2.imshow("Video Frame", rgb_frame)
                out.write(rgb_frame)
                cv2.waitKey(1)
        except asyncio.TimeoutError:
            cv2.destroyAllWindows()
        finally:
            out.release()  # Ensure the writer is released when done


async def reconstructor(frame_queue: asyncio.Queue[np.ndarray]):
    decoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)
    volume = ReconstructionVolume(Path(__file__).parent / "data")
    volume.start_visualization()
    coord = ENUCoordinateSystem()
    try:
        i = 0
        while True:
            await asyncio.sleep(0.01)
            frame = await frame_queue.get()
            rgb, d, gps = decoder.video_frame_to_rgbd(frame.copy())
            if gps is None:
                logging.warning("No GPS data")
                continue
            rgb_img = o3d.geometry.Image(np.ascontiguousarray(rgb))
            d_img = o3d.geometry.Image(np.ascontiguousarray(d))
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                rgb_img,
                d_img,
                depth_scale=1 / depth_units,
                depth_trunc=max_depth_meters,
                convert_rgb_to_intensity=False,
            )
            if not coord.has_origin():
                coord.set_enu_origin(gps.latitude, gps.longitude, gps.altitude)
            cartesian = coord.gps2enu(gps.latitude, gps.longitude, gps.altitude)
            x, y, z = cartesian.item(0), cartesian.item(1), cartesian.item(2)
            extrinsic = create_transformation_matrix(y, x, z, gps.pitch, gps.roll, gps.yaw)
            await volume.add_image(rgbd, extrinsic)
            logging.debug(f"integrated image {i}")
            i += 1
    finally:
        await volume.close()


async def main(
    mutation_q: asyncio.Queue[pb.Mutation],
    event_q: asyncio.Queue[pb.Event],
    tg: asyncio.TaskGroup,
):
    rgbd_track = pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265")
    port_fut = asyncio.Future()
    frame_queue = asyncio.Queue(maxsize=100)
    tg.create_task(video_processor(rgbd_track.mime_type, port_fut, frame_queue))
    tg.create_task(reconstructor(frame_queue))
    target_state = pb.State(
        httpServerConfig=pb.HttpServer(
            address="localhost:11510",
            cloudflare_auth=pb.HttpServer.CloudflareTunnel(
                team_domain=os.environ["CLOUDFLARE_DOMAIN"],
                team_aud=os.environ["CLOUDFLARE_AUD"],
            ),
        ),
        wantedTracks=[pb.MediaChannel(track=rgbd_track, localhost_port=await port_fut)],
        config=pb.WebrtcConfig(ice_servers=[await cloudflare_turn()]),
    )
    await mutation_q.put(pb.Mutation(setState=target_state))
    while True:
        event = await event_q.get()
        event_type = event.WhichOneof("event")
        if event_type == "data":
            try:
                obj = json.loads(event.data.payload)
                print(json.dumps(obj, indent=2))
            except json.JSONDecodeError:
                print(event.data.payload)
        elif event_type == "media":
            pass
        elif event_type == "achievedState":
            pass
        elif event_type == "stats":
            if event.stats.type == pb.Stats.ICEType.Relay:
                logging.warning("Connected over TURN relay (higher latency)")
        else:
            logging.error(event_type)


async def setup():
    mutation_q = asyncio.Queue()
    event_q = asyncio.Queue()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(webrtc_proxy_client(mutation_q, event_q))
        tg.create_task(main(mutation_q, event_q, tg))


if __name__ == "__main__":
    logging.basicConfig(
        stream=sys.stdout,
        level=os.environ.get("LOGLEVEL", "INFO").upper(),
        format="%(levelname)s %(filename)s:%(lineno)d %(message)s",
    )
    uvloop.run(setup())
