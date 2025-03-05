import asyncio
import logging
import os
import sys

import httpx
import uvloop

from sensors import RGBDStream, FrameError, GPSError
from swarmnode_skymap_common import cloudflare_turn
from webrtc_proxy import webrtc_proxy_client, pb, webrtc_proxy_media_writer

target_state: pb.State | None = None


async def media_write_task(
    stream: RGBDStream,
    skymap_server_url: str,
    ice_servers: list[pb.WebrtcConfig.IceServer],
    creds: dict[str, pb.WebrtcConfig.auth],
    named_track: pb.NamedTrack,
    mutation_q: asyncio.Queue[pb.Mutation],
):
    while True:
        media_writer, port = webrtc_proxy_media_writer(
            named_track.mime_type,
            stream.width * 2,
            stream.height,
            stream.framerate,
            bits_per_sec=7000 * 1000,
        )
        global target_state
        target_state = pb.State(
            config=pb.WebrtcConfig(ice_servers=ice_servers, credentials=creds),
            data=[pb.DataChannel(dest_uuid=skymap_server_url)],
            media=[
                pb.MediaChannel(dest_uuid=skymap_server_url, track=named_track, localhost_port=port)
            ],
        )
        await mutation_q.put(pb.Mutation(setState=target_state))
        try:
            async with media_writer as pipeline:
                while True:
                    try:
                        data = await stream.gather_frame_data()
                    except FrameError:
                        pass
                    except GPSError:
                        pass
                    frame = stream.depth_encoder.rgbd_to_video_frame(*data)
                    await pipeline.put(frame)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            return
        except Exception as e:
            logging.exception(e)
        finally:
            stream.destroy()
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
        elif event_type == "stats":
            pass
        else:
            logging.error(event_type)


async def media_retry_task(mutation_q: asyncio.Queue[pb.Mutation], media_failed: asyncio.Event):
    while True:
        await media_failed.wait()
        if target_state is not None:
            await mutation_q.put(pb.Mutation(setState=target_state))
        await asyncio.sleep(5)


async def write_rtcm_task(
    rgbd_track: RGBDVideoStreamTrack, ntrip_username: str, ntrip_password: str
):
    auth = httpx.BasicAuth(ntrip_username, ntrip_password)
    client = httpx.AsyncClient()
    while True:
        try:
            async with client.stream(
                "GET",
                url="http://rtk2go.com:2101/AVRIL",
                auth=auth,
                headers={
                    "Ntrip-Version": "Ntrip/2.0",
                    "User-Agent": "NTRIP pygnssutils/1.1.9",
                    "Accept": "*/*",
                    "Connection": "close",
                },
            ) as response:
                async for chunk in response.aiter_bytes():
                    logging.debug(f"RTCM Data Chunk: {chunk}")
                    rgbd_track.stream.write_rtcm(chunk)
        except Exception as e:
            logging.exception(e)
        await asyncio.sleep(1)


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
    ntrip_username = os.environ.get("NTRIP_USERNAME")
    assert ntrip_username is not None, "Environment variable NTRIP_USERNAME must be set"
    ntrip_password = os.environ.get("NTRIP_PASSWORD")
    assert ntrip_password is not None, "Environment variable NTRIP_PASSWORD must be set"

    rgbd_stream = RGBDStream()

    ice_server = await cloudflare_turn()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(write_rtcm_task(rgbd_stream, ntrip_username, ntrip_password))
        tg.create_task(webrtc_proxy_client(mutation_q, event_q))
        tg.create_task(
            media_write_task(
                rgbd_stream, skymap_server_url, [ice_server], creds, named_track, mutation_q
            )
        )
        media_failed = asyncio.Event()
        tg.create_task(process_events_task(event_q, media_failed))
        tg.create_task(media_retry_task(mutation_q, media_failed))


if __name__ == "__main__":
    logging.basicConfig(
        stream=sys.stdout,
        level=os.environ.get("LOGLEVEL", "INFO").upper(),
        format="%(levelname)s %(filename)s:%(lineno)d %(message)s",
    )
    uvloop.run(write_rtcm_task("h285zhou@uwaterloo.ca", "none"))
    # uvloop.run(setup())
