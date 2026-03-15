"""消息适配层：wxauto Message → MessageDTO。

职责：
- 类型识别（按 msg.attr / msg.type / content 正则）
- 媒体下载（image / video / file）
- 语音转文字（可选）
- 链接 / 位置识别
- fingerprint 生成
- message_time 维护（来自最近 TimeMessage）
"""

import hashlib
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import ContentType, MessageDTO, SenderAttr

logger = logging.getLogger("wxauto_pro.adapter")

# 链接正则
URL_PATTERN = re.compile(r"https?://[^\s<>\"{}|\\^`\[\]]+", re.IGNORECASE)

# 文件名/文件夹名非法字符（Windows），替换为下划线
_FILENAME_SAFE_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_dirname(name: str, max_len: int = 80) -> str:
    """将聊天名转为可作目录名的字符串。"""
    s = _FILENAME_SAFE_RE.sub("_", (name or "unknown").strip())
    return s[:max_len] if len(s) > max_len else s or "unknown"

# 位置正则（微信 UI 中位置消息的常见格式）
LOCATION_PATTERN = re.compile(r"^\[位置\](.+)$|^位置：(.+)$")


class MessageAdapter:
    def __init__(
        self,
        save_dir: str,
        voice_to_text: bool = True,
        voice_to_text_timeout_seconds: int = 60,
    ):
        self._save_dir = save_dir
        self._voice_to_text = voice_to_text
        self._voice_to_text_timeout_seconds = voice_to_text_timeout_seconds
        # chat_name → 最近 TimeMessage 的 datetime
        self._last_time: Dict[str, Optional[datetime]] = {}

        Path(self._save_dir).mkdir(parents=True, exist_ok=True)

    def _get_chat_save_info(self, msg: Any, chat_name: str) -> Tuple[Path, str]:
        """按 群/人 分类的保存目录与相对路径前缀。

        Returns:
            (绝对目录 Path, 相对前缀 str，如 "群/群名" 或 "人/好友名")
        """
        chat_type = ""
        try:
            info = getattr(msg, "chat_info", None)
            if callable(info):
                res = info()
                if isinstance(res, dict):
                    chat_type = res.get("chat_type", res.get("type", "")) or ""
        except Exception:
            pass
        category = "群" if chat_type == "group" else "人"
        safe_name = _sanitize_dirname(chat_name)
        root = Path(self._save_dir)
        abs_dir = root / category / safe_name
        rel_prefix = f"{category}/{safe_name}"
        return abs_dir, rel_prefix

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def adapt(self, msg: Any, chat_name: str) -> Optional[MessageDTO]:
        """将 wxauto Message 转为 MessageDTO。"""
        msg_type = getattr(msg, "type", "?")
        msg_attr = getattr(msg, "attr", "?")
        content_preview = str(getattr(msg, "content", ""))[:80]
        logger.debug(
            "收到原始消息: type=%s, attr=%s, content_preview=%s",
            msg_type,
            msg_attr,
            content_preview,
        )

        attr = getattr(msg, "attr", "other")

        # 系统类消息（按 attr 判断）
        if attr == "time":
            return self._adapt_time(msg, chat_name)
        if attr == "tickle":
            return self._adapt_tickle(msg, chat_name)
        if attr == "system":
            return self._adapt_system(msg, chat_name)

        # 用户消息（friend / self / human）
        return self._adapt_user_message(msg, chat_name, attr)

    # ------------------------------------------------------------------
    # 系统类消息
    # ------------------------------------------------------------------

    def _adapt_time(self, msg: Any, chat_name: str) -> MessageDTO:
        logger.debug("类型分支: time_separator, attr=%s", msg.attr)

        time_value = getattr(msg, "time", None)
        if time_value:
            self._last_time[chat_name] = time_value

        extra: Dict[str, Any] = {}
        if time_value:
            extra["time"] = (
                time_value.isoformat()
                if hasattr(time_value, "isoformat")
                else str(time_value)
            )

        dto = self._build_dto(
            msg=msg,
            chat_name=chat_name,
            content_type=ContentType.TIME_SEPARATOR,
            sender_attr=SenderAttr.SYSTEM,
            content=getattr(msg, "content", ""),
            extra=extra,
        )
        logger.info(
            "消息识别完成: chat=%s, type=time_separator, fingerprint=%s",
            chat_name,
            dto.fingerprint[:16],
        )
        return dto

    def _adapt_tickle(self, msg: Any, chat_name: str) -> MessageDTO:
        logger.debug("类型分支: tickle, attr=%s", msg.attr)

        tickle_list = getattr(msg, "tickle_list", [])
        extra = {"tickle_list": tickle_list}

        dto = self._build_dto(
            msg=msg,
            chat_name=chat_name,
            content_type=ContentType.TICKLE,
            sender_attr=SenderAttr.SYSTEM,
            content=getattr(msg, "content", ""),
            extra=extra,
        )
        logger.info(
            "消息识别完成: chat=%s, type=tickle, fingerprint=%s",
            chat_name,
            dto.fingerprint[:16],
        )
        return dto

    def _adapt_system(self, msg: Any, chat_name: str) -> MessageDTO:
        logger.debug("类型分支: system, attr=%s", msg.attr)

        dto = self._build_dto(
            msg=msg,
            chat_name=chat_name,
            content_type=ContentType.SYSTEM,
            sender_attr=SenderAttr.SYSTEM,
            content=getattr(msg, "content", ""),
            extra={},
        )
        logger.info(
            "消息识别完成: chat=%s, type=system, fingerprint=%s",
            chat_name,
            dto.fingerprint[:16],
        )
        return dto

    # ------------------------------------------------------------------
    # 用户消息
    # ------------------------------------------------------------------

    def _adapt_user_message(
        self, msg: Any, chat_name: str, attr: str
    ) -> Optional[MessageDTO]:
        sender_attr = SenderAttr.SELF if attr == "self" else SenderAttr.FRIEND
        msg_type = getattr(msg, "type", "other")

        if msg_type == "text":
            return self._adapt_text(msg, chat_name, sender_attr)
        if msg_type == "image":
            return self._adapt_image(msg, chat_name, sender_attr)
        if msg_type == "video":
            return self._adapt_video(msg, chat_name, sender_attr)
        if msg_type == "file":
            return self._adapt_file(msg, chat_name, sender_attr)
        if msg_type == "voice":
            return self._adapt_voice(msg, chat_name, sender_attr)
        return self._adapt_other(msg, chat_name, sender_attr)

    def _adapt_text(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        content = getattr(msg, "content", "")

        # 优先检测位置
        loc = LOCATION_PATTERN.match(content)
        if loc:
            logger.debug("类型分支: location, 来源: content regex")
            address = loc.group(1) or loc.group(2)
            extra = {"address": address, "lat": None, "lng": None}
            return self._finish(
                msg, chat_name, ContentType.LOCATION, sender_attr, content, extra
            )

        # 检测链接
        url = URL_PATTERN.search(content)
        if url:
            logger.debug("类型分支: link, 来源: content regex")
            extra = {"url": url.group(0), "title": content}
            return self._finish(
                msg, chat_name, ContentType.LINK, sender_attr, content, extra
            )

        # 纯文本
        logger.debug("类型分支: text, 来源: msg.type")
        return self._finish(
            msg, chat_name, ContentType.TEXT, sender_attr, content, {}
        )

    def _adapt_image(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        logger.debug("类型分支: image, 来源: msg.type")
        extra = self._download_media(msg, chat_name)
        return self._finish(
            msg,
            chat_name,
            ContentType.IMAGE,
            sender_attr,
            getattr(msg, "content", "[图片]"),
            extra,
        )

    def _adapt_video(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        logger.debug("类型分支: video, 来源: msg.type")
        extra = self._download_media(msg, chat_name)
        return self._finish(
            msg,
            chat_name,
            ContentType.VIDEO,
            sender_attr,
            getattr(msg, "content", "[视频]"),
            extra,
        )

    def _adapt_file(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        logger.info("类型分支: file，开始下载 filename=%s", getattr(msg, "filename", ""))

        filename = getattr(msg, "filename", "")
        filesize = getattr(msg, "filesize", "")
        extra: Dict[str, Any] = {"filename": filename, "filesize": filesize}

        save_dir, rel_prefix = self._get_chat_save_info(msg, chat_name)
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            path = msg.download(dir_path=str(save_dir))
            if getattr(path, "is_success", True) is False:
                extra["path"] = None
                extra["download_status"] = "failed"
                extra["download_error"] = getattr(path, "message", str(path))
            else:
                path = Path(path) if not isinstance(path, Path) else path
                extra["path"] = f"{rel_prefix}/{path.name}"
                extra["download_status"] = "success"
                logger.debug("文件下载成功: %s -> %s", path, extra["path"])
        except Exception as e:
            extra["path"] = None
            extra["download_status"] = "failed"
            extra["download_error"] = str(e)
            logger.warning("文件下载失败: %s", e)

        return self._finish(
            msg,
            chat_name,
            ContentType.FILE,
            sender_attr,
            filename or getattr(msg, "content", "[文件]"),
            extra,
        )

    def _adapt_voice(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        logger.debug("类型分支: voice, 来源: msg.type")

        content = getattr(msg, "content", "[语音]")
        extra: Dict[str, Any] = {}

        if self._voice_to_text:
            result_holder: list = []

            def _run_to_text() -> None:
                try:
                    result_holder.append(msg.to_text())
                except Exception as e:
                    result_holder.append(e)

            timeout = self._voice_to_text_timeout_seconds
            thread = threading.Thread(target=_run_to_text, daemon=True)
            thread.start()
            thread.join(timeout=timeout)

            if not result_holder:
                extra["voice_to_text_status"] = "timeout"
                logger.warning(
                    "语音转文字超时(%ds)，放弃等待，避免阻塞后续消息",
                    timeout,
                )
            else:
                try:
                    result = result_holder[0]
                    if isinstance(result, Exception):
                        raise result
                    # to_text() 返回 str 或 WxResponse
                    if isinstance(result, str):
                        content = result
                        extra["voice_text"] = result
                    elif hasattr(result, "is_success") and result.is_success:
                        text = result.get("data", content)
                        content = str(text)
                        extra["voice_text"] = content
                    else:
                        extra["voice_to_text_status"] = "failed"
                        logger.warning("语音转文字失败")
                except Exception as e:
                    extra["voice_to_text_status"] = "failed"
                    extra["voice_to_text_error"] = str(e)
                    logger.warning("语音转文字异常: %s", e)

        return self._finish(
            msg, chat_name, ContentType.VOICE, sender_attr, content, extra
        )

    def _adapt_other(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        logger.debug(
            "类型分支: other, 来源: msg.type=%s", getattr(msg, "type", "?")
        )
        return self._finish(
            msg,
            chat_name,
            ContentType.OTHER,
            sender_attr,
            getattr(msg, "content", ""),
            {},
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _finish(
        self,
        msg: Any,
        chat_name: str,
        content_type: ContentType,
        sender_attr: SenderAttr,
        content: str,
        extra: Dict[str, Any],
    ) -> MessageDTO:
        """构建 DTO 并打 INFO 日志。"""
        dto = self._build_dto(
            msg, chat_name, content_type, sender_attr, content, extra
        )
        extra_summary = (
            f"download_status={extra.get('download_status')}"
            if "download_status" in extra
            else f"extra_keys={list(extra.keys())}" if extra else "extra={}"
        )
        logger.info(
            "消息识别完成: chat=%s, type=%s, %s, fingerprint=%s",
            chat_name,
            content_type.value,
            extra_summary,
            dto.fingerprint[:16],
        )
        return dto

    def _download_media(self, msg: Any, chat_name: str) -> Dict[str, Any]:
        """下载图片/视频到 群/人 子目录，extra.path 存相对路径。"""
        extra: Dict[str, Any] = {}
        save_dir, rel_prefix = self._get_chat_save_info(msg, chat_name)
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            path = msg.download(dir_path=str(save_dir))
            if getattr(path, "is_success", True) is False:
                extra["path"] = None
                extra["download_status"] = "failed"
                extra["download_error"] = getattr(path, "message", str(path))
                logger.warning(
                    "媒体下载失败: chat=%s, type=%s, error=%s",
                    chat_name,
                    getattr(msg, "type", "?"),
                    extra["download_error"],
                )
            else:
                path = Path(path) if not isinstance(path, Path) else path
                extra["path"] = f"{rel_prefix}/{path.name}"
                extra["download_status"] = "success"
                logger.debug("媒体下载成功: %s -> %s", path, extra["path"])
        except Exception as e:
            extra["path"] = None
            extra["download_status"] = "failed"
            extra["download_error"] = str(e)
            logger.warning("媒体下载失败: %s", e)
        return extra

    def _build_dto(
        self,
        msg: Any,
        chat_name: str,
        content_type: ContentType,
        sender_attr: SenderAttr,
        content: str,
        extra: Dict[str, Any],
    ) -> MessageDTO:
        sender = getattr(msg, "sender", sender_attr.value)

        # chat_type
        chat_type = ""
        try:
            info = msg.chat_info()
            if isinstance(info, dict):
                chat_type = info.get("chat_type", info.get("type", ""))
        except Exception:
            pass

        # message_time
        message_time = self._last_time.get(chat_name)

        # fingerprint（含 message_time；图片/视频无 path 时用 msg.id 区分，避免 content 均为 [图片] 导致误去重）
        msg_id = None
        try:
            msg_id = getattr(msg, "id", None) or (
                getattr(getattr(msg, "control", None), "runtimeid", None)
            )
        except Exception:
            pass
        fingerprint = self._generate_fingerprint(
            chat_name, sender, content_type.value, content, extra, message_time, msg_id
        )

        # raw_info
        raw_info = None
        try:
            msg_info = getattr(msg, "info", None)
            if isinstance(msg_info, dict):
                raw_info = {
                    k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
                    for k, v in msg_info.items()
                }
        except Exception:
            pass

        return MessageDTO(
            chat_name=chat_name,
            chat_type=chat_type,
            sender=sender,
            sender_attr=sender_attr,
            content_type=content_type,
            content=content,
            extra=extra,
            fingerprint=fingerprint,
            message_time=message_time,
            raw_info=raw_info,
        )

    @staticmethod
    def _generate_fingerprint(
        chat_name: str,
        sender: str,
        content_type: str,
        content: str,
        extra: Dict[str, Any],
        message_time: Optional[datetime] = None,
        msg_id: Any = None,
    ) -> str:
        """生成内容指纹用于去重。

        对媒体消息，加入下载路径或文件名以区分不同文件。
        msg_id（控件 runtimeid）始终参与计算，确保同名文件多次发送不会被误去重。
        加入 message_time，同一内容在不同时间段视为不同消息，分别入库。
        """
        content_preview = content[:200] if content else ""

        extra_key = ""
        if content_type in ("image", "video", "file"):
            path = extra.get("path")
            filename = extra.get("filename")
            if path:
                extra_key = str(path)
            elif filename:
                extra_key = str(filename)

        id_key = str(msg_id) if msg_id is not None else ""
        time_key = message_time.isoformat() if message_time else ""
        raw = f"{chat_name}\x00{sender}\x00{content_type}\x00{content_preview}\x00{extra_key}\x00{id_key}\x00{time_key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
