#!/usr/bin/env -S sh -c '"$(dirname "$(readlink -f "$0")")/.venv/bin/python" "$0" "$@"'
import atexit
import faulthandler
import logging
import multiprocessing
import os
import signal
import sys

import uvicorn

from kernel import kernel_init
from util import configure_root_logger, provision_app_dirs


def main():
    assert sys.platform == "linux"
    multiprocessing.freeze_support()
    multiprocessing.spawn.freeze_support()
    multiprocessing.set_start_method("spawn")
    faulthandler.enable()
    provision_app_dirs()
    configure_root_logger(clear_log_files=os.getenv("env") == "dev")

    bg_kernel=kernel_init()

    # Workaround for https://github.com/encode/uvicorn/issues/1579
    class Server(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass

    from server import server
    config = uvicorn.Config(
        server(bg_kernel), host="0.0.0.0", port=8080, workers=1, access_log=False
    )
    _server_proc=Server(config=config)
    try:
        _server_proc.run()
    finally:
        bg_kernel.d.destroy()


if __name__ == "__main__":
    main()
