import importlib
import logging
import os
import sys
import time
from threading import Thread
from typing import Type, Callable, NoReturn

from litestar import put

from ipc import Daemon
from models import AudioDeviceOptions, BackgroundKernel, ForegroundKernel

class December(BackgroundKernel[AudioDeviceOptions, None]):
    id = "december"

    def http_routes(self):
        @put("/devices/audio", sync_to_thread=False)
        def december_put_audio_device(data: AudioDeviceOptions) -> None:
            self.d.mutate(data)

        return [december_put_audio_device]

    def __init__(self):
        december = importlib.import_module("kernels.december")
        entrypoint = getattr(december, "main")
        self.d = Daemon(entrypoint, "swarm_node_kernel")


class SkymapSensorArray(ForegroundKernel):
    id = "skymap-sens-arr"

    @staticmethod
    def entrypoint() -> Callable[[], NoReturn]:
        from kernels.skymap.sensor_array import main
        return main()


class SkymapServer(BackgroundKernel):
    id = "skymap-serv"

    def __init__(self):
        skymap_server = importlib.import_module("kernels.skymap.server")
        entrypoint = getattr(skymap_server, "main")
        self.d = Daemon(entrypoint, "skymap_server")



_kernels: dict[str, Type[BackgroundKernel] | Type[ForegroundKernel]] = {
    k.id: k for k in [December, SkymapSensorArray, SkymapServer]
}


def kernel_init(kernel_env_var="SWARM_NODE_KERNEL"):
    if kernel_env_var not in os.environ:
        logging.critical(
            f"SWARM_NODE_KERNEL must be set. Supported kernels: {','.join(_kernels.keys())}"
        )
        sys.exit(2)
    kernel_id = os.environ[kernel_env_var]
    if kernel_id not in _kernels:
        logging.critical(f"Unknown kernel: {kernel_id}, exiting.")
        sys.exit(2)

    kernel = _kernels[kernel_id]()
    if isinstance(kernel, ForegroundKernel):
        run_forever = kernel.entrypoint()
        run_forever()
        raise RuntimeError("Foreground Kernel exited")
    elif isinstance(kernel, BackgroundKernel):
        proc_gov = Thread(
            target=kernel_governor, name="kernel_gov", daemon=True, args=(kernel,)
        )
        proc_gov.start()
        return kernel


def kernel_governor(kernel: BackgroundKernel):
    while True:
        logging.debug("Checking processes")
        try:
            kernel.d.restart_if_failed()
        except Exception as e:
            # If this has failed, the program is toast and should be completely restarted by something like systemd
            logging.exception(e)
            logging.critical("Process governor failed, exiting.")
            sys.exit(7)
        time.sleep(1)
