import logging
import logging.handlers
import sys
from pathlib import Path

from config import config

_LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(config.log_level)
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    if config.log_dir:
        log_path = Path(config.log_dir) / "portal.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_path, when="midnight", backupCount=30
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").disabled = True

    # uvicorn's own startup/shutdown/reload messages (logged via "uvicorn"/"uvicorn.error")
    # keep their own handler, set up before this runs - just restyle it to match ours.
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error"):
        for handler in logging.getLogger(uvicorn_logger_name).handlers:
            handler.setFormatter(formatter)

    for noisy_logger in ("httpx", "kubernetes", "authlib"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)