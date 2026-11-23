"""Logging setup with rotating files."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.paths import LOG_DIR


def setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "testhelper.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [file_handler, console]

    for noisy in ("httpx", "httpcore", "PIL", "websocket"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
