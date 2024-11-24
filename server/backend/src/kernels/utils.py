import asyncio
import logging
from typing import Callable


def loop_forever(interval: float) -> Callable:
    def decorator(func: Callable) -> Callable:
        async def inner(*args, **kwargs):
            while True:
                try:
                    await func(*args, **kwargs)
                except Exception as e:
                    logging.exception(e)
                await asyncio.sleep(interval)

        return inner

    return decorator