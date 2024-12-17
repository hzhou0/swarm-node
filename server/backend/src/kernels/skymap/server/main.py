import asyncio
import logging
import multiprocessing
import time
from multiprocessing import connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Lock

import av
import cv2
import uvloop
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCDataChannel,
    RTCConfiguration,
    RTCIceServer, MediaStreamTrack, VideoStreamTrack,
)
from av.video.frame import VideoFrame
from matplotlib import pyplot as plt

from ipc import write_state
from kernels.utils import loop_forever
from models import (
    WebrtcOffer,
    KernelState,
)
from util import configure_root_logger, ice_servers

_state = KernelState()
_pc: RTCPeerConnection = RTCPeerConnection()
_datachannel: RTCDataChannel | None = None
_sensor_video: VideoStreamTrack | None = None

_state_mem: SharedMemory | None = None
_state_lock: Lock | None = None


def _commit_state():
    global _state_mem, _state_lock, _state
    _state_mem = write_state(_state_mem, _state_lock, _state)


@loop_forever(2.0)
async def keep_alive():
    if _datachannel is not None:
        _datachannel.send("")


async def on_connectionstatechange(pc: RTCPeerConnection):
    logging.info(f"Connection state is {pc.connectionState}")
    if pc.connectionState == "failed" or pc.connectionState == "closed":
        await pc.close()
        global _datachannel, _sensor_video
        _datachannel = None
        _sensor_video = None


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


def on_track(track: MediaStreamTrack):
    if track.kind != 'video':
        logging.info(f"Ignoring track, kind is {track.kind}")
        return
    logging.info(f"Using video track {track}")
    global _sensor_video
    _sensor_video = track


async def handle_offer(offer: WebrtcOffer):
    import aioice.stun

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

    pc.add_listener("track", lambda track: on_track(track))
    pc.add_listener("connectionstatechange", lambda: on_connectionstatechange(pc))
    pc.add_listener("datachannel", lambda channel: on_datachannel(channel))

    logging.info(offer.sdp)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer.sdp, type=offer.type))
    start = time.time()
    await pc.setLocalDescription(await pc.createAnswer())
    logging.info(f"ICE Candidates gathered in {time.time() - start}")
    logging.info(pc.localDescription.sdp)
    _state.webrtc_offer = WebrtcOffer(
        sdp=pc.localDescription.sdp, type=pc.localDescription.type, tracks=offer.tracks
    )
    _commit_state()

    global _pc
    await _pc.close()
    _pc = pc


@loop_forever(0.01)
async def process_frame():
    global _sensor_video
    if _sensor_video is None:
        return
    try:
        frame: VideoFrame=await _sensor_video.recv()
        plt.imshow(frame.to_ndarray(format="rgb24"))
        plt.show()
    except Exception as e:
        cv2.destroyAllWindows()
        logging.error(e)
        _sensor_video = None


@loop_forever(0.01)
async def process_mutations(pipe: connection.Connection):
    while pipe.poll():
        mutation: WebrtcOffer = pipe.recv()
        match mutation:
            case WebrtcOffer():
                await handle_offer(mutation)


def main(
        state_mem: SharedMemory,
        state_lock: Lock,
        pipe: connection.Connection,
):
    multiprocessing.freeze_support()
    multiprocessing.spawn.freeze_support()
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    global _state_mem, _state_lock
    _state_mem, _state_lock = state_mem, state_lock
    _commit_state()
    configure_root_logger()
    av.logging.set_level(av.logging.PANIC)

    loop = asyncio.get_event_loop()
    # Specify tasks in a collection to avoid garbage collection
    _ = (
        loop.create_task(process_frame()),
        loop.create_task(process_mutations(pipe)),
        loop.create_task(keep_alive()),
    )
    try:
        loop.run_forever()
    finally:
        for task in asyncio.all_tasks():
            task.cancel()
        loop.close()
