#!/usr/bin/env -S sh -c '"$(dirname "$(readlink -f "$0")")/.venv/bin/python" "$0" "$@"'
import faulthandler
import multiprocessing
import os
import sys
from pathlib import Path

import uvicorn

from processes import Processes
from util import configure_root_logger, provision_app_dirs


def main():
    assert sys.platform == "linux"
    multiprocessing.freeze_support()
    multiprocessing.spawn.freeze_support()
    multiprocessing.set_start_method("spawn")
    faulthandler.enable()
    provision_app_dirs()
    configure_root_logger(clear_log_files=os.getenv("env") == "dev")
    Processes.init()

    # Workaround for https://github.com/encode/uvicorn/issues/1579
    class Server(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass

    # imported here because it depends on PROCESSES
    from server import server
    config = uvicorn.Config(
        server(), host="127.0.0.1", port=8080, workers=1, access_log=False
    )
    Server(config=config).run()


if __name__ == "__main__":
    main()
