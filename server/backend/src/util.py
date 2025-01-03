import asyncio
import logging
import os
import shutil
import sys
from logging.handlers import RotatingFileHandler
from multiprocessing import current_process
from pathlib import Path
from typing import Callable

import msgspec

from models import IceServer

root_dir = Path.home().joinpath("swarmnode")
log_dir = root_dir / "log"


def provision_app_dirs():
    root_dir.mkdir(0o755, parents=True, exist_ok=True)
    log_dir.mkdir(0o755, exist_ok=True)


def configure_root_logger(clear_log_files=False):
    if clear_log_files:
        shutil.rmtree(log_dir, ignore_errors=True)
        provision_app_dirs()
    name = f"proc:{current_process().name}"
    rl = logging.getLogger()
    rl.setLevel(logging.INFO)
    rl.handlers.clear()
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_fmt = (
        "%(processName)s:%(levelname)s:    %(message)s    "
        "%(filename)s:%(lineno)d,%(funcName)s()    %(asctime)s"
    )
    stream_handler.setFormatter(logging.Formatter(stream_fmt))
    rl.addHandler(stream_handler)
    file_handler = RotatingFileHandler(
        log_dir / f"{name}.txt",
        maxBytes=1024 * 1024,
        backupCount=5,
    )
    file_fmt = (
        "%(processName)s:%(name)s:%(levelname)s:    %(message)s    "
        "%(pathname)s:%(lineno)d,%(funcName)s()    %(asctime)s"
    )
    file_handler.setFormatter(logging.Formatter(file_fmt))
    rl.addHandler(file_handler)
    return rl


try:
    ice_servers = msgspec.json.decode(os.environ["ICE_SERVERS"], type=list[IceServer])
    print(f"Discovered ice_servers from environment")
except Exception as e:
    print("Using default ice servers")
    ice_servers = [IceServer(urls="stun:stun.l.google.com:19302")]


def loop_forever(interval: float) -> Callable:
    def decorator(func: Callable) -> Callable:
        async def inner(*args, **kwargs):
            while True:
                try:
                    await func(*args, **kwargs)
                except Exception as e:
                    logging.exception(e)
                await asyncio.sleep(interval)

        return inner

    return decorator
