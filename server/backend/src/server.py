import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Literal

import msgspec
import psutil
from litestar import Litestar, Router, get, put
from litestar.config.cors import CORSConfig
from litestar.config.response_cache import CACHE_FOREVER
from litestar.exceptions import HTTPException
from litestar.logging import LoggingConfig
from litestar.openapi import OpenAPIConfig
from litestar.static_files import StaticFilesConfig

from models import (
    AudioDevice,
    VideoDevice,
    WebrtcOffer,
    WebrtcInfo,
    BackgroundKernel,
)
from util import ice_servers

KERNEL: BackgroundKernel
@get("/devices/audio", sync_to_thread=False)
def list_audio_devices(
    type: Literal["sink", "source"] | None = None,
    include_properties: bool = False,
) -> list[AudioDevice]:
    res = KERNEL.d.state().devices.audio.values()
    if type is not None:
        res = [d for d in res if d.type == type]
    if not include_properties:
        res = [msgspec.structs.replace(d, properties=None) for d in res]
    return res


@get("/devices/video", sync_to_thread=False)
def list_video_devices() -> list[VideoDevice]:
    return [*KERNEL.d.state().devices.video.values()]


@get("/webrtc", sync_to_thread=False)
def webrtc_info() -> WebrtcInfo:
    return WebrtcInfo(ice_servers=ice_servers)


@put("/webrtc")
async def webrtc_offer(data: WebrtcOffer) -> WebrtcOffer:
    prev_offer = KERNEL.d.state().webrtc_offer
    KERNEL.d.mutate(data)
    end = time.time() + 20
    while time.time() < end:
        cur_offer = KERNEL.d.state().webrtc_offer
        if cur_offer != prev_offer:
            return cur_offer
        await asyncio.sleep(0.1)
    raise HTTPException(status_code=503, detail="webrtc reply never received")


class SysPerf(msgspec.Struct, frozen=True):
    cpu_freq_mhz: float
    cpu_percent: float
    cpu_load_avg_per_core_percent: float
    disk_total_bytes: int
    disk_free_bytes: int
    mem_total_bytes: int
    mem_available_bytes: int
    swap_bytes: int


@get("/perf/system", sync_to_thread=False, cache=5)
def get_system_performance() -> SysPerf:
    disk_usage = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    return SysPerf(
        cpu_freq_mhz=psutil.cpu_freq().current,
        cpu_percent=psutil.cpu_percent(None),
        cpu_load_avg_per_core_percent=psutil.getloadavg()[0] / psutil.cpu_count() * 100,
        disk_total_bytes=disk_usage.total,
        disk_free_bytes=disk_usage.free,
        mem_total_bytes=mem.total,
        mem_available_bytes=mem.available,
        swap_bytes=psutil.swap_memory().used,
    )


class ProcessPerf(msgspec.Struct, frozen=True):
    cpu_num: int
    cpu_percent: float
    mem_uss_percent: float
    mem_uss_bytes: int
    mem_pss_bytes: int
    swap_bytes: int
    create_time_epoch: float
    niceness: int

    @classmethod
    def from_psutil_process(cls, p: psutil.Process):
        with p.oneshot():
            mem_full = p.memory_full_info()
            return cls(
                cpu_num=p.cpu_num(),
                cpu_percent=p.cpu_percent(None),
                mem_uss_percent=p.memory_percent("uss"),
                mem_uss_bytes=mem_full.uss,
                mem_pss_bytes=mem_full.pss,
                swap_bytes=mem_full.swap,
                create_time_epoch=p.create_time(),
                niceness=p.nice(),
            )


def set_process_pids():
    process_pids: dict[str, psutil.Process] = {
        KERNEL.d.name: psutil.Process(KERNEL.d.pid),
        "server": psutil.Process(os.getpid()),
    }
    return process_pids


_process_pids = {}


@get("/perf/processes", sync_to_thread=False, cache=5)
def list_process_performance() -> dict[str, ProcessPerf]:
    global _process_pids
    try:
        ret = {
            name: ProcessPerf.from_psutil_process(proc)
            for name, proc in _process_pids.items()
        }
    except Exception as e:
        logging.exception(e)
        _process_pids = set_process_pids()
        ret = {
            name: ProcessPerf.from_psutil_process(proc)
            for name, proc in _process_pids.items()
        }
    return ret

@get('/k', sync_to_thread=False, cache=CACHE_FOREVER)
def get_kernel_id()->str:
    return KERNEL.id

def server(kernel: BackgroundKernel) -> Litestar:
    global KERNEL
    KERNEL=kernel
    kernel_routes=kernel.http_routes()
    for route in kernel_routes:
        route.operation_id = route.handler_name
    kernel_api=Router(path=f"/k/{kernel.id}",route_handlers=kernel_routes)

    route_handlers = [
        list_audio_devices,
        list_video_devices,
        webrtc_offer,
        webrtc_info,
        get_system_performance,
        list_process_performance,
        get_kernel_id
    ]
    for route in route_handlers:
        route.operation_id = route.handler_name

    api = Router(
        path="/api",
        route_handlers=route_handlers+[kernel_api],
    )
    return Litestar(
        route_handlers=[api],
        static_files_config=[
            StaticFilesConfig(
                directories=[Path(__file__).parent / "frontend_dist"],
                path="/",
                html_mode=True,
            ),
        ],
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
            title="SwarmNode",
            version="0.2.0",
        ),
        debug=True,
    )
