import sys
from contextlib import asynccontextmanager
from multiprocessing import Process, Manager

import uvicorn
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import api
from machine.machine import main


@asynccontextmanager
async def lifespan(_: FastAPI):
    assert sys.platform == "linux"
    with Manager() as manager:
        api.MACHINE = manager.Namespace()
        p = Process(target=main, args=(api.MACHINE,), daemon=True)
        p.start()
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
    # Workaround for https://github.com/encode/uvicorn/issues/1579
    class Server(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass

    config = uvicorn.Config(server, host="127.0.0.1", port=8080, workers=1)
    Server(config=config).run()
