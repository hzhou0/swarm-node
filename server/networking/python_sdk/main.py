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

from networking_pb2 import Event, DataTransmission, State, Mutation


# Check if an FD is open and valid
def is_valid_fd(fd: int):
    try:
        fcntl.fcntl(fd, fcntl.F_GETFD)
        return True
    except OSError:
        return False


EVENT_R_FD = 3
STATE_W_FD = 4

if not is_valid_fd(EVENT_R_FD):
    print("File Handle 3 (eventR) not present")
    raise RuntimeError("File Handle 3 (eventR) not present")
if not is_valid_fd(STATE_W_FD):
    print("File Handle 4 (stateW) not present")
    raise RuntimeError("File Handle 4 (stateW) not present")
fcntl.fcntl(
    STATE_W_FD, fcntl.F_SETFL, fcntl.fcntl(STATE_W_FD, fcntl.F_GETFL) & ~os.O_NONBLOCK
)

log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.WARNING))


def poll_pipe(queue: SimpleQueue[Event]):
    sel = selectors.DefaultSelector()
    sel.register(EVENT_R_FD, selectors.EVENT_READ)
    while True:
        try:
            sel.select()
            contents = os.read(EVENT_R_FD, 65535)
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
                            queue.put(event)
                        except message.DecodeError as e:
                            logging.exception(e)
                            continue
        except Exception as e:
            logging.exception(e)


eventQueue: SimpleQueue[Event] = queue.SimpleQueue()
event_r_thread = threading.Thread(target=poll_pipe, args=(eventQueue,), daemon=True)
event_r_thread.start()


def signal_handler(sig, frame):
    print("gracefully terminated")
    os.close(EVENT_R_FD)
    os.close(STATE_W_FD)
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def receive_event() -> Event | None:
    try:
        return eventQueue.get_nowait()
    except queue.Empty:
        return None


def send_data(data: DataTransmission):
    try:
        m = Mutation()
        m.data.CopyFrom(data)
        binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
        logging.debug(f"sending data {binstr}")
        os.write(STATE_W_FD, binstr)
    except BlockingIOError as e:
        logging.exception(e)


def set_state(state: State):
    try:
        m = Mutation()
        m.setState.CopyFrom(state)
        binstr: bytes = b"\0" + cobs.encode(m.SerializeToString()) + b"\0"
        logging.debug(f"sending state {binstr}")
        os.write(STATE_W_FD, binstr)
    except BlockingIOError as e:
        logging.exception(e)
