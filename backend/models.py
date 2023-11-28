import re
import subprocess
from dataclasses import dataclass, field
from typing import Literal, Any

import v4l2py
from aiortc import RTCRtpCodecCapability
from pulsectl import PulseSourceInfo


@dataclass(slots=True)
class AudioTrack:
    name: str


@dataclass(slots=True)
class AudioDeviceOptions:
    name: str
    default: bool
    volume: float
    mute: bool


@dataclass(slots=True)
class AudioDevice(AudioDeviceOptions):
    description: str
    driver: str
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
        None
    ]
    index: int
    is_monitor: bool
    state: Literal["idle", "invalid", "running", "suspended"]
    type: Literal["sink", "source"]
    properties: dict[str, Any] | None = None

    @classmethod
    def from_pa(
        cls,
        d: PulseSourceInfo,
        default_name: str,
        type: Literal["sink", "source"],
    ):
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


@dataclass(slots=True)
class VideoSize:
    height: int
    width: int
    fps: list[float]
    format: str


@dataclass(slots=True)
class VideoTrack:
    name: str
    height: int
    width: int
    fps: float
    format: str


@dataclass(slots=True)
class VideoDevice:
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
            f"ffmpeg -f v4l2 -list_formats all -i {d.filename}".split(" "),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # This command should exit with code 1 (ffmpeg immediate exit)
        assert proc.returncode == 1
        ffmpeg_formats = proc.stdout
        for f in d.info.frame_sizes:
            frame_id = f"{f.height}{f.width}{f.pixel_format.name}"
            if frame_id in video_sizes:
                video_sizes[frame_id].fps.append(float(f.step_fps))
            else:
                fd = format_descriptions[f.pixel_format]
                regex = rf"^\[video4linux2,v4l2.*?\]\s*\w*\s*:\s*(\w*)\s*:\s*{fd}"
                ffmpeg_format = re.search(regex, ffmpeg_formats, re.MULTILINE)[1]
                video_sizes[frame_id] = VideoSize(
                    height=f.height,
                    width=f.width,
                    fps=[float(f.step_fps)],
                    format=ffmpeg_format,
                )
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


@dataclass(slots=True)
class WebrtcInfo:
    video_codecs: list[RTCRtpCodecCapability]
    audio_codecs: list[RTCRtpCodecCapability]


@dataclass(slots=True)
class WebrtcOffer:
    sdp: str
    type: Literal["answer", "offer", "pranswer", "rollback"]


@dataclass(slots=True)
class AudioDuplexInfo:
    remote: bool = False
    local: bool = False
    local_info: AudioTrack | None = None


@dataclass(slots=True)
class VideoDuplexInfo:
    remote: bool = False
    local: bool = False
    local_info: VideoTrack | None = None


@dataclass(slots=True)
class MachineState:
    @dataclass(slots=True)
    class Devices:
        video: dict[str, VideoDevice] = field(default_factory=dict)
        audio: dict[str, AudioDevice] = field(default_factory=dict)

    @dataclass(slots=True)
    class Tracks:
        video: VideoDuplexInfo = VideoDuplexInfo()
        audio: AudioDuplexInfo = AudioDuplexInfo()

    devices: Devices = Devices()
    tracks: Tracks = Tracks()


MachineMutation = (
    AudioDeviceOptions
    | WebrtcOffer
    | VideoTrack
    | AudioTrack
    | Literal["STOP_LOCAL_VIDEO", "STOP_LOCAL_AUDIO"]
)
MachineEvent = WebrtcOffer
