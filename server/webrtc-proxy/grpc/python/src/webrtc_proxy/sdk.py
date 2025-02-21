import asyncio
import logging
import os
import sys
from fractions import Fraction
from pathlib import Path
from typing import Literal

import gi
import grpc

import webrtc_proxy.networking_pb2 as pb
from webrtc_proxy.async_gst import gst_video_source, gst_video_sink

# Path manipulation for this one import: grpc generated code uses relative file imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from webrtc_proxy.networking_pb2_grpc import WebrtcProxyStub

sys.path.pop(0)
# End of path manipulation

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo

Gst.init(None)


def webrtc_proxy_media_reader(shm_path: str, mime_type: str):
    pipeline_tmpls = {
        "video/h264": [
            f"shmsrc socket-path={shm_path} is-live=true",
            "queue",
            "h264parse",
            "avdec_h264",
        ],
        "video/h265": [
            f"shmsrc socket-path={shm_path} is-live=true",
            "queue",
            "h265parse",
            "avdec_h265",
        ],
        "video/vp9": [
            f"shmsrc socket-path={shm_path} is-live=true do-timestamp=true",
            "application/x-rtp,encoding-name=VP9",
            "rtpvp9depay",
            "queue",
            "vp9parse",
            "vp9dec",
        ],
    }
    mime_type = mime_type.lower()
    if mime_type not in pipeline_tmpls:
        raise ValueError(f"Unsupported MIME type: {mime_type}")
    return gst_video_source(pipeline_tmpls[mime_type])


def webrtc_proxy_media_writer(
    shm_path: str,
    mime_type: str,
    width: int,
    height: int,
    fps: int,
    video_format: GstVideo.VideoFormat = GstVideo.VideoFormat.I420,
):
    pipeline_tmpls = {
        "video/h264": [
            "x264enc speed-preset=ultrafast tune=zerolatency bitrate=5000 key-int-max=1",
            f"shmsink wait-for-connection=true socket-path={shm_path}",
        ],
        "video/h265": [
            "x265enc speed-preset=ultrafast tune=zerolatency bitrate=7000 key-int-max=1",
            f"shmsink wait-for-connection=true socket-path={shm_path}",
        ],
        "video/vp9": [
            "vp9enc deadline=1",
            f"shmsink wait-for-connection=true socket-path={shm_path}",
        ],
    }
    mime_type = mime_type.lower()
    if mime_type not in pipeline_tmpls:
        raise ValueError(f"Unsupported MIME type: {mime_type}")
    return gst_video_sink(
        pipeline_tmpls[mime_type],
        width=width,
        height=height,
        fps=Fraction(fps, 1),
        video_frmt=video_format,
    )


def incoming_shm_path(channel: pb.MediaChannel, server_media_dir: str):
    # `pb.MediaChannel` is used here to process media channel-related metadata.
    return media_shm_path(channel.track, server_media_dir, channel.src_uuid)


def media_shm_path(
    named_track: pb.NamedTrack,
    media_socket_dir: str,
    src_uuid: str | Literal["outbound"] = "outbound",
):
    track_file = f"gst|{src_uuid}|{named_track.stream_id}|{named_track.track_id}|{named_track.mime_type.lower()}".replace(
        "/", "_"
    )
    return Path(media_socket_dir) / track_file


def webrtc_proxy_client(
    mutation_q: asyncio.Queue[pb.Mutation],
    event_q: asyncio.Queue[pb.Event],
):
    """
    Streams Mutations from mutation_q to the gRPC server
    and streams Events from the server into event_q.

    Args:
        mutation_q: Queue of outgoing pb.Mutation objects to send to the server.
        event_q: Queue of incoming pb.Event objects to receive from the server.
    """
    proxy_dir_env = os.getenv("PROXY_DIRECTORY")
    assert proxy_dir_env is not None, "PROXY_DIRECTORY environment variable not set"
    assert os.path.exists(
        proxy_dir_env
    ), f"PROXY_DIRECTORY environment variable points to nonexistent directory: {proxy_dir_env}"
    socket_path = Path(proxy_dir_env) / "swarmnode.sock"
    assert socket_path.is_socket(), f"Malformed socket: {socket_path}"
    # https://github.com/grpc/grpc/blob/master/doc/naming.md gRPC name resolution
    conn_str = f"unix://{socket_path.resolve()}"

    async def mutation_generator(queue: asyncio.Queue[pb.Mutation]):
        while True:
            mutation = await queue.get()
            logging.debug(f"Mutation: {mutation}")
            yield mutation

    async def client_task():
        async with grpc.aio.secure_channel(
            conn_str, grpc.local_channel_credentials(grpc.LocalConnectionType.UDS)
        ) as channel:
            stub = WebrtcProxyStub(channel)
            try:
                # Bidirectional streaming
                async for event in stub.Connect(mutation_generator(mutation_q)):
                    logging.debug(f"Event: {event}")
                    await event_q.put(event)  # Add event to the event queue
            except Exception as e:
                logging.exception(e)
            finally:
                logging.debug("Grpc client stream ended.")

    return client_task()
