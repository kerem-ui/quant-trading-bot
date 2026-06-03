"""Lightweight logging helper.

A single place to configure logging so modules don't each call
``logging.basicConfig``. Research code only - no remote handlers.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str = "quantbot", level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger. Idempotent."""
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root = logging.getLogger("quantbot")
        root.addHandler(handler)
        root.setLevel(level)
        root.propagate = False
        _CONFIGURED = True
    logger = logging.getLogger(name if name.startswith("quantbot") else f"quantbot.{name}")
    logger.setLevel(level)
    return logger
