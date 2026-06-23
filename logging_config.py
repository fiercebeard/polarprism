"""Standardized error logging setup for PolarPrism.

This module owns the configuration of the ``polarprism`` logger — the single
entry point for all application errors. Call :func:`setup_logging` once, early
in startup (before any other module logs).

Design:

- **Two handlers** — a ``StreamHandler`` to stderr (developer visibility in
  the terminal) and a ``RotatingFileHandler`` to ``<error_log_dir>/error.log``
  (persistent record for post-mortem). Both share one formatter.
- **Rotation** — 1 MiB per file, 3 backups kept. Prevents the unbounded growth
  of the old bespoke append-writers.
- **Per-user location** — defaults to ``~/.local/share/polarprism/`` (next to
  ``state.json``), so the error log never lands in the repo.
- **Idempotent** — safe to call more than once; re-attaches handlers cleanly.

Functional data logs (sailing logs, heading logs) are NOT routed through this
logger — only error/diagnostic events.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOGGER_NAME = "polarprism"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 1_048_576  # 1 MiB
BACKUP_COUNT = 3


def setup_logging(level: int = logging.INFO, error_log_dir: str | None = None) -> None:
    """Configure the ``polarprism`` logger with stderr + rotating-file handlers.

    Safe to call once at startup. If the log directory cannot be created or
    written, the file handler is skipped (stderr-only) so startup never fails
    on a logging problem.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    # Clear any prior handlers so repeated calls don't duplicate output.
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    formatter = logging.Formatter(LOG_FORMAT)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    if error_log_dir is None:
        error_log_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "polarprism")

    try:
        os.makedirs(error_log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(error_log_dir, "error.log"),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # Can't write the file — keep stderr-only. Log once to stderr so it's
        # visible, but don't raise (logging must never break the app).
        logger.warning(
            "could not create error log dir %s; falling back to stderr-only",
            error_log_dir,
            exc_info=False,
        )


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """Return the named logger under the polarprism namespace."""
    if name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
