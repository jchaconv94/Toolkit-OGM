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
    before_exit: Callable[[], None] | None = None,
) -> threading.Thread:
    """Guarantee that the old process releases installation files promptly.

    `before_exit` corre justo antes de terminar (por ejemplo, cerrar la ventana congelada);
    si falla, el proceso termina igual.
    """

    delay = max(0.0, float(delay_seconds))

    def _force_exit() -> None:
        wait(delay)
        if before_exit is not None:
            try:
                before_exit()
            except Exception:
                pass
        exit_process(exit_code)

    thread = threading.Thread(
        target=_force_exit,
        daemon=True,
        name="ToolkitUpdateExitWatchdog",
    )
    thread.start()
    return thread
