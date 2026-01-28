# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

import logging
from logging.handlers import RotatingFileHandler
import os

# Create a logger
SHORT_LOG_FORMAT = "[%(asctime)s - %(levelname)s] - %(name)s - %(message)s"
FULL_LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s (%(filename)s:%(lineno)d)"
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

logging.basicConfig(
    level=logging.INFO,
    format=SHORT_LOG_FORMAT,
    handlers=[
        RotatingFileHandler("logs.txt", maxBytes=5000000, backupCount=10),
        logging.StreamHandler()
    ]
)

logging.getLogger("pyrogram").setLevel(logging.WARNING)

def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)

# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
