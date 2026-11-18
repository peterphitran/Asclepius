import ctypes
import sys
import time
from dataclasses import dataclass
from typing import Literal

from asclepius.domain import AppError

ClockSource = Literal["linux-boottime-v1", "windows-gettickcount64-v1"]


@dataclass(frozen=True)
class Tick:
    source: ClockSource
    ns: int


class ElapsedClock:
    def __init__(self) -> None:
        self._windows_tick = None
        if sys.platform == "win32":
            self._windows_tick = ctypes.WinDLL("kernel32", use_last_error=True).GetTickCount64
            self._windows_tick.argtypes = []
            self._windows_tick.restype = ctypes.c_ulonglong

    def sample(self) -> Tick:
        if self._windows_tick is not None:
            return Tick("windows-gettickcount64-v1", self._windows_tick() * 1_000_000)
        if sys.platform == "linux" and hasattr(time, "CLOCK_BOOTTIME"):
            return Tick("linux-boottime-v1", time.clock_gettime_ns(time.CLOCK_BOOTTIME))
        raise AppError("clock_unavailable", "No supported elapsed clock is available.")

    def ns(self) -> int:
        return self.sample().ns


elapsed_clock = ElapsedClock()
