import asyncio
import logging
import os
import time
from typing import Literal

import msgspec
from litestar.config.cors import CORSConfig
from litestar.exceptions import HTTPException
from litestar.logging import LoggingConfig
from litestar.openapi import OpenAPIConfig
from litestar.static_files import StaticFilesConfig

from models import (
    AudioDevice,
    VideoDevice,
    WebrtcOffer,
    AudioDeviceOptions,
)
from processes import PROCESSES
from litestar import Litestar, Router, get, put, post


@get("/devices/audio", sync_to_thread=False)
def list_audio_devices(
    type: Literal["sink", "source"] | None = None, include_properties: bool = False
) -> list[AudioDevice]:
    res = PROCESSES.machine.state().devices.audio.values()
    if type is not None:
        res = [d for d in res if d.type == type]
    if not include_properties:
        res = [msgspec.structs.replace(d, properties=None) for d in res]
    return res


@put("/devices/audio", sync_to_thread=False)
def put_audio_device(data: AudioDeviceOptions) -> None:
    PROCESSES.machine.mutate(data)


@get("/devices/video", sync_to_thread=False)
def list_video_devices() -> list[VideoDevice]:
    return [*PROCESSES.machine.state().devices.video.values()]


@post("/webrtc")
async def webrtc_offer(data: WebrtcOffer) -> WebrtcOffer:
    prev_offer = PROCESSES.machine.state().webrtc_offer
    PROCESSES.machine.mutate(data)
    end = time.time() + 20
    while time.time() < end:
        cur_offer = PROCESSES.machine.state().webrtc_offer
        if cur_offer != prev_offer:
            return cur_offer
        await asyncio.sleep(0.1)
    raise HTTPException(status_code=500, detail="webrtc reply never received")


route_handlers = [
    list_audio_devices,
    put_audio_device,
    list_video_devices,
    webrtc_offer,
]
for route in route_handlers:
    route.operation_id = route.handler_name

api = Router(path="/api", route_handlers=route_handlers)
server = Litestar(
    route_handlers=[api],
    static_files_config=[StaticFilesConfig(directories=["public"], path="/public")],
    cors_config=CORSConfig(
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    ),
    logging_config=LoggingConfig(
        root={"level": logging.getLevelName(logging.INFO), "handlers": ["console"]},
        formatters={
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
    ),
    openapi_config=OpenAPIConfig(
        title="Shop Cart",
        version="0.1.0",
    ),
    debug=os.getenv("env") == "dev",
)
pass
