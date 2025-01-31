import logging
from enum import Enum
from time import sleep
from typing import ClassVar, Type, NamedTuple
import struct

import msgspec
import pyudev
import serial


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


class MPU6500Calibrate(msgspec.Struct, frozen=True):
    mutation_id: ClassVar[int] = 2

    @classmethod
    def to_bytes(cls) -> bytes:
        return bytes(
            [
                cls.mutation_id,
            ]
        )


class EmitBufferedErrorLog(msgspec.Struct, frozen=True):
    mutation_id: ClassVar[int] = 3

    @classmethod
    def to_bytes(cls) -> bytes:
        return bytes(
            [
                cls.mutation_id,
            ]
        )


class Mpu6500ResetOdom(msgspec.Struct, frozen=True):
    mutation_id: ClassVar[int] = 4

    @classmethod
    def to_bytes(cls) -> bytes:
        return bytes(
            [
                cls.mutation_id,
            ]
        )


class SetProgramOptions(msgspec.Struct, frozen=True):
    mutation_id: ClassVar[int] = 5
    log_level: logging.DEBUG | logging.INFO | logging.WARNING | logging.ERROR | logging.CRITICAL = logging.INFO
    emit_state_interval_ms: int = -1  # int16, negative means never push state to host
    emit_loop_perf: bool = False

    def to_bytes(self) -> bytes:
        return (bytes(
            [
                self.mutation_id,
                self.log_level,
            ]
        ) + self.emit_state_interval_ms.to_bytes(2, byteorder="big", signed=True)
                + bytes([int(self.emit_loop_perf)]))


class RP2040Events(Enum):
    STATE = 0
    PRINT_BYTES = 1
    PRINT_STRING = 2
    LOG = 3
    INA226_STATE = 4
    GPI_STATE = 5
    MPU6500_STATE = 6
    MAIN_LOOP_PERF = 7


class RP2040(msgspec.Struct):
    battery_charged: tuple[bool, bool, bool, bool] | None = None
    in_conn: bool | None = None  # whether a power supply is charging the system

    shunt_voltage: float = .0  # voltages in volts
    bus_voltage: float = .0
    power: float = .0  # power in watts
    energy_since_reset: float = .0  # energy consumed in watt * hours
    current: float = .0  # current in amps

    class Vector(NamedTuple):
        x: float = .0
        y: float = .0
        z: float = .0

    mpu6500_temp: float = .0  # imu temperature in Celsius
    ang_vel: Vector = Vector()  # deg/s
    direction: Vector = Vector()  # deg
    accel: Vector = Vector()  # m/s^2
    vel: Vector = Vector()  # m/s
    displacement: Vector = Vector()  # m

    loop_idle: float = .0  # percentage of time loops are idle
    loop_duration: float = .0  # duration of a single loop in seconds

    _serial: serial.Serial | None = None
    _end_of_frame: bool = False
    _start_of_frame: bool = False
    _serial_buffer: bytearray = msgspec.field(default_factory=lambda: bytearray(200))
    _serial_buffer_i: int = 0

    def process_events(self):
        if self._serial is None:
            self._serial = self.connect()
        try:
            while self._serial.in_waiting:
                self._process_event()
        except serial.SerialException as e:
            logging.exception(e)
            self.disconnect()
            return

    def _process_event(self):
        while not self._start_of_frame and self._serial_buffer_i == 0:
            while not self._end_of_frame:
                read_res = self._serial.read(1)
                if not len(read_res):
                    return
                elif read_res[0] == 0:
                    self._end_of_frame = True
            read_res = self._serial.read(1)
            # The start of frame should follow the end of frame
            # if not SoF, then the previous char wasn't the EoF. Keep looking for EoF.
            if not len(read_res):
                return
            elif read_res[0] == 0:
                self._end_of_frame = False
                self._start_of_frame = True
            else:
                self._end_of_frame = False
                return

        while True:
            read_res = self._serial.read(1)
            if not len(read_res):
                return
            else:
                self._start_of_frame = False
            if read_res[0] == 0:
                self._end_of_frame = True
                break
            if self._serial_buffer_i >= len(self._serial_buffer):
                logging.error("Event larger then allocated buffer")
                self._serial_buffer_i = 0
                return
            self._serial_buffer[self._serial_buffer_i] = read_res[0]
            self._serial_buffer_i += 1
        b = cobs_decode(self._serial_buffer[:self._serial_buffer_i])
        self._serial_buffer_i = 0
        event_id, event_body = RP2040Events(b[0]), b[1:]
        match event_id:
            case RP2040Events.STATE:
                self.battery_charged = tuple(bool(b) for b in event_body[:4])
                self.in_conn = bool(b[4])
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
            case RP2040Events.INA226_STATE:
                self.shunt_voltage = int.from_bytes(event_body[0:4], 'big', signed=True) / 1e9
                self.bus_voltage = int.from_bytes(event_body[4:8], 'big', signed=False) / 1e6
                self.power = int.from_bytes(event_body[8:12], 'big', signed=False) / 1e6
                self.current = int.from_bytes(event_body[20:24], 'big', signed=False) / 1e6
                self.energy_since_reset = int.from_bytes(event_body[12:20], 'big',
                                                         signed=False) / 1e6 / 60 / 60
            case RP2040Events.GPI_STATE:
                self.battery_charged = tuple(bool(b) for b in event_body[:4])
                self.in_conn = bool(b[4])
            case RP2040Events.MPU6500_STATE:
                values = struct.unpack_from('<f' + 'f' * 3 + 'd' * 3 + 'f' * 3 + 'd' * 3 + 'd' * 3, event_body)
                self.mpu6500_temp = values[0]
                self.ang_vel = self.Vector(*values[1:4])
                self.direction = self.Vector(*values[4:7])
                self.accel = self.Vector(*values[7:10])
                self.vel = self.Vector(*values[10:13])
                self.displacement = self.Vector(*values[13:16])
            case RP2040Events.MAIN_LOOP_PERF:
                self.loop_idle = int.from_bytes(event_body[0:2], 'big', signed=False) / 10000
                self.loop_duration = int.from_bytes(event_body[2:6], 'big', signed=False) / 10000 / (
                        1 - self.loop_idle) / 1e6
            case _:
                logging.error(f"unexpected eventid")

    def mutate(self,
               mut: ServoDegrees | Type[RequestState] | Type[MPU6500Calibrate] | Type[EmitBufferedErrorLog] | Type[
                   Mpu6500ResetOdom] | SetProgramOptions):
        if self._serial is None:
            self._serial = self.connect()
        try:
            self._serial.write(b"\0" + cobs_encode(mut.to_bytes()) + b"\0")
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
            s = serial.Serial(port=rp2040s[0].device_node, timeout=5, write_timeout=1)
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
    logging.getLogger().setLevel(logging.DEBUG)
    state = RP2040()
    state.mutate(EmitBufferedErrorLog)
    state.mutate(Mpu6500ResetOdom)
    # state.mutate(MPU6500Calibrate)
    state.mutate(SetProgramOptions(log_level=logging.INFO, emit_state_interval_ms=100, emit_loop_perf=True))
    while True:
        try:
            state.process_events()
            print(state.displacement)
        except Exception as e:
            logging.exception(e)
            pass
        sleep(0.1)
