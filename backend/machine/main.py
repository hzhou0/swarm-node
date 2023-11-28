import asyncio
import dataclasses
import logging
from multiprocessing import connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Lock

import pulsectl_asyncio
import v4l2py
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpSender,
    RTCDataChannel,
)
from aiortc.contrib.media import MediaPlayer
from aiortc.mediastreams import AudioStreamTrack, VideoStreamTrack

from ipc import write_state
from models import (
    AudioDevice,
    VideoDevice,
    AudioDeviceOptions,
    VideoTrack,
    AudioTrack,
    AudioDuplexInfo,
    VideoDuplexInfo,
    WebrtcOffer,
    MachineState,
    MachineMutation,
)
from util import configure_root_logger


@dataclasses.dataclass()
class AudioTrackDuplex:
    remote: AudioStreamTrack | None = None
    local: AudioStreamTrack | None = None
    local_info: AudioTrack | None = None

    def to_info(self) -> AudioDuplexInfo:
        remote = local = False
        if self.remote is not None:
            remote = self.remote.readyState == "live"
        if self.local is not None:
            local = self.local.readyState == "live"
        return AudioDuplexInfo(remote=remote, local=local, local_info=self.local_info)


@dataclasses.dataclass()
class VideoTrackDuplex:
    remote: VideoStreamTrack | None = None
    local: VideoStreamTrack | None = None
    local_info: VideoTrack | None = None

    def to_info(self) -> VideoDuplexInfo:
        remote = local = False
        if self.remote is not None:
            remote = self.remote.readyState == "live"
        if self.local is not None:
            local = self.local.readyState == "live"
        return VideoDuplexInfo(remote=remote, local=local, local_info=self.local_info)


machine_state = MachineState()
peer_conns: set[RTCPeerConnection] = set()
audio_tracks = AudioTrackDuplex()
video_tracks = VideoTrackDuplex()


async def on_connectionstatechange(pc: RTCPeerConnection):
    logging.info(f"Connection state is {pc.connectionState}")
    if pc.connectionState == "failed":
        await pc.close()
        peer_conns.discard(pc)


async def on_datachannel(pc: RTCPeerConnection, channel: RTCDataChannel):
    pass
    # channel.on()


async def handle_offer(pipe: connection.Connection, offer: WebrtcOffer):
    offer = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc = RTCPeerConnection()
    peer_conns.add(pc)
    pc.add_listener("connectionstatechange", lambda: on_connectionstatechange(pc))
    pc.add_listener("datachannel", lambda channel: on_datachannel(pc, channel))
    if video_tracks.local is not None:
        video_sender = pc.addTrack(video_tracks.local)
        trans = next(t for t in pc.getTransceivers() if t.sender == video_sender)
        trans.setCodecPreferences(
            [
                c
                for c in RTCRtpSender.getCapabilities("video").codecs
                if c.mimeType == "video/H264"
            ]
        )
    if audio_tracks.local is not None:
        audio_sender = pc.addTrack(audio_tracks.local)
        trans = next(t for t in pc.getTransceivers() if t.sender == audio_sender)
        trans.setCodecPreferences(
            [
                c
                for c in RTCRtpSender.getCapabilities("audio").codecs
                if c.mimeType == "audio/opus"
            ]
        )

    await pc.setRemoteDescription(offer)
    await pc.setLocalDescription(await pc.createAnswer())
    # noinspection PyTypeChecker
    pipe.send(WebrtcOffer(sdp=pc.localDescription.sdp, type=pc.localDescription.type))


async def refresh_devices(state_mem: SharedMemory, state_lock: Lock):
    while True:
        try:
            v = {}
            for d in v4l2py.iter_video_capture_devices():
                d.open()
                device = VideoDevice.from_v4l2(d)
                v[device.name] = device
                d.close()
            machine_state.devices.video = v

            async with pulsectl_asyncio.PulseAsync("enumerate_devices") as pa:
                default_sink = (await pa.server_info()).default_sink_name
                default_source = (await pa.server_info()).default_source_name
                sinks, sources = await asyncio.gather(pa.sink_list(), pa.source_list())
                a = [AudioDevice.from_pa(d, default_sink, "sink") for d in sinks]
                a += [AudioDevice.from_pa(d, default_source, "source") for d in sources]
                a = {audio_device.name: audio_device for audio_device in a}
            machine_state.devices.audio = a

            machine_state.tracks.audio = audio_tracks.to_info()
            machine_state.tracks.video = video_tracks.to_info()

            state_mem = write_state(state_mem, state_lock, machine_state)
        except Exception as e:
            logging.exception(e)
        await asyncio.sleep(2)


async def handle_audio_device_options(audio_device: AudioDeviceOptions):
    async with pulsectl_asyncio.PulseAsync("enumerate_devices") as pa:
        for d in await pa.sink_list() + await pa.source_list():
            if d.name == audio_device.name:
                await pa.mute(d, audio_device.mute),
                await pa.volume_set_all_chans(d, audio_device.volume)
                if audio_device.default:
                    await pa.default_set(d)


async def process_mutations(pipe: connection.Connection):
    while True:
        try:
            while pipe.poll():
                mutation: MachineMutation = pipe.recv()
                match mutation:
                    case AudioDeviceOptions():
                        await handle_audio_device_options(mutation)
                    case WebrtcOffer():
                        await handle_offer(pipe, mutation)
                    case VideoTrack():
                        track: VideoTrack = mutation
                        if video_tracks.local is not None:
                            video_tracks.local.stop()
                        video_tracks.local = MediaPlayer(
                            track.name,
                            format="v4l2",
                            options={
                                "video_size": f"{track.width}x{track.height}",
                                "framerate": str(track.fps),
                                "input_format": track.format,
                            },
                        ).video
                        video_tracks.local_info = track
                    case "STOP_LOCAL_VIDEO":
                        if video_tracks.local is not None:
                            video_tracks.local.stop()
                        video_tracks.local_info = video_tracks.local = None
                    case AudioTrack():
                        track: AudioTrack = mutation
                        if audio_tracks.local is not None:
                            audio_tracks.local.stop()
                        audio_tracks.local = MediaPlayer(
                            track.name, format="pulse"
                        ).audio
                        audio_tracks.local_info = track
                    case "STOP_LOCAL_AUDIO":
                        if audio_tracks.local is not None:
                            audio_tracks.local.stop()
                        audio_tracks.local_info = audio_tracks.local = None
        except Exception as e:
            logging.exception(e)
        await asyncio.sleep(0.01)


def main(
    state_mem: SharedMemory,
    state_lock: Lock,
    pipe: connection.Connection,
):
    configure_root_logger()
    v4l2py.device.log.setLevel(logging.WARNING)
    loop = asyncio.get_event_loop()
    # Specify tasks in collection to avoid garbage collection
    _ = (
        loop.create_task(refresh_devices(state_mem, state_lock)),
        loop.create_task(process_mutations(pipe)),
    )
    try:
        loop.run_forever()
    finally:
        for task in asyncio.all_tasks():
            task.cancel()
        loop.close()
