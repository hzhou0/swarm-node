import asyncio
import dotenv
from uuid import uuid4
from pathlib import Path

from data_transport import DataTransport
from depth_camera import DepthCamera


async def main():
    while True:
        async with asyncio.TaskGroup() as tg:
            for t in data_transport.tasks:
                tg.create_task(t)


if __name__ == '__main__':
    dotenv.load_dotenv()
    data_transport = DataTransport()
    asyncio.run(main())
