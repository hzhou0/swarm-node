import asyncio
import logging
import os
import time

import av
import cv2
import msgspec.json
import numpy as np
import uvloop
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpSender,
    RTCDataChannel,
    RTCConfiguration,
    RTCIceServer,
    MediaStreamTrack,
    VideoStreamTrack,
)
from av import VideoFrame

from client import SwarmNodeClient
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


class FlagVideoStreamTrack(VideoStreamTrack):
    """
    A video track that returns an animated flag.
    """

    def __init__(self):
        super().__init__()  # remember this!
        self.counter = 0
        height, width = 480, 640

        # generate flag
        data_bgr = np.hstack(
            [
                self._create_rectangle(
                    width=213, height=480, color=(255, 0, 0)
                ),  # blue
                self._create_rectangle(
                    width=214, height=480, color=(255, 255, 255)
                ),  # white
                self._create_rectangle(width=213, height=480, color=(0, 0, 255)),  # red
            ]
        )

        # shrink and center it
        M = np.float32([[0.5, 0, width / 4], [0, 0.5, height / 4]])
        data_bgr = cv2.warpAffine(data_bgr, M, (width, height))

        # compute animation
        omega = 2 * np.pi / height
        id_x = np.tile(np.array(range(width), dtype=np.float32), (height, 1))
        id_y = np.tile(
            np.array(range(height), dtype=np.float32), (width, 1)
        ).transpose()

        self.frames = []
        for k in range(30):
            phase = 2 * k * np.pi / 30
            map_x = id_x + 10 * np.cos(omega * id_x + phase)
            map_y = id_y + 10 * np.sin(omega * id_x + phase)
            self.frames.append(
                VideoFrame.from_ndarray(
                    cv2.remap(data_bgr, map_x, map_y, cv2.INTER_LINEAR), format="bgr24"
                )
            )

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        frame = self.frames[self.counter % 30]
        frame.pts = pts
        frame.time_base = time_base
        self.counter += 1
        return frame

    @staticmethod
    def _create_rectangle(width, height, color):
        data_bgr = np.zeros((height, width, 3), np.uint8)
        data_bgr[:, :] = color
        return data_bgr


@loop_forever(1.0)
async def establish_pc(videoStream: MediaStreamTrack) -> None:
    import aioice.stun
    global _pc
    if _pc.connectionState in {"connecting", "connected"}:
        return
    # aioice attempts stun lookup on private network ports: these queries will never resolve
    # These attempts will timeout after 5 seconds, making connection take 5+ seconds
    # Modifying retry globals here to make it fail faster and retry more aggressively
    # Retries follow an exponential fallback: 1,2,4,8 * RETRY_RTO
    aioice.stun.RETRY_MAX = 2
    aioice.stun.RETRY_RTO = 0.1
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
    trans = pc.addTransceiver(videoStream, direction)
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
         loop.create_task(establish_pc(FlagVideoStreamTrack()))
         )
    try:
        loop.run_forever()
    finally:
        for task in asyncio.all_tasks():
            task.cancel()
        loop.close()
