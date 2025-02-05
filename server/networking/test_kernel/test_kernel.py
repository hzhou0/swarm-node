import asyncio
import os
import sys

import gi
import msgspec

from networking_python_sdk import SwarmNet
from networking_python_sdk.networking_pb2 import DataTransmission, DataChannel

print(os.environ)
print(sys.path)
gi.require_version("Gst", "1.0")


async def modify_state(swarm_net: SwarmNet[str]):
    state = await swarm_net.achieved_state()
    state.reconnectAttempts += 1  # Increment reconnect attempts
    await swarm_net.set_state(state)


async def echo_data(swarm_net: SwarmNet[str]):
    while True:
        # echo incoming data
        src, data = await swarm_net.data_queue.get()
        await swarm_net.send_data(
            DataTransmission(
                channel=DataChannel(dest_uuid=src),
                payload=msgspec.msgpack.encode(data),
            )
        )


async def main():
    # List all file descriptors in the current process
    print(os.environ)
    fds = os.listdir("/proc/self/fd")

    print("Open file descriptors:")
    for fd in fds:
        try:
            link = os.readlink(f"/proc/self/fd/{fd}")
            print(f"FD {fd}: {link}")
        except OSError:
            pass  # Ignore errors (e.g., invalid links

    swarm_net = SwarmNet[str]()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(echo_data(swarm_net))
        tg.create_task(modify_state(swarm_net))


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    except Exception:
        pass
    finally:
        loop.stop()
    loop.close()
    # if event.HasField("data"):
    #     if event.data.HasField("channel"):
    #         event.data.channel.dest_uuid = event.data.channel.src_uuid
    #         event.data.channel.ClearField("src_uuid")
    #     swarm_net.send_data(event.data)
    # elif event.HasField("media"):
    #     media = event.media
    #     new_media = MediaChannel()
    #     if media.src_uuid:
    #         new_media.dest_uuid = media.src_uuid
    #     if media.HasField("track"):
    #         new_media.track.CopyFrom(media.track)
    #     new_media.close = media.close
    #     # Create a State mutation with the new MediaChannel
    #     state = State()
    #     state.media.append(new_media)
    #     swarm_net.set_state(state)
    # # Handle achievedState (State update)
    # elif event.HasField("achievedState"):
    #     new_state = State()
    #     new_state.CopyFrom(event.achievedState)
    #     new_state.reconnectAttempts += 1  # Increment reconnect attempts
    #     swarm_net.set_state(new_state)
