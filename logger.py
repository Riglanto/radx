from datetime import datetime, timezone, time, timedelta
import logging


def create_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(
        datetime.now().strftime("_logs/%Y%m%d.log"),
        encoding="utf-8",
        mode="a",
    )
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d - $(name) %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
