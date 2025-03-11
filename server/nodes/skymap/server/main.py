import asyncio
import datetime
import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
import uvloop

from gps_cartesian import ENUCoordinateSystem, create_transformation_matrix
from integrator import ReconstructionVolume
from swarmnode_skymap_common import (
    cloudflare_turn,
    ZhouDepthEncoder,
    depth_units,
    min_depth_meters,
    max_depth_meters,
)
from tui import ScanStateStatus, ScanState, SkymapScanTui
from webrtc_proxy import (
    webrtc_proxy_client,
    pb,
    webrtc_proxy_media_reader,
)


async def video_processor(
    mime_type: str,
    port_future: asyncio.Future[int],
    frame_queue: asyncio.Queue[np.ndarray],
    scan_state: ScanState,
):
    frame_out_dir = scan_state.directory / "frames"
    frame_out_dir.mkdir(parents=True, exist_ok=True)
    frames_arr: list[np.ndarray] = []

    media_reader = webrtc_proxy_media_reader(mime_type)
    i = 0

    vis = o3d.visualization.Visualizer()

    trans = o3d.geometry.PointCloud.get_rotation_matrix_from_xzy([180, 0, 0])
    pcd: o3d.geometry.PointCloud | None = None
    decoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)

    async with media_reader as media:
        port, pipeline = media
        port_future.set_result(port)
        video_src = await pipeline()
        try:
            while True:
                try:
                    while True:
                        frame = await asyncio.wait_for(video_src.get(), timeout=10)
                        frame = frame.copy()
                        scan_state.last_client_frame_epoch_time = time.time()
                        scan_state.frames_received += 1
                        scan_state.status = ScanStateStatus.receiving
                        # await frame_queue.put(frame)
                        rgb, d, gps = decoder.video_frame_to_rgbd(frame)
                        rgb_img = o3d.geometry.Image(np.ascontiguousarray(rgb))
                        d_img = o3d.geometry.Image(np.ascontiguousarray(d))
                        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                            rgb_img,
                            d_img,
                            depth_scale=1 / depth_units,
                            depth_trunc=max_depth_meters,
                            convert_rgb_to_intensity=False,
                        )

                        new_pcd: o3d.geometry.PointCloud = o3d.geometry.PointCloud.create_from_rgbd_image(
                            rgbd, ReconstructionVolume.INTRINSICS
                        )
                        new_pcd.rotate(trans)
                        if pcd is None:
                            vis.create_window()
                            vis_ctrl: o3d.visualization.ViewControl = vis.get_view_control()
                            vis_ctrl.set_zoom(1.5)
                            pcd = new_pcd
                            vis.add_geometry(pcd)
                        else:
                            pcd.points = new_pcd.points
                            pcd.colors = new_pcd.colors
                            vis.update_geometry(pcd)
                            vis_ctrl.set_lookat(pcd.get_center())
                        vis.poll_events()
                        vis.update_renderer()
                        # frames_arr.append(frame)
                        # if len(frames_arr) >= 30:
                        #     await asyncio.to_thread(np.savez_compressed, frame_out_dir / f"{i}", *frames_arr)
                        #     i += 1
                        #     frames_arr = []
                        await asyncio.sleep(0.01)
                except asyncio.TimeoutError:
                    scan_state.status = ScanStateStatus.lost
        finally:
            if frames_arr:
                np.savez_compressed(frame_out_dir / f"{i}", *frames_arr)
            vis.destroy_window()


async def reconstructor(frame_queue: asyncio.Queue[np.ndarray], scan_state: ScanState):
    decoder = ZhouDepthEncoder(depth_units, min_depth_meters, max_depth_meters)
    volume = ReconstructionVolume(scan_state.directory / "data")
    # volume.start_visualization()

    coord = ENUCoordinateSystem()
    try:
        scan_state.images_integrated = 0
        while True:
            await asyncio.sleep(0.01)
            frame = await frame_queue.get()
            rgb, d, gps = decoder.video_frame_to_rgbd(frame.copy())
            if gps is None:
                scan_state.frames_corrupted += 1
                continue
            logging.info(gps)
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
                scan_state.gps_origin = (gps.latitude, gps.longitude, gps.altitude)
                coord.set_enu_origin(*scan_state.gps_origin)
            cartesian = coord.gps2enu(gps.latitude, gps.longitude, gps.altitude)
            x, y, z = cartesian.item(0), cartesian.item(1), cartesian.item(2)
            extrinsic = create_transformation_matrix(y, x, z, gps.yaw, gps.pitch, gps.roll)
            await volume.add_image(rgbd, extrinsic)
            scan_state.images_integrated += 1
    finally:
        await volume.close()


async def main(
    mutation_q: asyncio.Queue[pb.Mutation],
    event_q: asyncio.Queue[pb.Event],
    tg: asyncio.TaskGroup,
    scan_state: ScanState,
):
    rgbd_track = pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265")
    port_fut = asyncio.Future()
    frame_queue = asyncio.Queue(maxsize=100)
    tg.create_task(video_processor(rgbd_track.mime_type, port_fut, frame_queue, scan_state))
    tg.create_task(reconstructor(frame_queue, scan_state))
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
                if "position_type" in obj:
                    scan_state.client_gps_fix = obj["position_type"]
                if "sat_num" in obj:
                    scan_state.client_sat_num = obj["sat_num"]
                if "error" in obj:
                    logging.warning(f"sensor array encountered error: {obj['error']}")
            except json.JSONDecodeError:
                logging.warning("Unparsable sensor array msg:" + event.data.payload.decode("utf-8"))
        elif event_type == "media":
            if event.media.close:
                scan_state.status = ScanStateStatus.lost
            else:
                scan_state.status = ScanStateStatus.connected
        elif event_type == "achievedState":
            pass
        elif event_type == "stats":
            scan_state.webrtc_turn = event.stats.type == event.stats.ICEType.Relay
            scan_state.webrtc_rtt = event.stats.current_rtt
        else:
            logging.error(event_type)


def configure_root_logger(log_dir: Path):
    rl = logging.getLogger()
    rl.setLevel(os.environ.get("LOGLEVEL", "INFO").upper())
    rl.handlers.clear()
    log_path = log_dir / "skymap.log"
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
    )
    file_fmt = "%(levelname)s %(filename)s:%(lineno)d %(message)s"
    file_handler.setFormatter(logging.Formatter(file_fmt))
    rl.addHandler(file_handler)
    return log_path


async def scan_instance(scan_state: ScanState):
    try:
        scan_state.id = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        scan_state.directory = Path.home() / "skymap-server" / scan_state.id
        scan_state.directory.mkdir(parents=True, exist_ok=True)
        log_dir = scan_state.directory / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        scan_state.log_path = configure_root_logger(log_dir)
        mutation_q = asyncio.Queue()
        event_q = asyncio.Queue()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(webrtc_proxy_client(mutation_q, event_q))
            tg.create_task(main(mutation_q, event_q, tg, scan_state))
    except asyncio.CancelledError:
        scan_state.status = ScanStateStatus.done
    except Exception as e:
        logging.exception(e)
        scan_state.status = ScanStateStatus.error
    finally:
        scan_state.end_time = time.time()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    uvloop.run(SkymapScanTui(scan_instance=scan_instance).run_async())
