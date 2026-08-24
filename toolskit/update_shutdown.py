import os
import threading
import time
from collections.abc import Callable


def arm_update_exit_watchdog(
    *,
    delay_seconds: float = 3.0,
    exit_code: int = 0,
    exit_process: Callable[[int], None] = os._exit,
    wait: Callable[[float], None] = time.sleep,
) -> threading.Thread:
    """Guarantee that the old process releases installation files promptly."""

    delay = max(0.0, float(delay_seconds))

    def _force_exit() -> None:
        wait(delay)
        exit_process(exit_code)

    thread = threading.Thread(
        target=_force_exit,
        daemon=True,
        name="ToolkitUpdateExitWatchdog",
    )
    thread.start()
    return thread
