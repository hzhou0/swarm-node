import faulthandler
import multiprocessing
import os
import shutil
import sys
from contextlib import asynccontextmanager
from multiprocessing import Process, Manager, Pipe
from multiprocessing.managers import SyncManager
from time import sleep

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

import api
from util import configure_logger, process_governor


@asynccontextmanager
async def lifespan(_: FastAPI):
    assert sys.platform == "linux"
    manager: SyncManager
    with Manager() as manager:
        faulthandler.enable()
        configure_logger()
        state = manager.dict()
        mutations = manager.dict()
        bootstrapped = manager.Event()
        p = Process(target=process_governor, args=(state, mutations, bootstrapped))
        p.start()
        bootstrapped.wait()
        api.MACHINE = state["machine"]
        api.MUTATION = mutations["machine"]
        yield


server = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    title="Shop Cart",
)
server.mount("/public", StaticFiles(directory="public"))
server.include_router(api.api)
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


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    if os.getenv("env") == "dev":
        shutil.rmtree("log")
        os.mkdir("log")

    # Workaround for https://github.com/encode/uvicorn/issues/1579
    class Server(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass

    config = uvicorn.Config(
        server, host="127.0.0.1", port=8080, workers=1, access_log=False
    )
    Server(config=config).run()
