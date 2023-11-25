import itertools
import logging
from ctypes import c_int
from multiprocessing import connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import RLock, Event
from time import sleep

import pulsectl
import v4l2py

from models import AudioDevice, VideoDevice, AudioDeviceOptions, MachineState
from ipc import write_buffer

machine_state = MachineState()


def refresh_devices():
    v = {}
    for d in v4l2py.iter_video_capture_devices():
        d.open()
        device = VideoDevice.from_v4l2(d)
        v[device.name] = device
        d.close()
    machine_state.vid = v

    pa = pulsectl.Pulse("enumerate_devices")
    default_sink = pa.server_info().default_sink_name
    default_source = pa.server_info().default_source_name
    a = [AudioDevice.from_pa(d, default_sink, "sink") for d in pa.sink_list()]
    a += [AudioDevice.from_pa(d, default_source, "source") for d in pa.source_list()]
    a = {audio_device.name: audio_device for audio_device in a}
    pa.close()
    machine_state.aud = a


def process_mutations(mutations: connection.Connection):
    while mutations.poll():
        mutation = mutations.recv()
        match mutation:
            case AudioDeviceOptions():
                audio_device: AudioDeviceOptions = mutation
                pa = pulsectl.Pulse("mutate_audio_device")
                for d in itertools.chain(pa.sink_list(), pa.source_list()):
                    if d.name == audio_device.name:
                        if audio_device.default:
                            pa.default_set(d)
                        pa.mute(d, audio_device.mute)
                        pa.volume_set_all_chans(d, audio_device.volume)
                pa.close()


def main(
    state_lock: RLock,
    state_new: Event,
    state_mem: SharedMemory,
    state_len: c_int,
    mutations: connection.Connection,
    logger: logging.Logger,
):
    while True:
        try:
            process_mutations(mutations)
            refresh_devices()
            with state_lock:
                state_len.value = write_buffer(state_mem, machine_state)
                state_new.set()
        except Exception as e:
            logger.exception(e)
        sleep(1)
