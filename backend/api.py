from multiprocessing import connection
from typing import List, Literal, Set

from aiortc import (
    RTCRtpSender,
    RTCPeerConnection,
    MediaStreamTrack,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaPlayer
from fastapi import APIRouter

from machine.machine import MachineState
from models import (
    AudioDevice,
    AudioStream,
    VideoStream,
    VideoDevice,
    webrtcInfo,
    webrtcOffer,
    AudioDeviceOptions,
)

MACHINE: MachineState | None = None
MUTATION: connection.Connection | None = None
PEER_CONNS: Set[RTCPeerConnection] = set()
AUDIO_STREAM: MediaStreamTrack | None = None
AUDIO_STREAM_INFO: AudioStream | None = None
VIDEO_STREAM: MediaStreamTrack | None = None
VIDEO_STREAM_INFO: VideoStream | None = None

api = APIRouter(prefix="/api")


@api.get(
    "/devices/audio",
    response_model=List[AudioDevice],
    response_model_exclude_unset=True,
)
def list_audio_devices(
    type: Literal["sink", "source"] | None = None, include_properties: bool = False
):
    res = MACHINE.aud.values()
    if type is not None:
        res = [d for d in res if d.type == type]
    if not include_properties:
        res = [d.model_dump(exclude={"properties"}) for d in res]
    return res


@api.put("/devices/audio")
def put_audio_device(options: AudioDeviceOptions) -> None:
    MUTATION.send(options)


@api.get("/devices/video")
def list_video_devices() -> List[VideoDevice]:
    return [*MACHINE.vid.values()]


@api.get("/stream/video")
def video_stream_info() -> VideoStream | None:
    return VIDEO_STREAM_INFO


@api.put("/stream/video")
def start_video_stream(stream: VideoStream) -> None:
    global VIDEO_STREAM, VIDEO_STREAM_INFO
    if VIDEO_STREAM is not None:
        VIDEO_STREAM.stop()
    VIDEO_STREAM = MediaPlayer(
        stream.name,
        format="v4l2",
        options={
            "video_size": f"{stream.width}x{stream.height}",
            "framerate": str(stream.fps),
            "input_format": stream.format,
        },
    ).video
    VIDEO_STREAM_INFO = stream


@api.delete("/stream/video")
def stop_video_stream() -> None:
    global VIDEO_STREAM, VIDEO_STREAM_INFO
    if VIDEO_STREAM is not None:
        VIDEO_STREAM.stop()
    VIDEO_STREAM = VIDEO_STREAM_INFO = None


@api.get("/stream/audio")
def audio_stream_info() -> AudioStream | None:
    return AUDIO_STREAM_INFO


@api.put("/stream/audio")
def start_audio_stream(stream: AudioStream) -> None:
    global AUDIO_STREAM, AUDIO_STREAM_INFO
    if AUDIO_STREAM is not None:
        AUDIO_STREAM.stop()
    AUDIO_STREAM = MediaPlayer(
        stream.name,
        format="pulse",
    ).audio
    AUDIO_STREAM_INFO = stream


@api.delete("/stream/audio")
def stop_audio_stream() -> None:
    global AUDIO_STREAM, AUDIO_STREAM_INFO
    if AUDIO_STREAM is not None:
        AUDIO_STREAM.stop()
    AUDIO_STREAM = AUDIO_STREAM_INFO = None


@api.get("/webrtc")
def webrtc_info() -> webrtcInfo:
    return webrtcInfo(
        video_codecs=RTCRtpSender.getCapabilities("video").codecs,
        audio_codecs=RTCRtpSender.getCapabilities("audio").codecs,
    )


async def on_connectionstatechange(pc: RTCPeerConnection):
    print("Connection state is %s" % pc.connectionState)
    if pc.connectionState == "failed":
        await pc.close()
        PEER_CONNS.discard(pc)


@api.post("/webrtc")
async def webrtc_offer(offer: webrtcOffer) -> webrtcOffer:
    offer = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc = RTCPeerConnection()
    PEER_CONNS.add(pc)
    pc.add_listener("connectionstatechange", lambda: on_connectionstatechange(pc))

    if VIDEO_STREAM:
        video_sender = pc.addTrack(VIDEO_STREAM)
        trans = next(t for t in pc.getTransceivers() if t.sender == video_sender)
        trans.setCodecPreferences(
            [
                c
                for c in RTCRtpSender.getCapabilities("video").codecs
                if c.mimeType == "video/H264"
            ]
        )
    if AUDIO_STREAM:
        audio_sender = pc.addTrack(AUDIO_STREAM)
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

    return webrtcOffer(sdp=pc.localDescription.sdp, type=pc.localDescription.type)
