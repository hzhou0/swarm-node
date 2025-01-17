import logging
import re
import subprocess
from typing_extensions import TypeVar
from typing import (
    Literal,
    Any,
    Protocol,
    NoReturn,
    Callable,
    runtime_checkable,
)

import av
import v4l2py
from litestar.handlers import HTTPRouteHandler
from msgspec import Struct, field
from pulsectl import PulseSourceInfo

from ipc import Daemon


class AudioDeviceOptions(Struct, frozen=True):
    name: str
    default: bool
    volume: float
    mute: bool


class AudioDevice(AudioDeviceOptions, frozen=True):
    description: str
    driver: str
    index: int
    is_monitor: bool
    state: Literal["idle", "invalid", "running", "suspended"]
    type: Literal["sink", "source"]
    properties: dict[str, Any] | None = None
    form_factor: Literal[
                     "car",
                     "computer",
                     "hands-free",
                     "handset",
                     "headphone",
                     "headset",
                     "hifi",
                     "internal",
                     "microphone",
                     "portable",
                     "speaker",
                     "tv",
                     "webcam",
                     "unknown",
                 ] | None = None

    @classmethod
    def from_pa(
            cls,
            d: PulseSourceInfo,
            default_name: str,
            type: Literal["sink", "source"],
    ):
        # noinspection PyProtectedMember
        return cls(
            default=d.name == default_name,
            description=d.description,
            driver=d.driver,
            form_factor=d.proplist.get("device.form_factor"),
            index=d.index,
            is_monitor=d.proplist.get("device.class") == "monitor",
            mute=bool(d.mute),
            name=d.name,
            properties=d.proplist,
            state=d.state._value,
            type=type,
            volume=d.volume.value_flat,
        )


class VideoSize(Struct, frozen=True):
    height: int
    width: int
    fps: list[float]
    format: str


class VideoDevice(Struct, frozen=True):
    name: str
    index: int
    closed: bool
    description: str
    capabilities: list[str]
    video_sizes: tuple[VideoSize, ...]

    @classmethod
    def from_v4l2(cls, d: v4l2py.Device):
        video_sizes: dict[str, VideoSize] = {}
        format_descriptions = {f.pixel_format: f.description for f in d.info.formats}
        proc = subprocess.run(
            f"ffmpeg -f v4l2 -list_formats compressed -i {d.filename}".split(" "),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # This command should exit with code 1 (ffmpeg immediate exit)
        assert proc.returncode == 1
        ffmpeg_formats = proc.stdout
        invalid_formats = set()
        for f in d.info.frame_sizes:
            frame_id = f"{f.height}{f.width}{f.pixel_format.name}"
            if frame_id in video_sizes:
                video_sizes[frame_id].fps.append(float(f.step_fps))
            else:
                fd = format_descriptions[f.pixel_format]
                regex = rf"^\[video4linux2,v4l2.*?\]\s*\w*\s*:\s*(\w*)\s*:\s*{fd}"
                ffmpeg_format_match = re.search(regex, ffmpeg_formats, re.MULTILINE)
                if ffmpeg_format_match is None:
                    continue
                ffmpeg_format = ffmpeg_format_match[1]
                # noinspection PyUnresolvedReferences
                if ffmpeg_format in av.formats_available:
                    video_sizes[frame_id] = VideoSize(
                        height=f.height,
                        width=f.width,
                        fps=[float(f.step_fps)],
                        format=ffmpeg_format,
                    )
                elif ffmpeg_format not in invalid_formats:
                    logging.warning(
                        f'Format "{ffmpeg_format}" unavailable in ffmpeg, discarded'
                    )
                    invalid_formats.add(ffmpeg_format)
        return cls(
            name=str(d.filename),
            index=d.index,
            closed=d.closed,
            description=d.info.card,
            capabilities=[
                flag.name
                for flag in d.info.capabilities.__class__
                if flag in d.info.capabilities
            ],
            video_sizes=tuple(video_sizes.values()),
        )


class IceServer(Struct, frozen=True):
    urls: str
    username: str | None = None
    credential: str | None = None


class WebrtcInfo(Struct, frozen=True):
    ice_servers: list[IceServer]


class VideoTrack(Struct, frozen=True):
    name: str
    height: int
    width: int
    fps: float
    format: str


class AudioTrack(Struct, frozen=True):
    name: str


class Tracks(Struct, frozen=True):
    client_video: bool = False
    client_audio: bool = False
    machine_video: VideoTrack | None = None
    machine_audio: AudioTrack | None = None


class WebrtcOffer(Struct, frozen=True):
    sdp: str
    type: Literal["answer", "offer", "pranswer", "rollback"]
    tracks: Tracks


class KernelState(Struct):
    class Devices(Struct):
        video: dict[str, VideoDevice] = field(default_factory=dict)
        audio: dict[str, AudioDevice] = field(default_factory=dict)

    devices: Devices = field(default_factory=Devices)
    webrtc_offer: WebrtcOffer | None = None


Mutation = TypeVar("Mutation", default=None)
Event = TypeVar("Event", default=None)


@runtime_checkable
class BackgroundKernel(Protocol[Mutation, Event]):
    id: str
    d: Daemon[KernelState, WebrtcOffer | Mutation, WebrtcOffer | Event]
    http_routes: Callable[[], list[HTTPRouteHandler]] = lambda self: []


@runtime_checkable
class ForegroundKernel(Protocol):
    id: str

    @staticmethod
    def entrypoint() -> Callable[[], NoReturn]:
        pass

WebrtcTrackDirection: Literal["sendrecv", "sendonly", "recvonly", None]
