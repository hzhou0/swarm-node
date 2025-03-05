import asyncio
import base64
import logging
import os
import socket
import sys
from fractions import Fraction
from pathlib import Path

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


def webrtc_proxy_media_reader(mime_type: str):
    pipeline_tmpls = {
        "video/h264": [
            "queue",
            "rtpjitterbuffer",
            "rtph264depay",
            "avdec_h264",
        ],
        "video/h265": [
            "queue",
            "rtpjitterbuffer latency=1000",
            "rtph265depay",
            "avdec_h265",
        ],
        "video/vp9": [
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
    mime_type: str,
    width: int,
    height: int,
    fps: int,
    bits_per_sec: int = 1000 * 1000,
    video_format: GstVideo.VideoFormat = GstVideo.VideoFormat.I420,
):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("localhost", 0))
        s.getsockname()
        free_udp_port: int = s.getsockname()[1]

    pipeline_tmpls = {
        "video/h264": [
            f"x264enc speed-preset=ultrafast tune=zerolatency bitrate={bits_per_sec // 1000} key-int-max=1",
            "rtph264pay config-interval=1 aggregate-mode=zero-latency",
            f"udpsink host=localhost port={free_udp_port}",
        ],
        "video/h265": [
            f"x265enc speed-preset=ultrafast tune=zerolatency bitrate={bits_per_sec // 1000} key-int-max=5",
            "rtph265pay config-interval=1 aggregate-mode=zero-latency",
            f"udpsink host=localhost port={free_udp_port}",
        ],
        "video/vp9": [
            f"vp9enc deadline=1 target-bitrate={bits_per_sec}",
            f"udpsink host=localhost port={free_udp_port}",
        ],
    }
    mime_type = mime_type.lower()
    if mime_type not in pipeline_tmpls:
        raise ValueError(f"Unsupported MIME type: {mime_type}")
    return (
        gst_video_sink(
            pipeline_tmpls[mime_type],
            width=width,
            height=height,
            fps=Fraction(fps, 1),
            video_frmt=video_format,
        ),
        free_udp_port,
    )


class IDPool:
    def __init__(self):
        self.ids: set[str] = set()

    def claim(self):
        i = 2
        new_id = self.new_uuid(i)
        while new_id in self.ids:
            i += 1
            new_id = self.new_uuid(i)
        self.ids.add(new_id)
        return new_id

    def release(self, new_id):
        self.ids.discard(new_id)

    @classmethod
    def new_uuid(cls, i: int):
        return base64.urlsafe_b64encode(os.urandom(i)).decode("utf-8").rstrip("=")


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
