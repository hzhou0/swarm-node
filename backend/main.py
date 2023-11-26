import faulthandler
import multiprocessing
import os
import sys

import uvicorn

from processes import Processes
from util import configure_root_logger

if __name__ == "__main__":
    assert sys.platform == "linux"
    multiprocessing.set_start_method("spawn")
    faulthandler.enable()
    configure_root_logger(clear_log_files=os.getenv("env") == "dev")
    Processes.init()

    # Workaround for https://github.com/encode/uvicorn/issues/1579
    class Server(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass

    # imported here because it depends on PROCESSES
    from api import server

    config = uvicorn.Config(
        server, host="127.0.0.1", port=8080, workers=1, access_log=False
    )
    Server(config=config).run()
