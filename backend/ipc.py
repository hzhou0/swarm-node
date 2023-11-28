import atexit
import collections
import logging
import multiprocessing
import pickle
import signal
import struct
import sys
from multiprocessing import Process, Pipe
from multiprocessing.connection import Connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Lock
from typing import Callable, Any, TypeVar, Generic, NamedTuple, Generator

"""
Shared memory blocks are initially created by the reader process.
If the block is too small, the writer process will create a larger block to use.
The process that creates the block will manage it, and perform cleanup on exit. 
"""
managed_mem_blocks: set[SharedMemory] = set()


def exit_handler():
    logging.info(f"Exiting: cleaning up {len(managed_mem_blocks)} shared memory blocks")
    for shm in managed_mem_blocks:
        shm.close()
        shm.unlink()


def kill_handler(*_):
    sys.exit(0)


atexit.register(exit_handler)
signal.signal(signal.SIGINT, kill_handler)
signal.signal(signal.SIGTERM, kill_handler)

State = TypeVar("State")
Mutation = TypeVar("Mutation")
Event = TypeVar("Event")


class Daemon(Generic[State, Mutation, Event]):
    def __init__(
        self,
        target: Callable[[SharedMemory, Lock, Connection], Any],
        name: str,
        logger: logging.Logger = logging.getLogger(),
    ):
        self.target = target
        self.name = name
        self.logger = logger

        self._state: State | None = None
        self._state_lock: Lock = multiprocessing.Lock()
        self._state_mem = SharedMemory(create=True, size=1024 * 1024)
        managed_mem_blocks.add(self._state_mem)
        self._conn = self._proc = None
        self.start()

    def start(self):
        child_conn, parent_conn = Pipe(duplex=True)
        self._conn = parent_conn
        self._proc = Process(
            target=self.target,
            args=(
                self._state_mem,
                self._state_lock,
                child_conn,
            ),
            daemon=True,
            name=self.name,
        )
        self._proc.start()
        logging.info(f"Started process {self._proc.name}, pid={self._proc.pid}")

    @property
    def state(self) -> State | None:
        while True:
            header = Header.from_mem(self._state_mem)
            if not header.is_memory:
                break
            self._state_mem = pickle.loads(self._state_mem.buf[obj_slice(header)])
        if header.is_new:
            with self._state_lock:
                Header(is_new=False, obj_len=header.obj_len).write(self._state_mem)
                self._state = pickle.loads(self._state_mem.buf[obj_slice(header)])
        return self._state

    def mutate(self, mutation: Mutation):
        self._conn: Connection
        self._conn.send(mutation)

    @property
    def events(self) -> Generator[Event, None, None]:
        self._conn: Connection
        while self._conn.poll():
            yield self._conn.recv()

    def flush_events(self):
        collections.deque(self.events, maxlen=0)

    @property
    def failed(self):
        return not self._proc.is_alive()

    def restart_if_failed(self):
        if not self.failed:
            return
        self.logger.error(f"process:{self.name} failed, attempting restart")
        self._proc.close()
        self.start()
        self.logger.error(f"process:{self.name} successfully restarted")


class Header(NamedTuple):
    obj_len: int
    is_new: bool
    is_memory: bool = False
    # Not present in tuple, class variables
    spec = "n??"
    start = 0
    end = start + struct.calcsize(spec)

    def write(self, mem: SharedMemory):
        struct.pack_into(self.spec, mem.buf, self.start, *self)

    @classmethod
    def from_mem(cls, mem: SharedMemory):
        return cls._make(struct.unpack_from(cls.spec, mem.buf, cls.start))


def obj_slice(header: Header) -> slice:
    return slice(header.end, header.end + header.obj_len)


def write_state(mem: SharedMemory, lock: Lock, obj: object) -> SharedMemory:
    obj_bytes = pickle.dumps(obj)
    content_end = Header.end + len(obj_bytes)
    if content_end > mem.size:
        new_mem = SharedMemory(create=True, size=content_end * 2)
        managed_mem_blocks.add(new_mem)
        new_mem_bytes = pickle.dumps(new_mem)
        new_mem_header = Header(is_new=True, obj_len=len(new_mem_bytes), is_memory=True)
        with lock:
            new_mem_header.write(mem)
            mem.buf[obj_slice(new_mem_header)] = new_mem_bytes
        mem.close()
        logging.warning(f"Reallocated memory, new size: {new_mem.size}")
        mem = new_mem
    obj_header = Header(obj_len=len(obj_bytes), is_new=True)
    with lock:
        obj_header.write(mem)
        mem.buf[obj_slice(obj_header)] = obj_bytes
    return mem
