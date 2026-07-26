from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Literal


DEFAULT_RUN_TIMEOUT_SECONDS = 900
MIN_RUN_TIMEOUT_SECONDS = 1
MAX_RUN_TIMEOUT_SECONDS = 3600

StopReason = Literal["cancelled", "timed_out"]


def validate_timeout_seconds(value: object, *, default: int = DEFAULT_RUN_TIMEOUT_SECONDS) -> int:
    timeout = default if value is None else value
    if type(timeout) is not int or not MIN_RUN_TIMEOUT_SECONDS <= timeout <= MAX_RUN_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be an integer from 1 to 3600.")
    return timeout


@dataclass
class RunControl:
    deadline: float | None = None
    clock: Callable[[], float] = time.monotonic
    cancel_probe: Callable[[], bool] | None = None
    _cancelled: Event = field(default_factory=Event, init=False, repr=False)
    _cancel_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @classmethod
    def with_timeout(
        cls,
        timeout_seconds: object = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        cancel_probe: Callable[[], bool] | None = None,
    ) -> "RunControl":
        timeout = validate_timeout_seconds(timeout_seconds)
        return cls(deadline=clock() + timeout, clock=clock, cancel_probe=cancel_probe)

    def request_cancel(self) -> bool:
        with self._cancel_lock:
            if self._cancelled.is_set():
                return False
            self._cancelled.set()
            return True

    def stop_reason(self) -> StopReason | None:
        if self._cancelled.is_set():
            return "cancelled"
        if self.cancel_probe is not None and self.cancel_probe():
            self.request_cancel()
            return "cancelled"
        if self.deadline is not None and self.clock() >= self.deadline:
            return "timed_out"
        return None
