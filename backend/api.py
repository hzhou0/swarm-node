import asyncio
import dataclasses
import time
from typing import Literal, Set

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
    response_model=list[AudioDevice],
    response_model_exclude_unset=True,
)
def list_audio_devices(
    type: Literal["sink", "source"] | None = None, include_properties: bool = False
):
    res = PROCESSES.machine.state().devices.audio.values()
    if type is not None:
        res = [d for d in res if d.type == type]
    if not include_properties:
        res = [dataclasses.replace(d, properties=None) for d in res]
    return res


@api.put("/devices/audio")
def put_audio_device(options: AudioDeviceOptions) -> None:
    PROCESSES.machine.mutate(options)


@api.get("/devices/video")
def list_video_devices() -> list[VideoDevice]:
    return [*PROCESSES.machine.state().devices.video.values()]


@api.post("/webrtc")
async def webrtc_offer(offer: WebrtcOffer) -> WebrtcOffer:
    prev_offer = PROCESSES.machine.state().webrtc_offer
    PROCESSES.machine.mutate(offer)
    end = time.time() + 20
    while time.time() < end:
        cur_offer = PROCESSES.machine.state().webrtc_offer
        if cur_offer != prev_offer:
            return cur_offer
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
