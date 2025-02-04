import fcntl
import logging
import os
import queue
import selectors
import signal
import sys
import threading
from queue import SimpleQueue

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


class SwarmNet:
    EVENT_R_FD = 3
    STATE_W_FD = 4
    eventQueue: SimpleQueue[Event] = queue.SimpleQueue()

    @classmethod
    def receive_event(cls) -> Event | None:
        try:
            return cls.eventQueue.get_nowait()
        except queue.Empty:
            return None

    @classmethod
    def send_data(cls, data: DataTransmission):
        try:
            m = Mutation()
            m.data.CopyFrom(data)
            binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
            logging.debug(f"sending data {binstr}")
            os.write(cls.STATE_W_FD, binstr)
        except BlockingIOError as e:
            logging.exception(e)

    @classmethod
    def set_state(cls, state: State):
        try:
            m = Mutation()
            m.setState.CopyFrom(state)
            binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
            logging.debug(f"sending state {binstr}")
            os.write(cls.STATE_W_FD, binstr)
        except BlockingIOError as e:
            logging.exception(e)


def poll_pipe():
    sel = selectors.DefaultSelector()
    sel.register(SwarmNet.EVENT_R_FD, selectors.EVENT_READ)
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
                            logging.debug(f"parsed event {event}")
                            SwarmNet.eventQueue.put(event)
                        except message.DecodeError as e:
                            logging.exception(e)
                            continue
        except Exception as e:
            logging.exception(e)


once = True

event_r_thread = threading.Thread(target=poll_pipe, daemon=True)


def swarm_net_init():
    global once
    if once:
        if not is_valid_fd(SwarmNet.EVENT_R_FD):
            print("File Handle 3 (eventR) not present")
            raise RuntimeError("File Handle 3 (eventR) not present")
        if not is_valid_fd(SwarmNet.STATE_W_FD):
            print("File Handle 4 (stateW) not present")
            raise RuntimeError("File Handle 4 (stateW) not present")
        fcntl.fcntl(
            SwarmNet.STATE_W_FD,
            fcntl.F_SETFL,
            fcntl.fcntl(SwarmNet.STATE_W_FD, fcntl.F_GETFL) & ~os.O_NONBLOCK,
        )

        log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.WARNING))
        event_r_thread.start()

        def signal_handler(sig, frame):
            print("gracefully terminated")
            os.close(SwarmNet.EVENT_R_FD)
            os.close(SwarmNet.STATE_W_FD)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        once = False
    return SwarmNet
