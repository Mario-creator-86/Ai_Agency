"""Windows RAM guard for this application's Comfy jobs, never another client's job."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

GIB = 1024**3
MIN_START_BYTES = 8 * GIB
MIN_RUNNING_BYTES = 3 * GIB
logger = logging.getLogger("studio.local_media")


def available_memory() -> int | None:
    if sys.platform != "win32":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total_phys",
                "available_phys",
                "total_page",
                "available_page",
                "total_virtual",
                "available_virtual",
                "extended",
            )
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return int(status.available_phys)
    return None


def watch_job(
    task_id: str, read: Callable[[], dict], interrupt: Callable[[], Any], timeout: float
) -> None:
    def run() -> None:
        consecutive = 0
        started = time.monotonic()
        next_check = started + 5
        while time.monotonic() - started < timeout:
            free = available_memory()
            consecutive = consecutive + 1 if free is not None and free < MIN_RUNNING_BYTES else 0
            if consecutive >= 3:
                try:
                    interrupt()
                    logger.warning("local_job_interrupted_low_ram", extra={"task_id": task_id})
                except Exception:  # noqa: BLE001 - guard logs, never crashes the server
                    logger.exception("local_ram_interrupt_failed")
                return
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + 5
                try:
                    entry = read().get(task_id, {})
                    status = entry.get("status", {})
                    if status.get("completed") or status.get("status_str") == "error":
                        return
                except Exception:  # noqa: BLE001 - temporary disconnect must not end guard
                    pass
            time.sleep(0.5)

    threading.Thread(target=run, daemon=True, name=f"comfy-ram-{task_id[:8]}").start()
