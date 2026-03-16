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
LOCATION_PATTERN = re.compile(r"^\[位置\](.*)$|^位置：(.+)$")

# 链接卡片正则（微信中分享链接/音乐/公众号等卡片消息）
LINK_CARD_PATTERN = re.compile(r"^\[(音乐|链接|公众号)\]$")
CONTACT_CARD_PATTERN = re.compile(r"^\[名片\]$")
VIDEO_ACCOUNT_PATTERN = re.compile(r"^\[视频号\]$")

# 引用消息正则（content 中包含 \n引用  的消息 : ）
QUOTE_PATTERN = re.compile(r"\n引用\s+的消息\s*:\s*")


class MessageAdapter:
    def __init__(
        self,
        save_dir: str,
        voice_to_text: bool = True,
        voice_to_text_timeout_seconds: int = 60,
        repo: Any = None,
    ):
        self._save_dir = save_dir
        self._voice_to_text = voice_to_text
        self._voice_to_text_timeout_seconds = voice_to_text_timeout_seconds
        self._repo = repo
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

        # 引用消息（必须在类型分发之前拦截，防止引用文件触发下载）
        content = getattr(msg, "content", "")
        if QUOTE_PATTERN.search(content):
            return self._adapt_quote(msg, chat_name, sender_attr)

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

    def _adapt_quote(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        """处理引用/回复消息。

        content 格式: "回复内容\n引用  的消息 : 被引用内容"
        对媒体类引用（图片/视频/文件），通过 UI 导航到原始消息下载媒体。
        """
        import time
        import wxauto.uiautomation as uia

        content = getattr(msg, "content", "")
        match = QUOTE_PATTERN.search(content)

        reply_content = content[: match.start()] if match else content
        quoted_raw = content[match.end() :] if match else ""

        logger.debug(
            "类型分支: quote, reply='%s', quoted_raw='%s'",
            reply_content[:50],
            quoted_raw[:50],
        )

        quoted_type = self._infer_quoted_type(quoted_raw)

        # 从控件树提取发送者和内容
        quoted_sender, quoted_content_from_tree, tree_type = self._extract_quote_info(
            msg, reply_content
        )
        quoted_content = quoted_content_from_tree or quoted_raw

        # 控件树检测到的类型优先级高于纯文本推断
        if quoted_type == "text" and tree_type:
            quoted_type = tree_type
            logger.debug("引用类型由控件树修正: %s", tree_type)

        # DB 辅助推断：控件树无法判断时，查 DB 中同聊天的匹配消息
        if quoted_type == "text" and quoted_content and self._repo:
            db_type = self._infer_type_from_db(chat_name, quoted_content)
            if db_type:
                quoted_type = db_type
                logger.debug("引用类型由DB修正: %s", db_type)

        extra: Dict[str, Any] = {
            "reply_content": reply_content,
            "quoted_sender": quoted_sender,
            "quoted_content": quoted_content,
            "quoted_type": quoted_type,
        }

        # 对媒体类引用，导航到原始消息下载
        if quoted_type in ("image", "video", "file"):
            media_extra = self._navigate_quote_and_download(
                msg, chat_name, quoted_type
            )
            extra.update(media_extra)

        return self._finish(
            msg, chat_name, ContentType.QUOTE, sender_attr, reply_content, extra
        )

    def _navigate_quote_and_download(
        self, msg: Any, chat_name: str, quoted_type: str
    ) -> Dict[str, Any]:
        """点击引用区中的媒体缩略图，通过预览窗口下载原始媒体。

        流程（图片）：
        1. 点击引用区中的图片缩略图 → 打开图片预览窗口
        2. 在预览窗口中右键 → 复制 → 从剪贴板获取文件
        3. 关闭预览窗口
        """
        import time

        extra: Dict[str, Any] = {}
        control = getattr(msg, "control", None)
        if not control:
            return extra

        try:
            # 1. 找到引用区中的可点击元素（图片缩略图 ButtonControl）
            quoted_pane = self._find_quoted_pane(control)
            if not quoted_pane:
                logger.debug("[quote dl] 未找到引用区控件")
                return extra

            # 在引用区中查找图片缩略图（ButtonControl，Name 为空）
            click_target = self._find_media_in_quoted_pane(
                quoted_pane, quoted_type
            )
            if not click_target:
                # fallback: 直接点击引用区中心
                click_target = quoted_pane

            # 点击前确保聊天窗口在前台
            self._ensure_foreground(control)

            logger.debug("[quote dl] 点击引用区媒体缩略图")
            click_target.Click()
            time.sleep(1)

            # 2. 检测预览窗口并下载（图片和视频都可能打开预览）
            if quoted_type in ("image", "video"):
                extra = self._download_from_preview_window(msg, chat_name)

        except Exception as e:
            extra["download_status"] = "failed"
            extra["download_error"] = str(e)
            logger.warning("[quote dl] 异常: %s", e)

        return extra

    @staticmethod
    def _ensure_foreground(control: Any) -> None:
        """将消息所在的聊天窗口拉到前台，确保后续点击操作生效。"""
        try:
            import win32gui
            # 从控件向上找到顶层窗口
            top = control
            if hasattr(top, "GetTopLevelControl"):
                top = top.GetTopLevelControl()
            hwnd = getattr(top, "NativeWindowHandle", 0)
            if hwnd:
                win32gui.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
                win32gui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)  # TOPMOST
                win32gui.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 3)  # NOTOPMOST
                logger.debug("[quote dl] 窗口已前置: hwnd=%s", hwnd)
        except Exception as e:
            logger.debug("[quote dl] 窗口前置失败: %s", e)

    @staticmethod
    def _find_quoted_pane(control: Any) -> Any:
        """找到引用区 PaneControl（递归搜索，兼容 self/friend 不同结构）。

        引用消息的气泡主体是一个 PaneControl，它有 >=2 个 PaneControl 子节点：
          - 第一个：回复区
          - 第二个：引用区 ← 要找的
        搜索最深层符合条件的 PaneControl，避免匹配到上层容器。
        """
        try:
            # dump 完整控件树帮助调试
            def _dump(ctrl, depth=0):
                if depth > 10:
                    return
                ctype = getattr(ctrl, "ControlTypeName", "?")
                name = getattr(ctrl, "Name", "")
                logger.debug(
                    "[quote tree] %s%s | Name='%s'",
                    "  " * depth, ctype, name,
                )
                for child in (ctrl.GetChildren() or []):
                    _dump(child, depth + 1)
            _dump(control)

            # 收集所有符合条件的 PaneControl（有 >=2 个 PaneControl 子节点）
            candidates: list = []

            def _find_all(ctrl, depth=0):
                if depth > 10:
                    return
                if ctrl.ControlTypeName == "PaneControl":
                    children = ctrl.GetChildren() or []
                    pane_children = [
                        c for c in children
                        if c.ControlTypeName == "PaneControl"
                    ]
                    if len(pane_children) >= 2:
                        candidates.append((ctrl, pane_children, depth))
                for child in (ctrl.GetChildren() or []):
                    _find_all(child, depth + 1)

            _find_all(control)

            if not candidates:
                return None

            def _has_quote_marker(pane) -> bool:
                """检查 PaneControl 子树中是否包含引用区标记（' : ' 文本）。"""
                try:
                    for child in (pane.GetChildren() or []):
                        if child.ControlTypeName == "TextControl":
                            name = getattr(child, "Name", "")
                            if " : " in name:
                                return True
                        if _has_quote_marker(child):
                            return True
                except Exception:
                    pass
                return False

            # 选第二个 PaneControl 子节点包含引用区标记（' : '）的候选
            for ctrl, pane_children, depth in candidates:
                if _has_quote_marker(pane_children[1]):
                    logger.debug(
                        "[quote dl] 找到引用区 PaneControl (depth=%d, candidates=%d, 匹配: quote marker)",
                        depth, len(candidates),
                    )
                    return pane_children[1]

            # fallback：取最浅层（最不容易选错）
            bubble_body, pane_children, depth = min(candidates, key=lambda x: x[2])
            logger.debug(
                "[quote dl] 找到引用区 PaneControl (depth=%d, candidates=%d, fallback: shallowest)",
                depth, len(candidates),
            )
            return pane_children[1]

        except Exception as e:
            logger.debug("[quote dl] 查找引用区异常: %s", e)
            return None

    @staticmethod
    def _find_media_in_quoted_pane(quoted_pane: Any, quoted_type: str) -> Any:
        """在引用区中找到媒体缩略图控件。

        图片引用的控件树：
          TextControl | '桔梗'
          TextControl | ' : '
          PaneControl
            ButtonControl ← 图片缩略图，点击打开预览
        """
        try:
            # 先 dump 引用区控件树，帮助调试
            def _dump(ctrl, depth=0):
                if depth > 6:
                    return
                ctype = getattr(ctrl, "ControlTypeName", "?")
                name = getattr(ctrl, "Name", "")
                logger.debug(
                    "[quote dl] 引用区控件: %s%s | Name='%s'",
                    "  " * depth, ctype, name,
                )
                for child in (ctrl.GetChildren() or []):
                    _dump(child, depth + 1)
            _dump(quoted_pane)

            # 收集所有 ButtonControl（不限制 Name）
            buttons: list = []

            def _find_buttons(ctrl, depth=0):
                if depth > 8:
                    return
                if ctrl.ControlTypeName == "ButtonControl":
                    buttons.append(ctrl)
                for child in (ctrl.GetChildren() or []):
                    _find_buttons(child, depth + 1)

            _find_buttons(quoted_pane)

            if buttons:
                # 优先选 Name 为空的（缩略图），否则取第一个
                btn = next((b for b in buttons if not getattr(b, "Name", "")), buttons[0])
                logger.debug(
                    "[quote dl] 找到媒体缩略图 ButtonControl (共%d个, Name='%s')",
                    len(buttons), getattr(btn, "Name", ""),
                )
                return btn

            logger.debug("[quote dl] 引用区未找到 ButtonControl")
            return None
        except Exception as e:
            logger.debug("[quote dl] 查找媒体缩略图异常: %s", e)
            return None

    def _download_from_preview_window(
        self, msg: Any, chat_name: str
    ) -> Dict[str, Any]:
        """从图片预览窗口下载图片。

        点击引用区图片缩略图后，微信打开图片预览窗口。
        在预览窗口中右键 → 复制 → 从剪贴板获取文件路径。
        """
        import time
        import wxauto.uiautomation as uia
        from wxauto.utils.win32 import ReadClipboardData, FindWindow

        extra: Dict[str, Any] = {}

        # 检测预览窗口
        preview_hwnd = None
        preview_classes = ["ImagePreviewWnd", "CefWebViewWnd", "MediaPreviewWnd"]
        for cls in preview_classes:
            hwnd = FindWindow(classname=cls, timeout=1)
            if hwnd:
                preview_hwnd = hwnd
                logger.debug("[quote dl] 检测到预览窗口: class=%s, hwnd=%s", cls, hwnd)
                break

        if not preview_hwnd:
            logger.debug("[quote dl] 未检测到预览窗口")
            extra["download_status"] = "no_preview"
            return extra

        try:
            # 获取预览窗口的控件
            from wxauto.uiautomation import ControlFromHandle
            preview_ctrl = ControlFromHandle(preview_hwnd)

            if not preview_ctrl:
                logger.debug("[quote dl] 无法获取预览窗口控件")
                extra["download_status"] = "no_preview_ctrl"
                return extra

            # 在预览窗口中心右键
            rect = preview_ctrl.BoundingRectangle
            sx = (rect.left + rect.right) // 2
            sy = (rect.top + rect.bottom) // 2

            logger.debug("[quote dl] 在预览窗口中右键: (%s, %s)", sx, sy)
            uia.RightClick(sx, sy)
            time.sleep(0.5)

            # 查找右键菜单并选择 "复制"
            from wxauto.utils.win32 import GetAllWindows
            menu_ctrl = None
            menu_list = [i for i in GetAllWindows() if 'CMenuWnd' in i]
            if menu_list:
                menu_ctrl = uia.ControlFromHandle(menu_list[0][0])

            if menu_ctrl:
                # 在菜单中查找 "复制" 选项并点击
                copy_clicked = False
                try:
                    list_ctrl = menu_ctrl.ListControl()
                    if list_ctrl:
                        for item in (list_ctrl.GetChildren() or []):
                            if item.Name == "复制":
                                item.Click()
                                copy_clicked = True
                                break
                except Exception:
                    pass

                if not copy_clicked:
                    # fallback: 按 ESC 关闭菜单
                    try:
                        menu_ctrl.SendKeys("{ESC}")
                    except Exception:
                        pass
                    extra["download_status"] = "menu_no_copy"
                    logger.debug("[quote dl] 右键菜单未找到复制选项")
                else:
                    time.sleep(0.5)
                    data = ReadClipboardData()
                    # ReadClipboardData 返回的 key 可能是 int 或 str
                    hdrop = data.get(15) or data.get('15') or data.get(str(15)) if data else None
                    if hdrop:
                        src_path = Path(hdrop[0])
                        save_dir, rel_prefix = self._get_chat_save_info(msg, chat_name)
                        save_dir.mkdir(parents=True, exist_ok=True)
                        dst_path = save_dir / src_path.name
                        # 文件已存在时加时间戳避免冲突
                        if dst_path.exists():
                            stem = src_path.stem
                            suffix = src_path.suffix
                            ts = datetime.now().strftime("%Y%m%d%H%M%S")
                            dst_path = save_dir / f"{stem}_{ts}{suffix}"
                        import shutil
                        shutil.copy2(str(src_path), str(dst_path))
                        extra["path"] = f"{rel_prefix}/{dst_path.name}"
                        extra["download_status"] = "success"
                        logger.debug("[quote dl] 媒体下载成功: %s", extra["path"])
                    else:
                        extra["download_status"] = "clipboard_empty"
                        logger.debug("[quote dl] 剪贴板无文件数据, keys=%s", list(data.keys()) if data else "None")
            else:
                extra["download_status"] = "menu_not_found"
                logger.debug("[quote dl] 未找到右键菜单窗口")

        except Exception as e:
            extra["download_status"] = "failed"
            extra["download_error"] = str(e)
            logger.warning("[quote dl] 预览窗口下载异常: %s", e)
        finally:
            # 关闭预览窗口
            try:
                import win32gui
                win32gui.PostMessage(preview_hwnd, 0x0010, 0, 0)  # WM_CLOSE
                time.sleep(0.3)
                logger.debug("[quote dl] 预览窗口已关闭")
            except Exception:
                pass

        return extra

    @staticmethod
    def _infer_quoted_type(quoted_raw: str) -> str:
        """根据被引用的原始内容推断其类型。"""
        quoted_raw = quoted_raw.strip()
        if quoted_raw == "[图片]":
            return "image"
        if quoted_raw == "[视频]":
            return "video"
        if quoted_raw == "[语音]":
            return "voice"
        if quoted_raw in ("[链接]", "[音乐]", "[公众号]"):
            return "link"
        if quoted_raw == "[位置]":
            return "location"
        if quoted_raw == "[名片]":
            return "card"
        if quoted_raw == "[视频号]":
            return "video_account"
        # 文件名特征：包含扩展名
        if "." in quoted_raw and not quoted_raw.startswith("http"):
            ext = quoted_raw.rsplit(".", 1)[-1].lower()
            if ext in (
                "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf",
                "txt", "zip", "rar", "7z", "tar", "gz",
                "jpg", "jpeg", "png", "gif", "bmp", "webp",
                "mp3", "wav", "mp4", "avi", "mov", "mkv",
            ):
                return "file"
        return "text"

    def _infer_type_from_db(self, chat_name: str, quoted_content: str) -> Optional[str]:
        """从 DB 中查找匹配的消息类型（用于位置等无法从内容推断的引用）。"""
        try:
            # 正向搜索：quoted_content 出现在 DB 记录的 content/extra 中
            row = self._repo._conn.execute(
                "SELECT content_type FROM messages "
                "WHERE chat_name = ? AND content_type NOT IN ('system', 'time_separator', 'quote', 'text') "
                "AND (extra LIKE ? OR content LIKE ?) "
                "ORDER BY created_at DESC LIMIT 1",
                (chat_name, f"%{quoted_content}%", f"%{quoted_content}%"),
            ).fetchone()
            if row:
                return row[0]

            # 反向搜索：DB 记录的 content 出现在 quoted_content 中
            # 用于视频号等场景（DB存频道名，引用显示视频标题含频道名）
            rows = self._repo._conn.execute(
                "SELECT content_type, content FROM messages "
                "WHERE chat_name = ? AND content_type NOT IN ('system', 'time_separator', 'quote', 'text') "
                "ORDER BY created_at DESC LIMIT 20",
                (chat_name,),
            ).fetchall()
            for r in rows:
                db_content = r[1] or ""
                if db_content and len(db_content) >= 2 and db_content in quoted_content:
                    return r[0]
        except Exception as e:
            logger.debug("DB 类型推断异常: %s", e)
        return None

    @staticmethod
    def _extract_quote_info(
        msg: Any, reply_content: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """从控件树提取引用消息的发送者、内容和类型。

        Returns:
            (quoted_sender, quoted_content, detected_type)
            detected_type: 从控件树检测到的类型（如 "location"），无法判断时为 None
        """
        try:
            control = getattr(msg, "control", None)
            if control is None:
                return None, None, None

            # 收集所有 TextControl 和特殊控件名称
            texts: list = []
            special_names: list = []

            def _collect(ctrl, depth=0):
                if depth > 12:
                    return
                name = getattr(ctrl, "Name", "")
                if ctrl.ControlTypeName == "TextControl":
                    if name:
                        texts.append((name, depth))
                # 记录含特殊标记的控件名称（如 "[位置]", "查看位置" 等）
                if name and name not in ("", reply_content):
                    special_names.append((name, ctrl.ControlTypeName, depth))
                for child in (ctrl.GetChildren() or []):
                    _collect(child, depth + 1)

            _collect(control)

            if not texts:
                return None, None, None

            logger.debug("引用控件树 texts: %s", texts)

            # 检测特殊类型
            detected_type = None
            for name, ctype, depth in special_names:
                if name in ("[位置]", "查看位置"):
                    detected_type = "location"
                    break

            # 策略：回复文字是第一个 TextControl（与 reply_content 匹配）
            # 后续的 TextControl 属于引用区
            quote_texts = []
            found_reply = False
            for name, depth in texts:
                if not found_reply and name == reply_content:
                    found_reply = True
                    continue
                if found_reply:
                    quote_texts.append(name)

            # 如果没有精确匹配到回复文字，跳过第一个 TextControl
            if not found_reply and len(texts) > 1:
                quote_texts = [name for name, _ in texts[1:]]

            if not quote_texts:
                return None, None, detected_type

            # 解析引用区的 TextControl
            # 情况1: 单个 "发送者 : 内容" 格式
            if len(quote_texts) == 1:
                text = quote_texts[0]
                if " : " in text:
                    sender, content = text.split(" : ", 1)
                    return sender.strip(), content.strip(), detected_type
                return None, text, detected_type

            # 情况2: 多个 TextControl，如 ["桔梗", " : ", ...] 或 ["桔梗", " : "]
            # 第一个是发送者，" : " 是分隔符，后面是内容
            sender = quote_texts[0]
            # 过滤掉 " : " 分隔符
            remaining = [t for t in quote_texts[1:] if t.strip() != ":"]
            quoted_content = remaining[0] if remaining else None
            return sender, quoted_content, detected_type

        except Exception as e:
            logger.debug("引用控件树提取异常: %s", e)
            return None, None, None

    def _adapt_other(
        self, msg: Any, chat_name: str, sender_attr: SenderAttr
    ) -> MessageDTO:
        content = getattr(msg, "content", "")

        # 位置消息（wxauto 中位置消息的 type 为 other，需在此检测）
        loc = LOCATION_PATTERN.match(content)
        if loc:
            logger.debug("类型分支: location, 来源: other + content regex")
            address, detail = self._extract_location_address(msg)
            extra: Dict[str, Any] = {"address": address, "detail": detail, "lat": None, "lng": None}
            return self._finish(
                msg, chat_name, ContentType.LOCATION, sender_attr, content, extra
            )

        # 个人名片
        if CONTACT_CARD_PATTERN.match(content):
            logger.debug("类型分支: card, 来源: other + card regex (名片)")
            card_info = self._extract_link_card_info(msg)
            extra: Dict[str, Any] = {
                "title": card_info.get("title"),
                "description": card_info.get("description"),
            }
            display_content = card_info.get("title") or content
            return self._finish(
                msg, chat_name, ContentType.CARD, sender_attr, display_content, extra
            )

        # 视频号
        if VIDEO_ACCOUNT_PATTERN.match(content):
            logger.debug("类型分支: video_account, 来源: other + card regex (视频号)")
            card_info = self._extract_link_card_info(msg)
            extra: Dict[str, Any] = {
                "title": card_info.get("title"),
                "description": card_info.get("description"),
            }
            display_content = card_info.get("title") or content
            return self._finish(
                msg, chat_name, ContentType.VIDEO_ACCOUNT, sender_attr, display_content, extra
            )

        # 链接卡片消息（微信中分享链接/音乐/公众号等）
        # 1) content 为 [音乐]/[链接]/[公众号] 的明确匹配
        # 2) 兜底：尝试从控件树提取卡片信息（如 QQ 音乐分享 content 为 "歌名 歌手"）
        link_card = LINK_CARD_PATTERN.match(content)
        if link_card:
            card_type_name = link_card.group(1)
            logger.debug("类型分支: link, 来源: other + card regex (%s)", card_type_name)
            card_info = self._extract_link_card_info(msg)
            extra: Dict[str, Any] = {
                "title": card_info.get("title"),
                "description": card_info.get("description"),
                "source": card_info.get("source") or card_type_name,
            }
            display_content = card_info.get("title") or content
            return self._finish(
                msg, chat_name, ContentType.LINK, sender_attr, display_content, extra
            )

        # 兜底：尝试从控件树检测是否为卡片消息（有 source 说明是分享卡片）
        card_info = self._extract_link_card_info(msg)
        if card_info.get("source"):
            source = card_info["source"]
            # 小程序单独类型
            if source == "小程序":
                logger.debug("类型分支: mini_program, 来源: other + 控件树检测 (source=%s)", source)
                extra: Dict[str, Any] = {
                    "title": card_info.get("title"),
                    "description": card_info.get("description"),
                }
                display_content = card_info.get("title") or content
                return self._finish(
                    msg, chat_name, ContentType.MINI_PROGRAM, sender_attr, display_content, extra
                )
            logger.debug("类型分支: link, 来源: other + 控件树检测 (source=%s)", source)
            extra: Dict[str, Any] = {
                "title": card_info.get("title"),
                "description": card_info.get("description"),
                "source": source,
            }
            display_content = card_info.get("title") or content
            return self._finish(
                msg, chat_name, ContentType.LINK, sender_attr, display_content, extra
            )

        logger.debug(
            "类型分支: other, 来源: msg.type=%s", getattr(msg, "type", "?")
        )
        return self._finish(
            msg,
            chat_name,
            ContentType.OTHER,
            sender_attr,
            content,
            {},
        )

    @staticmethod
    def _extract_link_card_info(msg: Any) -> Dict[str, Optional[str]]:
        """从链接卡片消息控件的 TextControl 中提取标题、描述、来源。

        微信链接卡片通常包含多个 TextControl：
          - 标题（如"廉价token的代价"）
          - 描述（如"UP主：雷哥AI"）
          - 来源（如"哔哩哔哩"）
        """
        result: Dict[str, Optional[str]] = {"title": None, "description": None, "source": None}
        try:
            control = getattr(msg, "control", None)
            if control is None:
                return result

            skip_names = {"", "[音乐]", "[链接]", "[公众号]", "[视频号]", "[名片]"}
            texts: list = []

            def _collect_text(ctrl, depth=0):
                if depth > 10:
                    return
                if ctrl.ControlTypeName == "TextControl":
                    name = getattr(ctrl, "Name", "")
                    if name and name not in skip_names:
                        texts.append(name)
                for child in (ctrl.GetChildren() or []):
                    _collect_text(child, depth + 1)

            _collect_text(control)

            # DEBUG: dump 完整控件树，用于探测可用信息
            def _dump_tree(ctrl, depth=0):
                if depth > 10:
                    return
                ctype = getattr(ctrl, "ControlTypeName", "?")
                name = getattr(ctrl, "Name", "")
                auto_id = getattr(ctrl, "AutomationId", "")
                class_name = getattr(ctrl, "ClassName", "")
                line = f"{'  ' * depth}{ctype} | Name='{name}' | AutoId='{auto_id}' | Class='{class_name}'"
                logger.debug("控件树: %s", line)
                for child in (ctrl.GetChildren() or []):
                    _dump_tree(child, depth + 1)

            _dump_tree(control)

            if len(texts) >= 1:
                result["title"] = texts[0]
            if len(texts) >= 2:
                result["description"] = texts[1]
            if len(texts) >= 3:
                result["source"] = texts[2]
            if texts:
                logger.debug("链接卡片提取: texts=%s -> title='%s', desc='%s', source='%s'",
                             texts, result["title"], result["description"], result["source"])
        except Exception as e:
            logger.debug("链接卡片提取异常: %s", e)
        return result

    @staticmethod
    def _extract_location_address(msg: Any) -> Tuple[Optional[str], Optional[str]]:
        """从位置消息控件的 TextControl 中提取地址名称和详细地址。

        微信位置气泡的控件结构（depth=7-8）中包含两个 TextControl：
          - 第一个：地点名称（如"紫金研发创业中心"）
          - 第二个：详细地址（如"江宁区挹淮街附近"）

        Returns:
            (地点名称, 详细地址)，提取失败时对应字段为 None。
        """
        try:
            control = getattr(msg, "control", None)
            if control is None:
                return None, None

            # 收集所有 TextControl 的文本
            texts: list = []
            skip_names = {"", "[位置]", "查看位置"}

            def _collect_text(ctrl, depth=0):
                if depth > 10:
                    return
                if ctrl.ControlTypeName == "TextControl":
                    name = getattr(ctrl, "Name", "")
                    if name and name not in skip_names:
                        texts.append(name)
                for child in (ctrl.GetChildren() or []):
                    _collect_text(child, depth + 1)

            _collect_text(control)

            address = texts[0] if len(texts) >= 1 else None
            detail = texts[1] if len(texts) >= 2 else None
            if address:
                logger.debug("位置地址提取: address='%s', detail='%s'", address, detail)
            return address, detail
        except Exception as e:
            logger.debug("位置地址提取异常: %s", e)
            return None, None

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
        time_key = (message_time.isoformat() if hasattr(message_time, "isoformat") else str(message_time)) if message_time else ""
        raw = f"{chat_name}\x00{sender}\x00{content_type}\x00{content_preview}\x00{extra_key}\x00{id_key}\x00{time_key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
