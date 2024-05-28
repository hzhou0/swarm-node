import logging
from time import sleep
from typing import ClassVar, Type

import msgspec
import pyudev
import serial

from util import configure_root_logger

_serial: serial.Serial | None = None


class DecodeError(Exception):
    pass


def _get_buffer_view(in_bytes):
    mv = memoryview(in_bytes)
    if mv.ndim > 1 or mv.itemsize > 1:
        raise BufferError("object must be a single-dimension buffer of bytes.")
    try:
        mv = mv.cast("c")
    except AttributeError:
        pass
    return mv


def _cobs_encode(in_bytes: bytes):
    """Encode a string using Consistent Overhead Byte Stuffing (COBS).

    Input is any byte string. Output is also a byte string, without framing 0x00 bytes.

    Encoding guarantees no zero bytes in the output. The output
    string will be expanded slightly, by a predictable amount.

    An empty string is encoded to '\\x01'"""
    in_bytes_mv = _get_buffer_view(in_bytes)
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


def _cobs_decode(in_bytes: bytes):
    """Decode a string using Consistent Overhead Byte Stuffing (COBS).

    Input should be a byte string that has been COBS encoded, without framing 0x00 bytes. Output
    is also a byte string.

    A cobs.DecodeError exception will be raised if the encoded data
    is invalid."""
    in_bytes_mv = _get_buffer_view(in_bytes)
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


class RP2040Exception(Exception):
    pass


_rp2040_logger = logging.getLogger("rp2040_msg")
_rp2040_logger.setLevel(logging.INFO)


class State(msgspec.Struct):
    battery_charged: tuple[bool, bool, bool, bool] | None = None
    in_conn: bool | None = None  # whether a power supply is charing the system

    def update(self):
        if _serial is None:
            connect()
        try:
            while True:
                if _serial.in_waiting == 0:
                    break
                b = bytearray(50)
                b_len = 0
                for i in range(50):
                    char = _serial.read(1)[0]
                    if char == 0:
                        b_len = i
                        break
                    b[i] = char
                b = _cobs_decode(b[:b_len])
                if b[0] == 0:
                    self.battery_charged = tuple(bool(b) for b in b[1:5])
                    self.in_conn = bool(b[5])
                    break
                elif b[0] == 1:
                    _rp2040_logger.info(list(b[1:]))
                elif b[0] == 2:
                    _rp2040_logger.info(b[1:])
        except serial.SerialException as e:
            logging.exception(e)
            disconnect()
            return


class ServoDegrees(msgspec.Struct, frozen=True):
    mutation_id: ClassVar[int] = 0
    right_front: tuple[int, int, int]
    left_front: tuple[int, int, int]
    right_back: tuple[int, int, int]
    left_back: tuple[int, int, int]

    def to_bytes(self) -> bytes:
        return bytes(
            [
                self.mutation_id,
                *self.right_front,
                *self.left_front,
                *self.right_back,
                *self.left_back,
            ]
        )


class RequestState(msgspec.Struct, frozen=True):
    mutation_id: ClassVar[int] = 1

    @classmethod
    def to_bytes(cls) -> bytes:
        return bytes(
            [
                cls.mutation_id,
            ]
        )


def mutate(mut: ServoDegrees | RequestState | Type[RequestState]):
    if _serial is None:
        connect()
    try:
        _serial.write(_cobs_encode(mut.to_bytes()) + b"\0")
    except serial.SerialException as e:
        logging.exception(e)
        disconnect()


def connect():
    context = pyudev.Context()
    rp2040s = list(
        context.list_devices(subsystem="tty", ID_VENDOR_ID="2e8a", ID_MODEL_ID="000a")
    )
    assert len(rp2040s) == 1
    assert rp2040s[0].device_node is not None
    global _serial
    # Virtual serial port (USB CDC) is not affected by settings
    s = serial.Serial(port=rp2040s[0].device_node, timeout=0, write_timeout=1)
    assert s.is_open
    s.flush()
    _serial = s


def disconnect():
    global _serial
    if _serial is None:
        pass
    try:
        _serial.close()
    finally:
        _serial = None


if __name__ == "__main__":
    configure_root_logger()
    connect()
    mutate(ServoDegrees([0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]))
    state = State()
    sleep(0.001)
    state.update()
