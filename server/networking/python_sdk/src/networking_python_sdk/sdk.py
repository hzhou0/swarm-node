import asyncio
import fcntl
import logging
import os
import signal
import sys
from asyncio import QueueEmpty, QueueFull
from typing import Generic, TypeVar

import msgspec.msgpack
from cobs import cobs
from google.protobuf import message

from .networking_pb2 import Event, DataTransmission, State, Mutation


# Check if an FD is open and valid
def is_valid_fd(fd: int):
    try:
        fcntl.fcntl(fd, fcntl.F_GETFD)
        return True
    except OSError:
        return False


T = TypeVar("T")


# Singleton
class SwarmNet(Generic[T]):
    EVENT_R_FD = 3
    STATE_W_FD = 4
    data_queue: asyncio.Queue[tuple[str, T]] = asyncio.Queue(maxsize=100)
    write_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

    _achieved_state_cond = asyncio.Event()
    _achieved_state: None | State = None
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SwarmNet, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not is_valid_fd(self.EVENT_R_FD):
            print("File Handle 3 (eventR) not present")
            raise RuntimeError("File Handle 3 (eventR) not present")
        if not is_valid_fd(self.STATE_W_FD):
            print("File Handle 4 (stateW) not present")
            raise RuntimeError("File Handle 4 (stateW) not present")
        EVENT_R_FD_SIZE = fcntl.fcntl(self.EVENT_R_FD, fcntl.F_GETPIPE_SZ)
        STATE_W_FD_SIZE = fcntl.fcntl(self.STATE_W_FD, fcntl.F_GETPIPE_SZ)
        log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.WARNING))

        def signal_handler(sig, frame):
            print("gracefully terminated")
            os.close(self.EVENT_R_FD)
            os.close(self.STATE_W_FD)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Setup async callback to poll event pipe
        loop = asyncio.get_running_loop()
        data_decoder = msgspec.msgpack.Decoder(T, strict=True)
        events: list[Event] = []

        def r_callback():
            try:
                contents = os.read(self.EVENT_R_FD, EVENT_R_FD_SIZE)
                logging.debug(contents)
                begin = None
                end = None

                for i, c in enumerate(contents):
                    if c == 0:
                        if begin is None:
                            begin = i
                        else:
                            end = i
                    if begin is not None and end is not None:
                        msg = contents[begin + 1 : end]
                        begin = end = None
                        if len(msg) != 0:
                            try:
                                event = Event()
                                event.ParseFromString(cobs.decode(msg))
                                events.append(event)
                                logging.debug(f"parsed event {event}")
                            except message.DecodeError as e:
                                logging.exception(e)
                                continue
            except Exception as e:
                logging.exception(e)

            for ev in events:
                if ev.HasField("data"):
                    try:
                        data = data_decoder.decode(ev.data.payload)
                        try:
                            self.data_queue.put_nowait((ev.data.channel.src_uuid, data))
                        except QueueFull:
                            logging.debug("queue full, dropping message")
                    except msgspec.DecodeError as e:
                        logging.exception(e)
                if ev.HasField("achievedState"):
                    self._achieved_state = ev.achievedState
                    self._achieved_state_cond.set()

        loop.add_reader(self.EVENT_R_FD, r_callback)

        def w_callback():
            write_buf = bytearray()
            while True:
                try:
                    msg = self.write_queue.get_nowait()
                except QueueEmpty:
                    break
                if len(msg) + len(write_buf) > STATE_W_FD_SIZE:
                    os.write(self.STATE_W_FD, write_buf)
                    write_buf.clear()
                write_buf.extend(msg)
            if len(write_buf):
                os.write(self.STATE_W_FD, write_buf)

        loop.add_writer(self.STATE_W_FD, w_callback)

    async def achieved_state(self):
        await self._achieved_state_cond.wait()
        ret = self._achieved_state
        assert ret is not None
        self._achieved_state = None
        self._achieved_state_cond.clear()
        return ret

    async def send_data(self, data: DataTransmission):
        m = Mutation()
        m.data.CopyFrom(data)
        binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
        await self.write_queue.put(binstr)

    async def set_state(self, state: State):
        m = Mutation()
        m.setState.CopyFrom(state)
        binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
        await self.write_queue.put(binstr)
