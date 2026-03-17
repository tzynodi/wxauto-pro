"""应用逻辑：App 类与消息回调。入口为项目根目录的 main.py。"""

import logging
import traceback
from typing import Any

from .config import AppConfig
from .logger import setup_logging
from .message_adapter import MessageAdapter
from .models import ContentType
from .repository import SQLiteMessageRepository
from .wx_facade import WxFacade

logger = logging.getLogger("wxauto_pro.app")


class App:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

        # 初始化日志
        setup_logging(self.config.log_level, self.config.log_file)

        # 初始化数据库
        self.repo = SQLiteMessageRepository(self.config.db_path)

        # 初始化消息适配器
        self.adapter = MessageAdapter(
            save_dir=self.config.download_dir,
            voice_to_text=self.config.voice_to_text,
            voice_to_text_timeout_seconds=self.config.voice_to_text_timeout_seconds,
            repo=self.repo,
        )

        # 初始化 WeChat
        self.wx = WxFacade()

    def start(self) -> None:
        """注册所有监听并启动主循环。"""
        if not self.config.listen_chats:
            logger.warning("监听列表为空，请在 config 中配置 listen_chats")
            return

        for nickname in self.config.listen_chats:
            self.wx.add_listen_chat(nickname, self._on_message)

        logger.info(
            "已注册 %d 个监听，启动 KeepRunning...",
            len(self.config.listen_chats),
        )
        self.wx.keep_running()

    def _on_message(self, msg: Any, chat_or_name: Any) -> None:
        """消息回调：适配 → 过滤 → 去重 → 入库。wxauto 传入的第二个参数为 Chat 对象，需取 .who 作为聊天名。"""
        chat_name = (
            chat_or_name.who
            if hasattr(chat_or_name, "who")
            else str(chat_or_name)
        )
        try:
            # 检测记录：在任何处理之前立即写入明细，用于比对是否漏消息
            self.repo.log_detect(chat_name, msg)

            dto = self.adapter.adapt(msg, chat_name)
            if dto is None:
                return

            # 按配置过滤系统类消息
            if self._should_skip(dto.content_type):
                return

            # 去重
            if self.repo.exists_by_fingerprint(
                dto.fingerprint, self.config.dedup_window_hours
            ):
                content_preview = (dto.content or "")[:40]
                if len(dto.content or "") > 40:
                    content_preview += "..."
                logger.info(
                    "消息去重跳过: chat=%s, type=%s, fingerprint=%s, dedup_window_hours=%s, content_preview=%s",
                    chat_name,
                    dto.content_type.value,
                    dto.fingerprint,
                    self.config.dedup_window_hours,
                    content_preview or "(空)",
                )
                return

            # 入库
            self.repo.save(dto)

        except Exception:
            logger.error(
                "消息处理异常: chat=%s\n%s",
                chat_name,
                traceback.format_exc(),
            )

    def _should_skip(self, content_type: ContentType) -> bool:
        if (
            content_type == ContentType.SYSTEM
            and not self.config.store_system_messages
        ):
            return True
        if (
            content_type == ContentType.TIME_SEPARATOR
            and not self.config.store_time_separators
        ):
            return True
        if (
            content_type == ContentType.TICKLE
            and not self.config.store_tickle_messages
        ):
            return True
        return False
