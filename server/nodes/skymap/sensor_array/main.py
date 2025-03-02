import asyncio
import logging
import os

import numpy as np
import uvloop

from sensors import RGBDStream
from webrtc_proxy import webrtc_proxy_client, pb, webrtc_proxy_media_writer


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
                raise RuntimeError("Stopped receiving frames from depth camera")
            i += 1
            data = self.stream.gather_frame_data()
            if data is None:
                await asyncio.sleep(polling_time)
                continue
            vf = self.stream.depth_encoder.rgbd_to_video_frame(*data)
            await asyncio.sleep(polling_time)
        return vf


async def main(
    mutation_q: asyncio.Queue[pb.Mutation],
    event_q: asyncio.Queue[pb.Event],
    tg: asyncio.TaskGroup,
):
    skymap_server_url = os.environ.get("SKYMAP_SERVER_URL")
    assert skymap_server_url is not None, "Environment variable SKYMAP_SERVER_URL must be set"

    named_track = pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265")

    async def media_write_forever():
        while True:
            track = RGBDVideoStreamTrack()
            media_writer, port = webrtc_proxy_media_writer(
                named_track.mime_type,
                track.stream.width * 2,
                track.stream.height,
                track.stream.framerate,
                bits_per_sec=7000 * 1000,
            )
            target_state = pb.State(
                data=[pb.DataChannel(dest_uuid=skymap_server_url)],
                media=[
                    pb.MediaChannel(
                        dest_uuid=skymap_server_url, track=named_track, localhost_port=port
                    )
                ],
            )
            await mutation_q.put(pb.Mutation(setState=target_state))
            try:
                async with media_writer as pipeline:
                    while True:
                        frame = await track.recv()
                        await pipeline.put(frame)
            except Exception as e:
                logging.exception(e)
            finally:
                track.stream.destroy()

    async def process_events_forever():
        while True:
            event = await event_q.get()
            event_type = event.WhichOneof("event")
            if event_type == "data":
                logging.info(event)
            elif event_type == "achievedState":
                logging.info(event.achievedState)
                if not event.achievedState.media:
                    logging.error("failed")
            else:
                logging.error(event_type)

    tg.create_task(media_write_forever())
    tg.create_task(process_events_forever())


async def setup():
    mutation_q = asyncio.Queue()
    event_q = asyncio.Queue()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(webrtc_proxy_client(mutation_q, event_q))
        tg.create_task(main(mutation_q, event_q, tg))


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO").upper())
    uvloop.run(setup())
