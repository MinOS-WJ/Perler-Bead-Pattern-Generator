from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from perler_pattern.paths import application_data_directory


def configure_logging() -> logging.Logger:
    log_directory = application_data_directory() / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_directory / "application.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=14,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(existing, RotatingFileHandler) for existing in root.handlers):
        root.addHandler(handler)
    logger = logging.getLogger("perler_pattern")

    def report_unhandled(error_type, error, traceback_object) -> None:
        logger.critical("Unhandled exception", exc_info=(error_type, error, traceback_object))
        sys.__excepthook__(error_type, error, traceback_object)

    sys.excepthook = report_unhandled
    return logger
