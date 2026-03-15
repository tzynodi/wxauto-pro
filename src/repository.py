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
from typing import List, Optional

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
                    dto.message_time.isoformat() if dto.message_time else None,
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
