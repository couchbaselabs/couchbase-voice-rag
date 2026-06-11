"""Centralised JSON logging setup.

Every log record passes through ``_RequestIDFilter`` which stamps the
active request id onto ``record.request_id``; ``pythonjsonlogger``
then emits one JSON object per line so Azure/Datadog/CloudWatch can
parse the stream without custom regexes.
"""

from __future__ import annotations

import logging
import os
import sys

from pythonjsonlogger.json import JsonFormatter

from middleware.request_id import request_id_var

_DEFAULT_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(message)s "
    "%(request_id)s %(pathname)s %(lineno)d"
)
_RENAME_FIELDS = {
    "asctime": "timestamp",
    "levelname": "level",
    "name": "logger",
}
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class _RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str | int | None = None) -> None:
    """Install a JSON handler on the root logger and silence duplicate handlers."""
    resolved_level = level or os.getenv("LOG_LEVEL", "INFO")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            _DEFAULT_FORMAT,
            rename_fields=_RENAME_FIELDS,
            timestamp=True,
        )
    )
    handler.addFilter(_RequestIDFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)

    # Let uvicorn's loggers flow through our handler instead of printing
    # plain-text lines via its default config.
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
