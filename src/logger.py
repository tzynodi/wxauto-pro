"""日志模块：使用 logging 标准库命名空间机制，与 wxauto 内置日志协调。"""

import logging
import os
from datetime import datetime


def setup_logging(level: str = "INFO", log_file: str = "") -> None:
    """初始化日志。

    配置 wxauto_pro.* 命名空间供本项目使用，
    同时管理 wxauto 命名空间的输出级别。

    Args:
        level: 日志级别，如 "DEBUG", "INFO", "WARNING", "ERROR"。
        log_file: 日志文件路径，为空则仅输出到控制台。若提供路径，每次启动会生成带时间戳的新文件（便于重启后排查）。
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
    )

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 配置 wxauto_pro 命名空间
    pro_logger = logging.getLogger("wxauto_pro")
    pro_logger.setLevel(log_level)
    if not pro_logger.handlers:
        pro_logger.addHandler(console_handler)

    # 配置 wxauto 命名空间（wxauto 内部可能已添加 handler）
    wx_logger = logging.getLogger("wxauto")
    wx_logger.setLevel(log_level)

    # 文件 handler（可选）：每次启动新文件，文件名带启动时间戳
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        base, ext = os.path.splitext(log_file)
        run_log_file = f"{base}_{datetime.now():%Y%m%d_%H%M%S}{ext}"
        file_handler = logging.FileHandler(run_log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        pro_logger.addHandler(file_handler)
        wx_logger.addHandler(file_handler)
        pro_logger.info("本次运行日志文件: %s", run_log_file)

    # 抑制第三方库的低级别日志
    for name in ("asyncio", "comtypes", "urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.WARNING)
