import logging
from pathlib import Path

TRACE = logging.DEBUG - 1


def get_logger(name: str) -> logging.Logger:
    # If a file path was passed, prefix it to fall under the component logger
    if name.endswith('.py') or '\\' in name or '/' in name:
        name = f"custom_components.homgar.{Path(name).stem}"
    return logging.getLogger(name)
