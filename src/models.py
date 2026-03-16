"""数据模型：MessageDTO、ContentType、SenderAttr。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    VOICE = "voice"
    LINK = "link"
    CARD = "card"
    MINI_PROGRAM = "mini_program"
    VIDEO_ACCOUNT = "video_account"
    LOCATION = "location"
    SYSTEM = "system"
    TIME_SEPARATOR = "time_separator"
    TICKLE = "tickle"
    QUOTE = "quote"
    OTHER = "other"


class SenderAttr(str, Enum):
    SELF = "self"
    FRIEND = "friend"
    SYSTEM = "system"


@dataclass
class MessageDTO:
    chat_name: str
    chat_type: str
    sender: str
    sender_attr: SenderAttr
    content_type: ContentType
    content: str
    extra: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    message_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    raw_info: Optional[Dict[str, Any]] = None
    id: Optional[int] = None
