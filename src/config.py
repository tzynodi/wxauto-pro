"""配置模块：监听列表、存储路径、日志、去重等。"""

import os
import sys
from dataclasses import dataclass, field
from typing import List


def _get_app_base_dir() -> str:
    """Return the directory that should hold runtime data."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class AppConfig:
    # 监听的聊天列表（群名或好友名）
    listen_chats: List[str] = field(default_factory=list)

    # 数据库路径
    db_path: str = os.path.join(_get_app_base_dir(), "data", "messages.db")

    # 下载根目录（图片/视频/文件）
    download_dir: str = os.path.join(_get_app_base_dir(), "downloads")

    # 日志级别
    log_level: str = "INFO"

    # 日志文件路径，为空则仅控制台输出
    log_file: str = ""

    # 去重时间窗口（小时）
    dedup_window_hours: int = 24

    # 系统消息是否入库
    store_system_messages: bool = True

    # 时间分隔消息是否入库
    store_time_separators: bool = True

    # 拍一拍消息是否入库
    store_tickle_messages: bool = True

    # 语音是否自动转文字
    voice_to_text: bool = True

    # 语音转文字最长等待时间（秒），超时则放弃转写、存为 [语音]，避免识别失败时无限阻塞监听
    voice_to_text_timeout_seconds: int = 20
