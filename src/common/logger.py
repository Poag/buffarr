import logging

from common.logging_setup import setup_logging

# Set up logging once when this module is first imported.
setup_logging()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
