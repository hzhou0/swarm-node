import av
import asyncio
import logging
import time
from functools import partial
from multiprocessing import connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Lock
from typing import Literal, Callable

import pulsectl_asyncio
import pyudev
import uvloop
import v4l2py
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpSender,
    RTCDataChannel,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.contrib.media import MediaPlayer
from pyudev import Monitor

from ipc import write_state
from models import (
    AudioDevice,
    VideoDevice,
    AudioDeviceOptions,
    WebrtcOffer,
    MachineState,
    MachineHTTPMutation,
)
from util import configure_root_logger, ice_servers

_state = MachineState()
_pc: RTCPeerConnection = RTCPeerConnection()
_datachannel: RTCDataChannel | None = None

_state_mem: SharedMemory | None = None
_state_lock: Lock | None = None


def _commit_state():
    global _state_mem, _state_lock, _state
    _state_mem = write_state(_state_mem, _state_lock, _state)


def loop_forever(interval: float) -> Callable:
    def decorator(func: Callable) -> Callable:
        async def inner(*args, **kwargs):
            while True:
                try:
                    await func(*args, **kwargs)
                except Exception as e:
                    logging.exception(e)
                await asyncio.sleep(interval)

        return inner

    return decorator


_refresh_devices_first_call = True


@loop_forever(2.0)
async def refresh_devices(video_mon: Monitor, audio_mon: Monitor):
    global _refresh_devices_first_call

    if _refresh_devices_first_call or list(iter(partial(video_mon.poll, 0), None)):
        logging.info("Hardware changes, refreshing video devices")
        v = {}
        for d in v4l2py.iter_video_capture_devices():
            d.open()
            device = VideoDevice.from_v4l2(d)
            v[device.name] = device
            d.close()
        _state.devices.video = v
        _commit_state()

    if _refresh_devices_first_call or list(iter(partial(audio_mon.poll, 0), None)):
        logging.info("Hardware changes, refreshing audio devices")
        async with pulsectl_asyncio.PulseAsync("enumerate_devices") as pa:
            default_sink = (await pa.server_info()).default_sink_name
            default_source = (await pa.server_info()).default_source_name
            sinks, sources = await asyncio.gather(pa.sink_list(), pa.source_list())
            a = [AudioDevice.from_pa(d, default_sink, "sink") for d in sinks]
            a += [AudioDevice.from_pa(d, default_source, "source") for d in sources]
            a = {audio_device.name: audio_device for audio_device in a}
        _state.devices.audio = a
        _commit_state()

    _refresh_devices_first_call = False


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


async def handle_offer(offer: WebrtcOffer):
    import aioice.stun

    # aioice attempts stun lookup on privet network ports: these queries will never resolve
    # These attempts will timeout after 5 seconds, making connection take 5+ seconds
    # Modifying retry globals here to make it fail faster and retry more aggresively
    # Retries follow an exponential fallback: 1,2,4,8 * RETRY_RTO
    aioice.stun.RETRY_MAX = 1
    aioice.stun.RETRY_RTO = 0.2
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
    direction: Literal["sendrecv", "sendonly", "recvonly", None] = None
    track_or_kind = "video"
    if offer.tracks.machine_video:
        if offer.tracks.client_video:
            direction = "sendrecv"
        else:
            direction = "sendonly"
        vid = offer.tracks.machine_video
        track_or_kind = MediaPlayer(
            file=vid.name,
            format="v4l2",
            options={
                "video_size": f"{vid.width}x{vid.height}",
                "framerate": str(vid.fps),
                "input_format": vid.format,
            },
        ).video
    elif offer.tracks.client_video:
        direction = "recvonly"
    if direction is not None:
        trans = pc.addTransceiver(track_or_kind, direction)
        trans.setCodecPreferences(
            [
                c
                for c in RTCRtpSender.getCapabilities("video").codecs
                if c.mimeType == "video/H264"
            ]
        )

    direction = None
    track_or_kind = "audio"
    if offer.tracks.machine_audio:
        if offer.tracks.client_video:
            direction = "sendrecv"
        else:
            direction = "sendonly"
        track_or_kind = MediaPlayer(
            offer.tracks.machine_audio.name,
            format="pulse",
            options={"fragment_size": "512"},
        ).audio
    elif offer.tracks.client_video:
        direction = "recvonly"
    if direction is not None:
        trans = pc.addTransceiver(track_or_kind, direction)
        trans.setCodecPreferences(
            [
                c
                for c in RTCRtpSender.getCapabilities("audio").codecs
                if c.mimeType == "audio/opus"
            ]
        )

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


async def handle_audio_device_options(audio_device: AudioDeviceOptions):
    async with pulsectl_asyncio.PulseAsync("enumerate_devices") as pa:
        for d in await pa.sink_list() + await pa.source_list():
            if d.name == audio_device.name:
                await pa.mute(d, audio_device.mute),
                await pa.volume_set_all_chans(d, audio_device.volume)
                if audio_device.default:
                    await pa.default_set(d)


@loop_forever(0.01)
async def process_mutations(pipe: connection.Connection):
    while pipe.poll():
        mutation: MachineHTTPMutation = pipe.recv()
        match mutation:
            case AudioDeviceOptions():
                await handle_audio_device_options(mutation)
            case WebrtcOffer():
                await handle_offer(mutation)


def main(
    state_mem: SharedMemory,
    state_lock: Lock,
    pipe: connection.Connection,
):
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    global _state_mem, _state_lock
    _state_mem, _state_lock = state_mem, state_lock
    configure_root_logger()
    v4l2py.device.log.setLevel(logging.WARNING)
    av.logging.set_level(av.logging.PANIC)

    loop = asyncio.get_event_loop()
    # Specify tasks in collection to avoid garbage collection
    context = pyudev.Context()
    video_mon = Monitor.from_netlink(context)
    video_mon.filter_by("video4linux")
    audio_mon = Monitor.from_netlink(context)
    audio_mon.filter_by("sound")
    _ = (
        loop.create_task(refresh_devices(video_mon, audio_mon)),
        loop.create_task(process_mutations(pipe)),
        loop.create_task(keep_alive()),
    )
    try:
        loop.run_forever()
    finally:
        for task in asyncio.all_tasks():
            task.cancel()
        loop.close()
