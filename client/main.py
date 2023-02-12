import asyncio
import dotenv
from uuid import uuid4
from pathlib import Path

from data_transport import DataTransport
from depth_camera import DepthCamera


async def main():
    data_transport.sync()
    depth_camera.start()
    while True:
        await asyncio.sleep(0.1)


if __name__ == '__main__':
    dotenv.load_dotenv()
    # obtain device uuid
    marker_file = Path.home() / '.shoppingCart'
    try:
        device_uid = open(marker_file, 'r').readline()
    except OSError:
        device_uid = uuid4().hex
        open(marker_file, 'w').write(device_uid)
    # initialize data transport
    data_transport = DataTransport(device_uid)
    depth_camera = DepthCamera()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except BaseException as e:
        loop.run_until_complete(data_transport.cleanup())
        loop.close()
        raise e
