
"""
Logger central pentru aplicație.
Folosim logging standard Python, cu format clar și niveluri.
"""

import logging
import sys


def get_logger(name: str = "dm-agent") -> logging.Logger:
    """
    Returnează un logger configurat pentru aplicație.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


# Exemplu instanță globală
logger = get_logger()