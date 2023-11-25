import logging
import sys
from logging.handlers import RotatingFileHandler


def configure_logger(name: str = None):
    rl = logging.getLogger(name)
    rl.setLevel(logging.INFO)
    rl.handlers.clear()
    fmt = "%(levelname)s:    %(message)s    logger:%(name)s,%(pathname)s:%(lineno)d,%(funcName)s()    %(asctime)s"
    formatter = logging.Formatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    rl.addHandler(stream_handler)
    file_handler = RotatingFileHandler(
        f"log/{name if name is not None else 'root'}.txt",
        maxBytes=1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    rl.addHandler(file_handler)
    return rl
