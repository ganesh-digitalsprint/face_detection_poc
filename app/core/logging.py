"""Centralized application logging.

Use ``get_logger(__name__)`` everywhere instead of ``print()``. Call
``setup_logging()`` once at startup; repeated calls are safe and only update
the log level.
"""

from __future__ import annotations

import logging
import sys
import threading

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_HANDLER_NAME = "face_poc_console"
_lock = threading.Lock()
_configured = False

# Third-party loggers that are very chatty at INFO/DEBUG.
_NOISY_LOGGERS = ("tensorflow", "PIL", "matplotlib", "urllib3", "h5py")


def setup_logging(level: str | None = None) -> None:
    """Configure console logging for the whole application.

    Args:
        level: Optional log level name overriding ``settings.LOG_LEVEL``.

    Safe to call multiple times: the handler is installed only once, and later
    calls just update the level.
    """
    global _configured

    resolved_level = (level or settings.LOG_LEVEL).upper()
    numeric_level = logging.getLevelName(resolved_level)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    with _lock:
        root = logging.getLogger()
        root.setLevel(numeric_level)

        if not _configured:
            handler = logging.StreamHandler(sys.stdout)
            handler.set_name(_HANDLER_NAME)
            handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
            # Avoid duplicate output if something else already added our handler.
            if not any(h.get_name() == _HANDLER_NAME for h in root.handlers):
                root.addHandler(handler)

            for name in _NOISY_LOGGERS:
                logging.getLogger(name).setLevel(logging.WARNING)

            _configured = True

        for handler in root.handlers:
            if handler.get_name() == _HANDLER_NAME:
                handler.setLevel(numeric_level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (typically ``get_logger(__name__)``)."""
    return logging.getLogger(name)