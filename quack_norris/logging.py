from loguru import logger
import sys


def log_only_warn():
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
