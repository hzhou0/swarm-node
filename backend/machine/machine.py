import itertools
from time import sleep
from typing import Dict
from multiprocessing import connection

import pulsectl
import v4l2py
from pydantic import BaseModel

from models import AudioDevice, VideoDevice, AudioDeviceOptions


class MachineState(BaseModel):
    vid: Dict[str, VideoDevice]
    aud: Dict[str, AudioDevice]


def refresh_devices(STATE: MachineState):
    v = {}
    for d in v4l2py.iter_video_capture_devices():
        d.open()
        device = VideoDevice.from_v4l2(d)
        v[device.name] = device
        d.close()
    STATE.vid = v

    pa = pulsectl.Pulse("enumerate_devices")
    default_sink = pa.server_info().default_sink_name
    default_source = pa.server_info().default_source_name
    a = [AudioDevice.from_pa(d, default_sink, "sink") for d in pa.sink_list()]
    a += [AudioDevice.from_pa(d, default_source, "source") for d in pa.source_list()]
    a = {audio_device.name: audio_device for audio_device in a}
    pa.close()
    STATE.aud = a


def process_mutations(MUTATIONS: connection.Connection):
    while MUTATIONS.poll():
        mutation = MUTATIONS.recv()
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


def main(STATE: MachineState, MUTATIONS: connection.Connection):
    while True:
        try:
            process_mutations(MUTATIONS)
            refresh_devices(STATE)
        except Exception as e:
            print(e)
        sleep(1)
