import logging
from enum import Enum
from time import sleep
from typing import ClassVar, Type

import msgspec
import pyudev
import serial

from util import configure_root_logger


class DecodeError(Exception):
    pass


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
                out_bytes += in_bytes_mv[search_start_idx: idx + 1]
                search_start_idx = idx + 1
        idx += 1
    if idx != search_start_idx or final_zero:
        out_bytes.append(idx - search_start_idx + 1)
        out_bytes += in_bytes_mv[search_start_idx:idx]
    return bytes(out_bytes)


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


class RP2040Exception(Exception):
    pass


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
                *self.right_back,
                *self.left_front,
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


class RP2040Events(Enum):
    STATE = 0
    PRINT_BYTES = 1
    PRINT_STRING = 2
    LOG = 3


class RP2040(msgspec.Struct):
    battery_charged: tuple[bool, bool, bool, bool] | None = None
    in_conn: bool | None = None  # whether a power supply is charging the system
    _serial: serial.Serial | None = None

    def process_events(self):
        if self._serial is None:
            self._serial = self.connect()
        try:
            while True:
                if self._serial.in_waiting == 0:
                    break
                b = bytearray(200)
                b_len = 0
                for i in range(200):
                    char = self._serial.read(1)[0]
                    if char == 0:
                        b_len = i
                        break
                    b[i] = char
                b = cobs_decode(b[:b_len])
                event_id, event_body = RP2040Events(b[0]), b[1:]
                match event_id:
                    case RP2040Events.STATE:
                        self.battery_charged = tuple(bool(b) for b in event_body[:4])
                        self.in_conn = bool(b[4])
                        break
                    case RP2040Events.PRINT_BYTES:
                        print(list(event_body))
                    case RP2040Events.PRINT_STRING:
                        print(event_body.decode("ascii"))
                    case RP2040Events.LOG:
                        i = 0
                        for i, char in enumerate(event_body):
                            if char == 0:
                                break
                        file_name = event_body[:i].decode('ascii')
                        level = int(event_body[i + 1])
                        line = int.from_bytes(event_body[i + 2:i + 6], 'big', signed=False)
                        msg = event_body[i + 6:].decode('ascii')
                        logging.log(level, f"{file_name}:{line} {msg}")
        except serial.SerialException as e:
            logging.exception(e)
            self.disconnect()
            return

    def mutate(self, mut: ServoDegrees | RequestState | Type[RequestState]):
        if self._serial is None:
            self._serial = self.connect()
        try:
            self._serial.write(cobs_encode(mut.to_bytes()) + b"\0")
        except serial.SerialException as e:
            logging.exception(e)
            self.disconnect()

    @staticmethod
    def connect() -> serial.Serial | None:
        try:
            context = pyudev.Context()
            rp2040s = list(
                context.list_devices(subsystem="tty", ID_VENDOR_ID="2e8a", ID_MODEL_ID="000a")
            )
            assert len(rp2040s) == 1
            assert rp2040s[0].device_node is not None
            # Virtual serial port (USB CDC) is not affected by settings
            s = serial.Serial(port=rp2040s[0].device_node, timeout=0, write_timeout=1)
            assert s.is_open
            s.flush()
            return s
        except Exception as e:
            logging.exception(e)
        return None

    def disconnect(self):
        if self._serial is None:
            pass
        try:
            self._serial.close()
        finally:
            self._serial = None


if __name__ == "__main__":
    configure_root_logger()
    state = RP2040()
    while True:
        state.process_events()
        sleep(0.1)
