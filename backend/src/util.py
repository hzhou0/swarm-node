import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from multiprocessing import current_process
from pathlib import Path

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
