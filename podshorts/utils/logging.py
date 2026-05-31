from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)


def get_logger(name: str = "podshorts", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    return logger


def configure_root_logger(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[
            RichHandler(
                console=_console,
                show_time=True,
                show_path=False,
                markup=False,
                rich_tracebacks=True,
            )
        ],
        format="%(message)s",
    )
