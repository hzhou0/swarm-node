import asyncio
import logging
import os

import numpy as np
import uvloop

from webrtc_proxy import webrtc_proxy_client, pb
from .sensors import RGBDStream


class RGBDVideoStreamTrack:
    """
    RGBD Depth Video Stream Track
    """

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
    event = await event_q.get()
    if event.WhichOneof("event") == "mediaSocketDirs":
        client_dir = event.mediaSocketDirs.clientDir
        server_dir = event.mediaSocketDirs.serverDir
    else:
        raise Exception("Expected first event to be mediaSocketDirs")
    target_state = pb.State(
        data=[pb.DataChannel(dest_uuid=skymap_server_url)],
        media=[
            pb.MediaChannel(
                dest_uuid=skymap_server_url,
                track=pb.NamedTrack(
                    track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265"
                ),
            )
        ],
        wantedTracks=[],
    )
    await mutation_q.put(pb.Mutation(setState=target_state))
    while True:
        event = await event_q.get()
        event_type = event.WhichOneof("event")
        if event_type == "data":
            print(event)
        elif event_type == "achievedState":
            print(event.achievedState)
        else:
            logging.error(event_type)


async def setup():
    mutation_q = asyncio.Queue()
    event_q = asyncio.Queue()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(webrtc_proxy_client(mutation_q, event_q))
        tg.create_task(main(mutation_q, event_q, tg))


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO").upper())
    uvloop.run(setup())
