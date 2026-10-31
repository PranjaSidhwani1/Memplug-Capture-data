"""Send memplug logs to stderr so they show up in the deploy output."""

from __future__ import annotations

import logging


def configure() -> None:
    logger = logging.getLogger("memplug")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
