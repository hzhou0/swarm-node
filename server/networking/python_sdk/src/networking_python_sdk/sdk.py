import fcntl
import logging
import os
import queue
import selectors
import signal
import sys
import threading
from queue import SimpleQueue
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


def poll_pipe():
    sel = selectors.DefaultSelector()
    sel.register(SwarmNet.EVENT_R_FD, selectors.EVENT_READ)
    data_decoder = msgspec.msgpack.Decoder(T, strict=True)
    events: list[Event] = []
    while True:
        try:
            sel.select()
            contents = os.read(SwarmNet.EVENT_R_FD, 65535)
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
                    SwarmNet.data_queue.put((ev.data.channel.src_uuid, data))
                except msgspec.DecodeError as e:
                    logging.exception(e)
            if ev.HasField("achievedState"):
                SwarmNet._achieved_state = ev.achievedState


T = TypeVar("T")


# Singleton
class SwarmNet(Generic[T]):
    EVENT_R_FD = 3
    STATE_W_FD = 4
    data_queue: SimpleQueue[tuple[str, T]] = queue.SimpleQueue()
    event_r_thread = threading.Thread(target=poll_pipe, daemon=True)
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
        fcntl.fcntl(
            self.STATE_W_FD,
            fcntl.F_SETFL,
            fcntl.fcntl(self.STATE_W_FD, fcntl.F_GETFL) & ~os.O_NONBLOCK,
        )

        log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.WARNING))
        self.event_r_thread.start()

        def signal_handler(sig, frame):
            print("gracefully terminated")
            os.close(self.EVENT_R_FD)
            os.close(self.STATE_W_FD)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def achieved_state(self):
        ret = self._achieved_state
        if ret:
            self._achieved_state = None
        return ret

    def recv_data(self):
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return None

    def send_data(self, data: DataTransmission):
        try:
            m = Mutation()
            m.data.CopyFrom(data)
            binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
            logging.debug(f"sending data {binstr}")
            os.write(self.STATE_W_FD, binstr)
        except BlockingIOError as e:
            logging.exception(e)

    def set_state(self, state: State):
        try:
            m = Mutation()
            m.setState.CopyFrom(state)
            binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
            logging.debug(f"sending state {binstr}")
            os.write(self.STATE_W_FD, binstr)
        except BlockingIOError as e:
            logging.exception(e)
