"""数据库层：MessageRepository 抽象 + SQLite 实现。

线程安全：WAL 模式 + 写操作 Lock 序列化。
"""

import json
import logging
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from .models import ContentType, MessageDTO, SenderAttr

logger = logging.getLogger("wxauto_pro.repository")


class MessageRepository(ABC):
    @abstractmethod
    def save(self, dto: MessageDTO) -> int:
        ...

    @abstractmethod
    def exists_by_fingerprint(
        self, fingerprint: str, time_window_hours: int = 24
    ) -> bool:
        ...

    @abstractmethod
    def list_by_chat(
        self, chat_name: str, limit: int = 50
    ) -> List[MessageDTO]:
        ...

    @abstractmethod
    def find_quoted_message_id(
        self, chat_name: str, quoted_content: str, quoted_type: str
    ) -> Optional[int]:
        ...


class SQLiteMessageRepository(MessageRepository):
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()

        # 确保目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._conn = self._create_connection()
        self._create_table()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_name       TEXT    NOT NULL,
                chat_type       TEXT,
                sender          TEXT    NOT NULL,
                sender_attr     TEXT    NOT NULL,
                content_type    TEXT    NOT NULL,
                content         TEXT,
                extra           TEXT,
                fingerprint     TEXT    NOT NULL,
                message_time    TEXT,
                created_at      TEXT    NOT NULL,
                raw_info        TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_fingerprint_created
                ON messages (fingerprint, created_at);

            CREATE INDEX IF NOT EXISTS idx_chat_name
                ON messages (chat_name, created_at);

            CREATE TABLE IF NOT EXISTS detect_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_name       TEXT    NOT NULL,
                msg_type        TEXT,
                msg_attr        TEXT,
                sender          TEXT,
                content_preview TEXT,
                runtime_id      TEXT,
                detected_at     TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_detect_log_chat
                ON detect_log (chat_name, detected_at);
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, dto: MessageDTO) -> int:
        now = datetime.now()
        dto.created_at = now

        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO messages (
                    chat_name, chat_type, sender, sender_attr, content_type,
                    content, extra, fingerprint, message_time, created_at,
                    raw_info
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dto.chat_name,
                    dto.chat_type,
                    dto.sender,
                    dto.sender_attr.value,
                    dto.content_type.value,
                    dto.content,
                    json.dumps(dto.extra, ensure_ascii=False)
                    if dto.extra
                    else None,
                    dto.fingerprint,
                    (dto.message_time.isoformat() if hasattr(dto.message_time, "isoformat") else str(dto.message_time)) if dto.message_time else None,
                    now.isoformat(),
                    json.dumps(dto.raw_info, ensure_ascii=False)
                    if dto.raw_info
                    else None,
                ),
            )
            self._conn.commit()
            dto.id = cursor.lastrowid

        logger.info(
            "消息入库成功: id=%s, chat=%s, type=%s",
            dto.id,
            dto.chat_name,
            dto.content_type.value,
        )
        return dto.id

    def exists_by_fingerprint(
        self, fingerprint: str, time_window_hours: int = 24
    ) -> bool:
        cutoff = (
            datetime.now() - timedelta(hours=time_window_hours)
        ).isoformat()
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE fingerprint = ? AND created_at > ? LIMIT 1",
            (fingerprint, cutoff),
        ).fetchone()
        return row is not None

    def list_by_chat(
        self, chat_name: str, limit: int = 50
    ) -> List[MessageDTO]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE chat_name = ? ORDER BY created_at DESC LIMIT ?",
            (chat_name, limit),
        ).fetchall()
        return [self._row_to_dto(row) for row in rows]

    def find_quoted_message_id(
        self, chat_name: str, quoted_content: str, quoted_type: str
    ) -> Optional[int]:
        """在同一聊天中查找被引用的原始消息 ID（精确匹配）。"""
        exclude = "AND content_type NOT IN ('system', 'time_separator', 'quote')"

        # 精确匹配 content
        row = self._conn.execute(
            f"SELECT id FROM messages WHERE chat_name = ? AND content = ? {exclude} "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_name, quoted_content),
        ).fetchone()
        if row:
            return row["id"]

        # 在 extra 中搜索（如位置消息的地址文字）
        if quoted_content:
            row = self._conn.execute(
                f"SELECT id FROM messages WHERE chat_name = ? AND extra LIKE ? {exclude} "
                "ORDER BY created_at DESC LIMIT 1",
                (chat_name, f"%{quoted_content}%"),
            ).fetchone()
            if row:
                return row["id"]

        return None

    def log_detect(self, chat_name: str, msg) -> None:
        """检测到新消息时立即记录明细（在 adapt/filter/dedup 之前调用）。
        msg 为 wxauto 原始 Message 对象，仅读取已有属性，不做 UI 操作。"""
        now = datetime.now().isoformat()
        content = getattr(msg, "content", None) or ""
        preview = content[:80] if content else ""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO detect_log
                    (chat_name, msg_type, msg_attr, sender, content_preview, runtime_id, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_name,
                    getattr(msg, "type", None),
                    getattr(msg, "attr", None),
                    getattr(msg, "sender", None),
                    preview,
                    str(getattr(msg, "id", "")),
                    now,
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dto(row: sqlite3.Row) -> MessageDTO:
        return MessageDTO(
            id=row["id"],
            chat_name=row["chat_name"],
            chat_type=row["chat_type"] or "",
            sender=row["sender"],
            sender_attr=SenderAttr(row["sender_attr"]),
            content_type=ContentType(row["content_type"]),
            content=row["content"] or "",
            extra=json.loads(row["extra"]) if row["extra"] else {},
            fingerprint=row["fingerprint"],
            message_time=datetime.fromisoformat(row["message_time"])
            if row["message_time"]
            else None,
            created_at=datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None,
            raw_info=json.loads(row["raw_info"]) if row["raw_info"] else None,
        )
