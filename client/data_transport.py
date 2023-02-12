import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Tuple, List, Dict, Union

from redis import asyncio as redis

DeviceMode = Enum('DeviceMode', ['SAFE', 'MANUAL', 'AUTONOMOUS'])
DeviceFailure = Enum('DeviceFailure',
                     ['CAMERA', 'ULTRASONIC1', 'ULTRASONIC2', 'ULTRASONIC3', 'ULTRASONIC4', 'IMU', 'GPS'])


@dataclass
class DeviceState:
    mode: DeviceMode = "SAFE"

    coordinates: Tuple[float, float] = (None, None)
    velocity: float = None
    acceleration: Tuple[float, float, float] = (None, None, None)
    heading: float = None

    battery_voltage: float = None
    battery_percentage: float = None

    mileage: float = None
    failures: List[DeviceFailure] = field(default_factory=list)
    ultrasonic: Tuple[float, float, float, float] = (None, None, None, None)

    epoch_time: float = None

    @property
    def serialized(self) -> Dict[str, str]:
        return {k: json.dumps(v) for k, v in asdict(self).items()}


@dataclass
class DeviceCommand:
    mode: DeviceMode = "SAFE"
    data: Union[Tuple[float, float], Tuple[float, float, float], Tuple[()]] = ()
    epoch_time: float = None

    def load_dict(self, d: Dict[str, str]):
        d = {k: json.loads(v) for k, v in d.items()}
        self.mode = d[b'mode']
        self.data = d[b'data']
        self.epoch_time = d[b'epoch_time']


class DataTransport:
    def __init__(self, device_id):
        self._device_id = device_id
        self._redis = redis.Redis(host=os.environ["SC_REDIS_HOST"], port=int(os.environ["SC_REDIS_PORT"]), db=0,
                                  username=os.environ["SC_REDIS_USERNAME"], password=os.environ["SC_REDIS_PASSWORD"],
                                  retry=None, auto_close_connection_pool=True)
        self._webrtc = None
        self._redis_state_key = f"{self._device_id}/get"
        self._redis_command_key = f"{self._device_id}/post"
        self.state = DeviceState()
        self._command = DeviceCommand()
        self._tasks = []

    @property
    def command(self):
        return self._command

    async def push_state(self):
        while True:
            try:
                self.state.epoch_time = time.time()
                await self._redis.hset(self._redis_state_key, mapping=self.state.serialized)
            except  redis.RedisError as e:
                logging.error(e)
            await asyncio.sleep(0.2)

    async def pull_command(self):
        while True:
            try:
                d = await self._redis.hgetall(self._redis_command_key)
                self._command.load_dict(d)
            except Exception as e:
                logging.error(e)
            await asyncio.sleep(0.05)

    async def register(self):
        while True:
            try:
                await self._redis.zadd("devices", {self._device_id: time.time()})
            except Exception as e:
                logging.error(e)
            await asyncio.sleep(1)

    async def cleanup(self):
        await self._redis.close()
        for task in self._tasks:
            task.cancel()

    def sync(self):
        self._tasks = [asyncio.create_task(self.push_state()), asyncio.create_task(self.pull_command()),
                       asyncio.create_task(self.register())]
