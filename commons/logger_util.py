"""日志工具 (参考 api_test_frame/commons/logger_util.py), 基于 colorlog。"""
import logging
import os
from logging.handlers import RotatingFileHandler

try:
    import colorlog
    _HAS_COLORLOG = True
except ImportError:  # pragma: no cover
    _HAS_COLORLOG = False

from commons.yaml_util import get_object_path, read_config

_LOG_DIR = os.path.join(get_object_path(), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")


def _build_logger():
    logger = logging.getLogger("live_auction_qa")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    config = read_config("LOG") or {}
    level = str(config.get("log_level", "info")).upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    color_console_fmt = str(config.get(
        "console_log_format",
        "%(log_color)s[%(levelname)s]-[%(asctime)s]-%(message)s",
    ))
    file_fmt = str(config.get(
        "file_log_format",
        "[%(levelname)s]-[%(asctime)s]-%(message)s",
    ))
    console_fmt = color_console_fmt if _HAS_COLORLOG else color_console_fmt.replace("%(log_color)s", "")

    sh = logging.StreamHandler()
    if _HAS_COLORLOG:
        sh.setFormatter(colorlog.ColoredFormatter(console_fmt))
    else:
        sh.setFormatter(logging.Formatter(file_fmt))
    logger.addHandler(sh)

    try:
        fh = RotatingFileHandler(
            _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        # 日志文件被占用或当前运行环境只读时，控制台日志仍应允许测试启动。
        pass
    else:
        fh.setFormatter(logging.Formatter(file_fmt))
        logger.addHandler(fh)
    return logger


_logger = _build_logger()


def info_log(message):
    _logger.info(message)
