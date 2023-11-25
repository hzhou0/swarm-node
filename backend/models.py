import re
import subprocess
from typing import Literal, Dict, Any, List, Type

import pulsectl
import v4l2py
from aiortc import RTCRtpCodecCapability
from pydantic import BaseModel


class AudioStream(BaseModel):
    name: str


class AudioDeviceOptions(BaseModel):
    name: str
    default: bool
    volume: float
    mute: bool


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
    ] | None
    index: int
    is_monitor: bool
    properties: Dict[str, Any] | None = None
    state: Literal["idle", "invalid", "running", "suspended"]
    type: Literal["sink", "source"]

    @classmethod
    def from_pa(
        cls,
        d: pulsectl.PulseSourceInfo,
        default_name: str,
        type: Literal["sink", "source"],
    ):
        return cls(
            default=d.name == default_name,
            description=d.description,
            driver=d.driver,
            form_factor=d.proplist.get("device.form_factor"),
            index=bool(d.index),
            is_monitor=d.proplist.get("device.class") == "monitor",
            mute=d.mute,
            name=d.name,
            properties=d.proplist,
            state=d.state._value,
            type=type,
            volume=d.volume.value_flat,
        )


class VideoSize(BaseModel):
    height: int
    width: int
    fps: List[float]
    format: str


class VideoStream(BaseModel):
    name: str
    height: int
    width: int
    fps: float
    format: str


class VideoDevice(BaseModel):
    name: str
    index: int
    closed: bool
    description: str
    capabilities: List[str]
    video_sizes: List[VideoSize]

    @classmethod
    def from_v4l2(cls, d: v4l2py.Device):
        video_sizes: Dict[str, VideoSize] = {}
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
            video_sizes=video_sizes.values(),
        )


class webrtcInfo(BaseModel):
    video_codecs: List[RTCRtpCodecCapability]
    audio_codecs: List[RTCRtpCodecCapability]


class webrtcOffer(BaseModel):
    sdp: str
    type: Literal["answer", "offer", "pranswer", "rollback"]


class MachineState(BaseModel):
    vid: Dict[str, VideoDevice] = {}
    aud: Dict[str, AudioDevice] = {}
