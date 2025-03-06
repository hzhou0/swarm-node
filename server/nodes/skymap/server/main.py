import asyncio
import json
import logging
import os
import sys

import cv2
import uvloop

from swarmnode_skymap_common import cloudflare_turn
from webrtc_proxy import (
    webrtc_proxy_client,
    pb,
    webrtc_proxy_media_reader,
)


async def video_processor(mime_type: str, port_future: asyncio.Future[int]):
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
                frame = await asyncio.wait_for(video_src.get(), timeout=1)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_YUV420P2RGB)
                cv2.imshow("Video Frame", rgb_frame)
                out.write(rgb_frame)
                cv2.waitKey(1)
        except asyncio.TimeoutError:
            cv2.destroyAllWindows()
        finally:
            out.release()  # Ensure the writer is released when done


async def main(
    mutation_q: asyncio.Queue[pb.Mutation],
    event_q: asyncio.Queue[pb.Event],
    tg: asyncio.TaskGroup,
):
    rgbd_track = pb.NamedTrack(track_id="rgbd", stream_id="realsenseD455", mime_type="video/h265")
    port_fut = asyncio.Future()
    tg.create_task(video_processor(rgbd_track.mime_type, port_fut))
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
            pass
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
