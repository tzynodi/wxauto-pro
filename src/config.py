"""配置模块：监听列表、存储路径、日志、去重等。"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class AppConfig:
    # 监听的聊天列表（群名或好友名）
    listen_chats: List[str] = field(default_factory=list)

    # 数据库路径
    db_path: str = os.path.join(os.getcwd(), "data", "messages.db")

    # 下载根目录（图片/视频/文件）
    download_dir: str = os.path.join(os.getcwd(), "downloads")

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
