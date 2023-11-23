import logging
import multiprocessing
import sys
import threading
from logging.handlers import RotatingFileHandler
from multiprocessing import Process, Pipe, Manager
from multiprocessing.connection import Connection
from multiprocessing.managers import SyncManager, Namespace, DictProxy
from time import sleep
from typing import Callable, Any, Tuple

from machine.machine import main


def configure_logger(name: str = None):
    rl = logging.getLogger(name)
    rl.setLevel(logging.INFO)
    rl.handlers.clear()
    fmt = "%(levelname)s:    %(message)s    logger:%(name)s,%(pathname)s:%(lineno)d,%(funcName)s()    %(asctime)s"
    formatter = logging.Formatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    rl.addHandler(stream_handler)
    file_handler = RotatingFileHandler(
        f"log/{name if name is not None else 'root'}.txt",
        maxBytes=1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    rl.addHandler(file_handler)
    return rl


def daemon(
    manager: SyncManager, target: Callable, name: str
) -> Tuple[Any, Connection, Process]:
    state = manager.Namespace()
    recv_conn, send_conn = Pipe(duplex=False)
    logger = configure_logger(f"proc:{name}")
    p = Process(target=target, args=(state, recv_conn, logger), daemon=True, name=name)
    p.start()
    return state, send_conn, p


def process_governor(
    state: DictProxy, mutations: DictProxy, bootstrapped: threading.Event
):
    processes: list[Process] = []
    manager: SyncManager
    logger = configure_logger("process_governor")
    with Manager() as m:
        logging.info(f"Process start method:{multiprocessing.get_start_method()}")
        state["machine"], mutations["machine"], proc = daemon(m, main, "machine")
        processes.append(proc)
        bootstrapped.set()
        while True:
            new_processes = []
            for p in processes:
                new_process = p
                if not p.is_alive():
                    p.terminate()
                    if p.name == "machine":
                        state["machine"], mutations["machine"], new_process = daemon(
                            m, main, "machine"
                        )
                        logger.error("Restarting machine process")
                new_processes.append(new_process)
            processes = new_processes
            sleep(5)
