import asyncio
import time
from typing import List, Literal, Set

from aiortc import RTCPeerConnection
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from models import (
    AudioDevice,
    AudioTrack,
    VideoTrack,
    VideoDevice,
    WebrtcOffer,
    AudioDeviceOptions,
)
from processes import PROCESSES

PEER_CONNS: Set[RTCPeerConnection] = set()

api = APIRouter(prefix="/api")


@api.get(
    "/devices/audio",
    response_model=List[AudioDevice],
    response_model_exclude_unset=True,
)
def list_audio_devices(
    type: Literal["sink", "source"] | None = None, include_properties: bool = False
):
    res = PROCESSES.machine.state.devices.audio.values()
    if type is not None:
        res = [d for d in res if d.type == type]
    if not include_properties:
        res = [d.model_dump(exclude={"properties"}) for d in res]
    return res


@api.put("/devices/audio")
def put_audio_device(options: AudioDeviceOptions) -> None:
    PROCESSES.machine.mutate(options)


@api.get("/devices/video")
def list_video_devices() -> List[VideoDevice]:
    return [*PROCESSES.machine.state.devices.video.values()]


@api.get("/stream/video")
def video_stream_info() -> VideoTrack | None:
    return PROCESSES.machine.state.tracks.video.local_info


@api.put("/stream/video")
def start_video_stream(track: VideoTrack) -> None:
    PROCESSES.machine.mutate(track)


@api.delete("/stream/video")
def stop_video_stream() -> None:
    PROCESSES.machine.mutate("STOP_LOCAL_VIDEO")


@api.get("/stream/audio")
def audio_stream_info() -> AudioTrack | None:
    return PROCESSES.machine.state.tracks.audio.local_info


@api.put("/stream/audio")
def start_audio_stream(track: AudioTrack) -> None:
    PROCESSES.machine.mutate(track)


@api.delete("/stream/audio")
def stop_audio_stream() -> None:
    PROCESSES.machine.mutate("STOP_LOCAL_AUDIO")


@api.post("/webrtc")
async def webrtc_offer(offer: WebrtcOffer) -> WebrtcOffer:
    PROCESSES.machine.flush_events()
    PROCESSES.machine.mutate(offer)
    end = time.time() + 60
    while time.time() < end:
        event = next(PROCESSES.machine.events, None)
        if isinstance(event, WebrtcOffer):
            return event
        await asyncio.sleep(0.1)
    raise HTTPException(status_code=500, detail="webrtc reply never received")


server = FastAPI(docs_url=None, title="Shop Cart")
server.mount("/public", StaticFiles(directory="public"))
server.include_router(api)
server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@server.get("/", include_in_schema=False)
def swagger():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Shop Cart",
        swagger_favicon_url="/public/favicon.png",
    )


for route in server.routes:
    if isinstance(route, APIRoute):
        route.operation_id = route.name
