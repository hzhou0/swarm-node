import asyncio
import logging
import os
from pathlib import Path

import cv2
import uvloop

from webrtc_proxy import (
    webrtc_proxy_client,
    pb,
    webrtc_proxy_media_reader,
)


async def video_processor(media_chan: pb.MediaChannel, server_dir: str):
    read_socket = Path(server_dir) / media_chan.socket_name
    media_reader = webrtc_proxy_media_reader(str(read_socket), media_chan.track.mime_type)
    async with media_reader as pipeline:
        while True:
            frame = await pipeline.get()
            # Display the frame
            cv2.imshow("Video Frame", cv2.cvtColor(frame, cv2.COLOR_YUV420P2RGB))
            cv2.waitKey(1)


async def main(
    mutation_q: asyncio.Queue[pb.Mutation],
    event_q: asyncio.Queue[pb.Event],
    tg: asyncio.TaskGroup,
):
    media_task: asyncio.Task | None = None
    event = await event_q.get()
    if event.WhichOneof("event") == "mediaSocketDirs":
        client_dir = event.mediaSocketDirs.clientDir
        server_dir = event.mediaSocketDirs.serverDir
    else:
        raise Exception("Expected first event to be mediaSocketDirs")
    target_state = pb.State(
        httpServerConfig=pb.HttpServer(address=":8080"),
        wantedTracks=[
            pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h264"),
            pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265"),
            pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/vp9"),
        ],
    )
    await mutation_q.put(pb.Mutation(setState=target_state))
    while True:
        event = await event_q.get()
        event_type = event.WhichOneof("event")
        if event_type == "data":
            print(event)
        elif event_type == "media":
            if media_task is not None:
                media_task.cancel()
            media_task = tg.create_task(video_processor(event.media, server_dir))
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
