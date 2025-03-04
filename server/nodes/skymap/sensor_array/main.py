import asyncio
import logging
import os
import sys

import numpy as np
import uvloop

from sensors import RGBDStream
from webrtc_proxy import webrtc_proxy_client, pb, webrtc_proxy_media_writer


class RBGDVideoStreamError(Exception):
    pass


class RGBDVideoStreamTrack:
    def __init__(self):
        self.stream: RGBDStream = RGBDStream()
        self.wait_for_frames = True

    async def recv(self) -> np.ndarray:
        vf: np.ndarray | None = None
        i = 0
        # poll for frames at 10x the frame rate
        polling_time = (1 / self.stream.framerate) / 10
        limit = (
            5 / polling_time if self.wait_for_frames else 50 / polling_time
        )  # wait 5 seconds for frames to arrive the first time
        while vf is None:
            if i > limit:
                self.stream.destroy()
                raise RBGDVideoStreamError("Stopped receiving frames from depth camera")
            i += 1
            data = self.stream.gather_frame_data()
            if data is None:
                await asyncio.sleep(polling_time)
                continue
            vf = self.stream.depth_encoder.rgbd_to_video_frame(*data)
            await asyncio.sleep(polling_time)
        return vf


target_state: pb.State | None = None


async def media_write_task(
    skymap_server_url: str,
    creds: dict[str, pb.WebrtcConfig.auth],
    named_track: pb.NamedTrack,
    mutation_q: asyncio.Queue[pb.Mutation],
):
    while True:
        track = await asyncio.to_thread(RGBDVideoStreamTrack)
        media_writer, port = webrtc_proxy_media_writer(
            named_track.mime_type,
            track.stream.width * 2,
            track.stream.height,
            track.stream.framerate,
            bits_per_sec=7000 * 1000,
        )
        global target_state
        target_state = pb.State(
            config=pb.WebrtcConfig(
                ice_servers=[pb.WebrtcConfig.IceServer(urls=["stun:stun.l.google.com:19302"])],
                credentials=creds,
            ),
            data=[pb.DataChannel(dest_uuid=skymap_server_url)],
            media=[
                pb.MediaChannel(dest_uuid=skymap_server_url, track=named_track, localhost_port=port)
            ],
        )
        await mutation_q.put(pb.Mutation(setState=target_state))
        try:
            async with media_writer as pipeline:
                while True:
                    frame = await track.recv()
                    await pipeline.put(frame)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            return
        except Exception as e:
            logging.exception(e)
        finally:
            track.stream.destroy()
        await asyncio.sleep(0.1)


async def process_events_task(event_q: asyncio.Queue[pb.Event], media_failed: asyncio.Event):
    while True:
        event = await event_q.get()
        event_type = event.WhichOneof("event")
        if event_type == "data":
            pass
        elif event_type == "achievedState":
            if not event.achievedState.media:
                media_failed.set()
            else:
                media_failed.clear()
        else:
            logging.error(event_type)


async def media_retry_task(mutation_q: asyncio.Queue[pb.Mutation], media_failed: asyncio.Event):
    while True:
        await media_failed.wait()
        if target_state is not None:
            await mutation_q.put(pb.Mutation(setState=target_state))
        await asyncio.sleep(5)


async def setup():
    mutation_q = asyncio.Queue()
    event_q = asyncio.Queue()
    named_track = pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265")
    skymap_server_url = os.environ.get("SKYMAP_SERVER_URL")
    assert skymap_server_url is not None, "Environment variable SKYMAP_SERVER_URL must be set"
    skymap_server_client_id = os.environ.get("SKYMAP_SERVER_CLIENT_ID")
    assert (
        skymap_server_client_id is not None
    ), "Environment variable SKYMAP_SERVER_CLIENT_ID must be set"
    skymap_server_client_secret = os.environ.get("SKYMAP_SERVER_CLIENT_SECRET")
    assert (
        skymap_server_client_secret is not None
    ), "Environment variable SKYMAP_SERVER_CLIENT_SECRET must be set"
    creds = {
        skymap_server_url: pb.WebrtcConfig.auth(
            cloudflare_auth=pb.WebrtcConfig.auth.CloudflareZeroTrust(
                client_id=skymap_server_client_id, client_secret=skymap_server_client_secret
            )
        )
    }
    async with asyncio.TaskGroup() as tg:
        tg.create_task(webrtc_proxy_client(mutation_q, event_q))
        tg.create_task(media_write_task(skymap_server_url, creds, named_track, mutation_q))
        media_failed = asyncio.Event()
        tg.create_task(process_events_task(event_q, media_failed))
        tg.create_task(media_retry_task(mutation_q, media_failed))


if __name__ == "__main__":
    logging.basicConfig(
        stream=sys.stdout,
        level=os.environ.get("LOGLEVEL", "INFO").upper(),
        format="%(levelname)s %(filename)s:%(lineno)d %(message)s",
    )
    uvloop.run(setup())
