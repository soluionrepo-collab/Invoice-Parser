import logging
import os
from datetime import datetime

def setup_logger(name: str | None = None, level: int = logging.DEBUG):
    """
    Set up and return a configured logger.

    Args:
        name (str | None): Logger name (typically use __name__). If None, the root logger is used.
        level (int): Logging level (default: logging.DEBUG).

    Returns:
        logging.Logger: Configured logger instance with console + file handlers.
    """
    # Ensure log directory exists
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    # Create a logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # File handler (daily rolling file)
    log_file = os.path.join(log_dir, f"api_{datetime.now().strftime('%Y-%m-%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Avoid duplicate handlers
    if not logger.handlers:
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger

logger = setup_logger(__name__)
