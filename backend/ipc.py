import atexit
import ctypes
import logging
import multiprocessing
import pickle
import signal
import sys
from multiprocessing import Process, Pipe
from multiprocessing.connection import Connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import RLock, Event
from typing import Callable, Any, TypeVar, Generic

from util import configure_logger

Mutations = TypeVar("Mutations")
State = TypeVar("State")

shared_mem_blocks: list[SharedMemory] = []


def exit_handler():
    logging.info("Exiting: cleaning up shared memory")
    for shm in shared_mem_blocks:
        shm.close()
        shm.unlink()


def kill_handler(*_):
    sys.exit(0)


atexit.register(exit_handler)
signal.signal(signal.SIGINT, kill_handler)
signal.signal(signal.SIGTERM, kill_handler)


class Daemon(Generic[State, Mutations]):
    def __init__(
        self,
        target: Callable[
            [RLock, Event, SharedMemory, ctypes.c_int, Connection, logging.Logger], Any
        ],
        name: str,
        logger: logging.Logger = logging.getLogger(),
    ):
        self.target = target
        self.name = name
        self.logger = logger

        self._proc_logger = configure_logger(f"proc:{name}")
        self._state: State | None = None
        self._state_lock: RLock = multiprocessing.RLock()
        self._state_mem = SharedMemory(create=True, size=1000 * 1000)
        shared_mem_blocks.append(self._state_mem)
        self._state_len: ctypes.c_int = multiprocessing.Value(
            ctypes.c_int, 0, lock=False
        )
        self._state_new: Event = multiprocessing.Event()
        self._conn = None
        self.proc = None
        self.start()

    def __del__(self):
        self._state_mem.close()
        self._state_mem.unlink()

    def start(self):
        recv_conn, send_conn = Pipe(duplex=True)
        self._conn: Connection = send_conn
        self.proc = Process(
            target=self.target,
            args=(
                self._state_lock,
                self._state_new,
                self._state_mem,
                self._state_len,
                recv_conn,
                self._proc_logger,
            ),
            daemon=True,
            name=self.name,
        )
        self.proc.start()

    @property
    def state(self) -> State | None:
        if self._state_new.is_set():
            with self._state_lock:
                self._state_new.clear()
                self._state = pickle.loads(self._state_mem.buf[: self._state_len.value])
        return self._state

    def mutate(self, mutation: Mutations):
        self._conn.send(mutation)

    @property
    def failed(self):
        return not self.proc.is_alive()

    def restart_if_failed(self):
        if not self.failed:
            return
        self.logger.error(f"process:{self.name} failed, attempting restart")
        self.proc.close()
        self.start()
        self.logger.error(f"process:{self.name} successfully restarted")


def write_buffer(mem: SharedMemory, x: Any):
    x_bytes = pickle.dumps(x)
    x_len = len(x_bytes)
    mem.buf[:x_len] = x_bytes
    return x_len
