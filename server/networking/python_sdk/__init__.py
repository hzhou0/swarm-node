import fcntl
import logging
import os
import queue
import selectors
import sys
import threading
from queue import SimpleQueue

from google.protobuf import message

from python_sdk.networking_pb2 import DataTransmission, Event, State

__all__ = ["receive_event", "set_state", "send_data", "eventQueue"]


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
    raise RuntimeError("File Handle 3 (eventR) not present")
if not is_valid_fd(STATE_W_FD):
    raise RuntimeError("File Handle 4 (stateW) not present")
fcntl.fcntl(STATE_W_FD, fcntl.F_SETFL, os.O_NONBLOCK)


def get_buffer_view(in_bytes):
    mv = memoryview(in_bytes)
    if mv.ndim > 1 or mv.itemsize > 1:
        raise BufferError("object must be a single-dimension buffer of bytes.")
    try:
        mv = mv.cast("c")
    except AttributeError:
        pass
    return mv


def cobs_encode(in_bytes: bytes):
    """Encode a string using Consistent Overhead Byte Stuffing (COBS).

    Input is any byte string. Output is also a byte string, without framing 0x00 bytes.

    Encoding guarantees no zero bytes in the output. The output
    string will be expanded slightly, by a predictable amount.

    An empty string is encoded to '\\x01'"""
    in_bytes_mv = get_buffer_view(in_bytes)
    final_zero = True
    out_bytes = bytearray()
    idx = 0
    search_start_idx = 0
    for in_char in in_bytes_mv:
        if in_char == b"\x00":
            final_zero = True
            out_bytes.append(idx - search_start_idx + 1)
            out_bytes += in_bytes_mv[search_start_idx:idx]
            search_start_idx = idx + 1
        else:
            if idx - search_start_idx == 0xFD:
                final_zero = False
                out_bytes.append(0xFF)
                out_bytes += in_bytes_mv[search_start_idx : idx + 1]
                search_start_idx = idx + 1
        idx += 1
    if idx != search_start_idx or final_zero:
        out_bytes.append(idx - search_start_idx + 1)
        out_bytes += in_bytes_mv[search_start_idx:idx]
    return bytes(out_bytes)


class DecodeError(Exception):
    pass


def cobs_decode(in_bytes: bytes):
    """Decode a string using Consistent Overhead Byte Stuffing (COBS).

    Input should be a byte string that has been COBS encoded, without framing 0x00 bytes. Output
    is also a byte string.

    A cobs.DecodeError exception will be raised if the encoded data
    is invalid."""
    in_bytes_mv = get_buffer_view(in_bytes)
    out_bytes = bytearray()
    idx = 0

    if len(in_bytes_mv) > 0:
        while True:
            length = ord(in_bytes_mv[idx])
            if length == 0:
                raise DecodeError("zero byte found in input")
            idx += 1
            end = idx + length - 1
            copy_mv = in_bytes_mv[idx:end]
            if b"\x00" in copy_mv:
                raise DecodeError("zero byte found in input")
            out_bytes += copy_mv
            idx = end
            if idx > len(in_bytes_mv):
                raise DecodeError("not enough input bytes for length code")
            if idx < len(in_bytes_mv):
                if length < 0xFF:
                    out_bytes.append(0)
            else:
                break
    return bytes(out_bytes)


def poll_pipe(queue: SimpleQueue[Event]):
    sel = selectors.DefaultSelector()
    sel.register(EVENT_R_FD, selectors.EVENT_READ)

    try:
        while True:
            sel.select()
            with os.fdopen(EVENT_R_FD, "r") as f:
                contents = f.read()

            begin = None
            end = None

            for i, c in enumerate(contents):
                if c == 0x00 and begin is None:
                    begin = i
                if c == 0x00 and begin is not None:
                    end = i
                if begin is not None and end is not None:
                    msg = c[begin + 1 : end]
                    begin = end = None
                    if len(msg) != 0:
                        try:
                            queue.put(Event().ParseFromString(msg), block=True)
                        except message.DecodeError:
                            continue
    except Exception as e:
        logging.exception(e)
    finally:
        sys.exit()


eventQueue = queue.SimpleQueue()

event_r_thread = threading.Thread(target=poll_pipe, args=(eventQueue,), daemon=True)
event_r_thread.start()


def receive_event() -> Event | None:
    try:
        return eventQueue.get_nowait()
    except queue.Empty:
        return None


def send_data(data: DataTransmission):
    try:
        os.write(STATE_W_FD, "\0" + data.SerializeToString() + "\0")
    except BlockingIOError:
        sys.exit()


def set_state(state: State):
    try:
        os.write(STATE_W_FD, "\0" + state.SerializeToString() + "\0")
    except BlockingIOError:
        sys.exit()
