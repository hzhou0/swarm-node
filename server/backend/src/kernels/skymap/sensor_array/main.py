import asyncio
import atexit
import fractions
import logging
import os
import time

import av
import msgspec.json
import uvloop
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpSender,
    RTCDataChannel,
    RTCConfiguration,
    RTCIceServer,
    VideoStreamTrack,
)
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame

from client import SwarmNodeClient
from kernels.skymap.sensor_array.sensors import RGBDStream
from kernels.utils import loop_forever
from models import (
    WebrtcOffer,
    Tracks,
)
from util import configure_root_logger, ice_servers

_pc: RTCPeerConnection = RTCPeerConnection()
_datachannel: RTCDataChannel | None = None
sn_client = SwarmNodeClient(
    os.environ["SKYMAP_SERV_ROOT_URL"],
    msgspec.json.decode(os.environ["SKYMAP_SERV_AUTH_HEADERS"], type=dict[str, str]),
)


@loop_forever(2.0)
async def keep_alive():
    if _datachannel is not None:
        _datachannel.send("")


async def on_connectionstatechange(pc: RTCPeerConnection):
    logging.info(f"Connection state is {pc.connectionState}")
    if pc.connectionState == "failed" or pc.connectionState == "closed":
        await pc.close()
        global _datachannel
        _datachannel = None


def on_datachannel(channel: RTCDataChannel):
    def on_message(message: str):
        logging.info(f"Received message {message}")
        try:
            logging.info(
                f"Latency: {int(time.time() - float(message.split(';')[-1])) * 1000}ms"
            )
        except:
            pass

    channel.on("message", on_message)
    global _datachannel
    _datachannel = channel


class RGBDVideoStreamTrack(VideoStreamTrack):
    """
    RGBD Depth Video Stream Track
    """

    def __init__(self, framerate: int = 5):
        super().__init__()
        self.stream: RGBDStream | None = RGBDStream(framerate=framerate)
        self.wait_for_frames = True

    async def recv(self):
        if self.readyState != "live" or self.stream is None:
            raise MediaStreamError
        video_clock_rate = 90000
        time_base = fractions.Fraction(1, video_clock_rate)
        if hasattr(self, "_timestamp"):
            self._timestamp += int(1 / self.stream.framerate * video_clock_rate)
        else:
            self._start = time.time()
            self._timestamp = 0

        frame = None
        i = 0
        # poll for frames at 10x the frame rate
        polling_time = (1 / self.stream.framerate) / 10
        limit = 5 / polling_time if self.wait_for_frames else 50  # wait 5 seconds for frames to arrive the first time
        while frame is None:
            if i > limit:
                logging.error(f"Stopped receiving frames from depth camera")
                self.stream.destroy()
                self.stream = None
                raise MediaStreamError
            i += 1
            frame = self.stream.get_frame()
            await asyncio.sleep(polling_time)
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = self._timestamp
        video_frame.time_base = time_base
        return video_frame


_rgbd_stream: RGBDVideoStreamTrack | None = None

@atexit.register
def cleanup():
    global _rgbd_stream
    if _rgbd_stream is not None:
        _rgbd_stream.stream.destroy()

@loop_forever(1.0)
async def maintain_peer_connection() -> None:
    global _pc, _rgbd_stream
    rgbd_failed = _rgbd_stream is None or _rgbd_stream.stream is None
    if _pc.connectionState in {"connecting", "connected"} and not rgbd_failed:
        return
    if _rgbd_stream is not None:
        try:
            _rgbd_stream.stop()
            _rgbd_stream.stream.destroy()
        except:
            pass
    _rgbd_stream = RGBDVideoStreamTrack()

    # aioice attempts stun lookup on private network ports: these queries will never resolve
    # These attempts will timeout after 5 seconds, making connection take 5+ seconds
    # Modifying retry globals here to make it fail faster and retry more aggressively
    # Retries follow an exponential fallback: 1,2,4,8 * RETRY_RTO
    import aioice.stun
    aioice.stun.RETRY_MAX = 2
    aioice.stun.RETRY_RTO = 0.1

    import aiortc.codecs.h264 as h264
    h264.MAX_FRAME_RATE=_rgbd_stream.stream.framerate

    pc = RTCPeerConnection(
        RTCConfiguration(
            [
                RTCIceServer(urls=s.urls, username=s.username, credential=s.credential)
                for s in ice_servers
            ]
        )
    )

    pc.add_listener("connectionstatechange", lambda: on_connectionstatechange(pc))
    pc.add_listener("datachannel", lambda channel: on_datachannel(channel))
    direction = "sendonly"
    trans = pc.addTransceiver(_rgbd_stream, direction)
    trans.setCodecPreferences(
        [
            c
            for c in RTCRtpSender.getCapabilities("video").codecs
            if c.mimeType == "video/H264"
        ]
    )

    await pc.setLocalDescription(await pc.createOffer())
    offer = WebrtcOffer(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        tracks=Tracks(client_video=True),
    )

    new_offer = await sn_client.webrtc_offer(offer)
    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=new_offer.sdp, type=new_offer.type)
    )
    _pc = pc


def main():
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    configure_root_logger()
    av.logging.set_level(av.logging.PANIC)

    loop = asyncio.get_event_loop()
    _ = (loop.create_task(keep_alive()),
         loop.create_task(maintain_peer_connection())
         )
    try:
        loop.run_forever()
    finally:
        for task in asyncio.all_tasks():
            task.cancel()
        loop.close()
