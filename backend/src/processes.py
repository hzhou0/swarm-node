import logging
import os
import sys
import time
from threading import Thread

import msgspec
import psutil

import machine
from ipc import Daemon
from models import MachineState, MachineHTTPMutation, MachineHTTPEvent


class Processes(msgspec.Struct, frozen=True):
    machine: Daemon[MachineState, MachineHTTPMutation, MachineHTTPEvent]

    @classmethod
    def init(cls):
        global PROCESSES
        PROCESSES = cls(machine=Daemon(machine.main, "machine"))
        proc_gov = Thread(target=process_governor, name="proc_gov", daemon=True)
        proc_gov.start()


def process_governor():
    while True:
        logging.debug("Checking processes")
        try:
            for proc_name in msgspec.structs.fields(PROCESSES):
                getattr(PROCESSES, proc_name.name).restart_if_failed()
        except Exception as e:
            # If this has failed, the program is toast and should be completely restarted by something like systemd
            logging.exception(e)
            logging.critical("Process governor failed, exiting.")
            sys.exit(7)
        time.sleep(1)


# noinspection PyTypeChecker
PROCESSES: Processes = None
