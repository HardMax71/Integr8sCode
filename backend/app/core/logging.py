import logging
from pythonjsonlogger import jsonlogger


def setup_logger():
    logger = logging.getLogger("integr8scode")
    logger.handlers.clear()

    console_handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

    return logger


logger = setup_logger()
