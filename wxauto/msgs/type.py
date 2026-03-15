from wxauto.utils.tools import (
    get_file_dir,
)
from wxauto.ui.component import (
    CMenuWnd,
    WeChatImage,
)
from wxauto.utils.win32 import (
    ReadClipboardData,
    SetClipboardText,
)
from wxauto.logger import wxlog
from .base import *
from typing import (
    Union,
)
from pathlib import Path
import shutil


class TextMessage(HumanMessage):
    type = 'text'
    
    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox"
        ):
        super().__init__(control, parent)

class MediaMessage:

    def download(
            self, 
            dir_path: Union[str, Path] = None,
            timeout: int = 30
        ) -> Path:
        """下载图片/视频。默认超时 30 秒，并在失败时写入日志。"""
        if dir_path is None:
            dir_path = WxParam.DEFAULT_SAVE_PATH
        if self.type == 'image':
            filename = f"wxauto_{self.type}_{time.strftime('%Y%m%d%H%M%S')}.png"
        elif self.type == 'video':
            filename = f"wxauto_{self.type}_{time.strftime('%Y%m%d%H%M%S')}.mp4"
        filepath = get_file_dir(dir_path) / filename

        # --- 最大连续失败次数，超过则提前放弃 ---
        MAX_CLICK_FAILURES = 5

        def _find_bubble_rect(parent_control):
            """在 parent_control 内递归搜索（最多2层），
            返回面积最小、非 ButtonControl、且 ≥100x100 的子控件的 BoundingRectangle。"""
            best_rect = None
            best_area = float('inf')
            for child in (parent_control.GetChildren() or []):
                try:
                    rect = child.BoundingRectangle
                except Exception:
                    continue
                # 按控件类型排除头像（ButtonControl），不依赖坐标比较
                if child.ControlTypeName == "ButtonControl":
                    continue
                w, h = rect.width(), rect.height()
                if w >= 100 and h >= 100 and w * h < best_area:
                    best_rect = rect
                    best_area = w * h
                # 往下再搜一层
                for grandchild in (child.GetChildren() or []):
                    try:
                        grect = grandchild.BoundingRectangle
                    except Exception:
                        continue
                    if grandchild.ControlTypeName == "ButtonControl":
                        continue
                    gw, gh = grect.width(), grect.height()
                    if gw >= 100 and gh >= 100 and gw * gh < best_area:
                        best_rect = grect
                        best_area = gw * gh
            return best_rect

        def _calc_click_screen_pos():
            """实时计算右键点击的屏幕坐标 (screen_x, screen_y, desc)。
            每次调用都从控件树读取最新坐标，不缓存。
            会将点击位置裁剪到聊天区域可见范围内。"""
            try:
                ctrl_rect = self.control.BoundingRectangle

                # 获取聊天区域（消息列表容器）的可见边界，用于裁剪
                visible_bottom = ctrl_rect.bottom
                try:
                    list_ctrl = self.control.GetParentControl()
                    if list_ctrl:
                        visible_bottom = list_ctrl.BoundingRectangle.bottom
                except Exception:
                    pass

                if self.type == "image":
                    img = self.control.ImageControl(searchDepth=8)
                    if img.Exists(0.3):
                        r = img.BoundingRectangle
                        sx = (r.left + r.right) // 2
                        sy = min((r.top + r.bottom) // 2, visible_bottom - 10)
                        return sx, sy, f"ImageControl {r}"
                if self.type == "video":
                    pane = self.control.GetProgenyControl(8, 1, control_type="PaneControl")
                    if pane is not None:
                        r = pane.BoundingRectangle
                        sx = (r.left + r.right) // 2
                        sy = min((r.top + r.bottom) // 2, visible_bottom - 10)
                        return sx, sy, f"PaneControl {r}"
                # 通用：找非 ButtonControl 的子控件
                parent_width = ctrl_rect.width()
                for child in (self.control.GetChildren() or []):
                    try:
                        rect = child.BoundingRectangle
                    except Exception:
                        continue
                    if child.ControlTypeName == "ButtonControl":
                        continue
                    if rect.width() <= 20 or rect.height() <= 20:
                        continue
                    # 子控件太宽 → 在内部找精确气泡位置
                    if rect.width() > parent_width * 0.7:
                        bubble = _find_bubble_rect(child)
                        if bubble is not None:
                            sx = (bubble.left + bubble.right) // 2
                            sy = min((bubble.top + bubble.bottom) // 2, visible_bottom - 10)
                            desc = (
                                f"bubble {bubble}[{bubble.width()}x{bubble.height()}]"
                                f" screen=({sx},{sy}) visible_bottom={visible_bottom}"
                            )
                            return sx, sy, desc
                    # 子控件宽度合理，直接用其中心
                    sx = (rect.left + rect.right) // 2
                    sy = min((rect.top + rect.bottom) // 2, visible_bottom - 10)
                    return sx, sy, f"child {child.ControlTypeName} {rect}[{rect.width()}x{rect.height()}]"
            except Exception as e:
                wxlog.debug("[MediaMessage.download] 定位气泡异常: %s", e)
            return None, None, None

        t0 = time.time()
        fail_count = 0
        while True:
            # 每次循环前确保消息滚入视野
            if hasattr(self, "roll_into_view"):
                self.roll_into_view()
            time.sleep(0.1)

            # 实时计算屏幕坐标（不缓存，因为滚动会改变位置）
            sx, sy, desc = _calc_click_screen_pos()
            if sx is not None:
                wxlog.debug("[MediaMessage.download] 气泡定位: %s", desc)
                # 用 uia.RightClick 模拟鼠标（已通过 roll_into_view 确保窗口可见）
                uia.RightClick(sx, sy)
            else:
                wxlog.debug("[MediaMessage.download] 无法定位气泡，兜底右键")
                try:
                    self.control.RightClick(x=-80)
                except Exception as e:
                    fail_count += 1
                    wxlog.debug("[MediaMessage.download] 右键异常(%d/%d): %s", fail_count, MAX_CLICK_FAILURES, e)
                    if fail_count >= MAX_CLICK_FAILURES:
                        wxlog.warning("[MediaMessage.download] 连续 %d 次右键异常，放弃下载", fail_count)
                        return WxResponse.failure(f'右键失败: {self.type}')
                    time.sleep(0.3)
                    continue

            # 等待右键菜单弹出
            time.sleep(0.5)
            menu = CMenuWnd(self)
            if menu and menu.select('复制'):
                try:
                    clipboard_data = ReadClipboardData()
                    cpath = clipboard_data['15'][0]
                    fail_count = 0
                    break
                except:
                    pass
            else:
                fail_count += 1
                # 只在菜单确实存在时才 close（发送 Esc），否则 Esc 会关闭聊天窗口
                if menu:
                    menu.close()
                wxlog.debug("[MediaMessage.download] 未弹出菜单(%d/%d)", fail_count, MAX_CLICK_FAILURES)
                if fail_count >= MAX_CLICK_FAILURES:
                    wxlog.warning("[MediaMessage.download] 连续 %d 次未弹出菜单，放弃下载", fail_count)
                    return WxResponse.failure(f'右键菜单失败: {self.type}')
            if time.time() - t0 > timeout:
                wxlog.warning('[MediaMessage.download] 超时(%.0fs): 下载 %s 失败', timeout, self.type)
                return WxResponse.failure(f'下载超时: {self.type}')
            time.sleep(0.3)

        shutil.copyfile(cpath, filepath)
        SetClipboardText('')
        if imagewnd := WeChatImage():
            imagewnd.close()
        return filepath

class ImageMessage(HumanMessage, MediaMessage):
    type = 'image'
    
    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox"
        ):
        super().__init__(control, parent)

class VideoMessage(HumanMessage, MediaMessage):
    type = 'video'
    
    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox"
        ):
        super().__init__(control, parent)

class VoiceMessage(HumanMessage):
    type = 'voice'
    
    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox"
        ):
        super().__init__(control, parent)

    def to_text(self):
        """语音转文字。对语音气泡控件右键弹出菜单，避免使用基类 right_click() 点到头像。"""
        if self.control.GetProgenyControl(8, 4):
            return self.control.GetProgenyControl(8, 4).Name
        voicecontrol = self.control.ButtonControl(Name='')
        if not voicecontrol.Exists(0.5):
            return WxResponse.failure('语音转文字失败')
        self.roll_into_view()
        voicecontrol.RightClick()
        menu = CMenuWnd(self.parent)
        menu.select('语音转文字')

        text = ''
        while True:
            if not self.control.Exists(0):
                return WxResponse.failure('消息已撤回')
            text_control = self.control.GetProgenyControl(8, 4)
            if text_control is not None:
                if text_control.Name == text:
                    return text
                text = text_control.Name
            time.sleep(0.1)

class FileMessage(HumanMessage):
    type = 'file'

    # 打开菜单最大尝试次数，避免点错头像时无限重试
    OPEN_MENU_MAX_RETRIES = 5
    # 获取「复制」并写入文件的总超时（秒）
    DOWNLOAD_TIMEOUT = 30
    # 写入 copyfile 阶段超时（秒）
    COPYFILE_TIMEOUT = 5

    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox"
        ):
        super().__init__(control, parent)
        try:
            self.filename = control.TextControl().Name or "[文件]"
        except Exception:
            self.filename = getattr(control, 'Name', None) or "[文件]"
        try:
            size_control = control.GetProgenyControl(10, control_type='TextControl')
            self.filesize = size_control.Name if size_control else ""
        except Exception:
            self.filesize = ""

    def _right_click_file_bubble(self):
        """对文件气泡区域右键，弹出菜单。避免使用基类 right_click() 点到头像。"""
        self.roll_into_view()
        # 用显示文件名的 TextControl 作为右键目标，避免点到头像
        file_text = self.control.TextControl(Name=self.filename)
        if file_text.Exists(0.5):
            file_text.RightClick()
        else:
            # 回退：用第一个 TextControl
            fallback = self.control.TextControl()
            if fallback.Exists(0.5):
                fallback.RightClick()
            else:
                self.control.RightClick()

    def download(
            self, 
            dir_path: Union[str, Path] = None,
            force_click: bool = False,
            timeout: int = None
        ) -> Path:
        """下载文件。对文件气泡右键，带超时与最大重试。"""
        try:
            timeout = int(timeout) if timeout is not None else self.DOWNLOAD_TIMEOUT
        except (TypeError, ValueError):
            timeout = self.DOWNLOAD_TIMEOUT
        wxlog.debug('[FileMessage.download] 开始 filename=%s dir_path=%s timeout=%s', self.filename, dir_path, timeout)
        if dir_path is None:
            dir_path = WxParam.DEFAULT_SAVE_PATH
        filepath = get_file_dir(dir_path) / self.filename
        t0 = time.time()

        def open_file_menu():
            for attempt in range(1, self.OPEN_MENU_MAX_RETRIES + 1):
                menu = CMenuWnd(self.parent)
                if menu:
                    return menu
                self.roll_into_view()
                self._right_click_file_bubble()
                wxlog.debug('[FileMessage.download] 打开菜单尝试 %d/%d', attempt, self.OPEN_MENU_MAX_RETRIES)
                time.sleep(0.3)
            wxlog.warning('[FileMessage.download] 打开菜单失败，已重试 %d 次', self.OPEN_MENU_MAX_RETRIES)
            return None

        if force_click:
            self.roll_into_view()
            file_text = self.control.TextControl(Name=self.filename)
            if file_text.Exists(0.5):
                file_text.Click()
            else:
                self.control.Click()

        temp_filepath = None
        while True:
            if time.time() - t0 > timeout:
                wxlog.warning('[FileMessage.download] 超时(%.0fs): 等待菜单/复制 filename=%s', timeout, self.filename)
                return WxResponse.failure("文件下载超时")
            try:
                if self.control.TextControl(Name=self._lang('接收中')).Exists(0):
                    time.sleep(0.1)
                    continue
                menu = open_file_menu()
                if menu is None:
                    time.sleep(0.5)
                    continue
                wxlog.debug('[FileMessage.download] 菜单选项: %s', getattr(menu, 'option_names', []))
                if (option := self._lang('复制')) in menu.option_names:
                    menu.select(option)
                    temp_filepath = Path(ReadClipboardData().get('15')[0])
                    wxlog.debug('[FileMessage.download] 已复制到剪贴板 temp=%s -> 目标=%s', temp_filepath, filepath)
                    break
            except Exception as e:
                wxlog.debug('[FileMessage.download] 等待复制异常: %s', e)
                time.sleep(0.1)

        t0 = time.time()
        while True:
            if time.time() - t0 > self.COPYFILE_TIMEOUT:
                wxlog.warning('[FileMessage.download] 超时(%.0fs): 写入文件失败 filename=%s', self.COPYFILE_TIMEOUT, self.filename)
                return WxResponse.failure("文件下载超时")
            try:
                shutil.copyfile(temp_filepath, filepath)
                SetClipboardText('')
                wxlog.debug('[FileMessage.download] 完成 filepath=%s', filepath)
                return filepath
            except Exception as e:
                wxlog.debug('[FileMessage.download] copyfile 异常: %s', e)
                time.sleep(0.01)


class OtherMessage(BaseMessage):
    type = 'other'
    
    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox",

        ):
        super().__init__(control, parent)