from wxauto import uiautomation as uia
from wxauto.logger import wxlog
from wxauto.param import (
    WxResponse,
    WxParam,
    PROJECT_NAME
)
from wxauto.ui.component import (
    CMenuWnd,
    SelectContactWnd
)
from wxauto.utils.tools import roll_into_view
from wxauto.languages import *
from typing import (
    Dict, 
    List, 
    Union,
    TYPE_CHECKING
)
from hashlib import md5
import time

if TYPE_CHECKING:
    from wxauto.ui.chatbox import ChatBox

def truncate_string(s: str, n: int=8) -> str:
    s = s.replace('\n', '').strip()
    return s if len(s) <= n else s[:n] + '...'

class Message:...
class BaseMessage(Message):
    type: str = 'base'
    attr: str = 'base'
    control: uia.Control

    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox",

        ):
        self.control = control
        self.parent = parent
        self.root = parent.root
        self.content = self.control.Name
        self.id = self.control.runtimeid
        self.sender = self.attr
        self.sender_remark = self.attr

    def __repr__(self):
        cls_name = self.__class__.__name__
        content = truncate_string(self.content)
        return f"<{PROJECT_NAME} - {cls_name}({content}) at {hex(id(self))}>"
    
    @property
    def message_type_name(self) -> str:
        return self.__class__.__name__
    
    def chat_info(self) -> Dict:
        if self.control.Exists(0):
            return self.parent.get_info()
    
    def _lang(self, text: str) -> str:
        return MESSAGES.get(text, {WxParam.LANGUAGE: text}).get(WxParam.LANGUAGE)
    
    def get_all_text(self) -> str:
        if self.control.Exists(0):
            return [text for i in self.control.FindAll() if (text:= i.Name)]
    

    def roll_into_view(self) -> WxResponse:
        if roll_into_view(self.control.GetParentControl(), self.control, equal=True) == 'not exist':
            wxlog.warning('消息目标控件不存在，无法滚动至显示窗口')
            return WxResponse.failure('消息目标控件不存在，无法滚动至显示窗口')
        return WxResponse.success('成功')
    
    @property
    def info(self) -> Dict:
        _info = self.parent.get_info().copy()
        _info['class'] = self.message_type_name
        _info['id'] = self.id
        _info['type'] = self.type
        _info['attr'] = self.attr
        _info['content'] = self.content
        return _info


class HumanMessage(BaseMessage):
    attr = 'human'

    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox",

        ):
        super().__init__(control, parent)
        self.head_control = self.control.ButtonControl(searchDepth=2)


    def roll_into_view(self) -> WxResponse:
        if roll_into_view(self.control.GetParentControl(), self.head_control, equal=True) == 'not exist':
            return WxResponse.failure('消息目标控件不存在，无法滚动至显示窗口')
        return WxResponse.success('成功')


    def click(self):
        self.roll_into_view()
        self.head_control.Click(x=self._xbias)


    def right_click(self):
        """对消息气泡区域右键弹出菜单，避免误点头像。

        采用与 MediaMessage.download._calc_click_screen_pos 相同的气泡定位策略：
        遍历直接子控件，跳过 ButtonControl（头像）和极小控件；
        若子控件太宽（全宽容器），在其内部递归查找面积最小的非按钮子控件作为气泡。
        """
        self.roll_into_view()

        try:
            ctrl_rect = self.control.BoundingRectangle
        except Exception:
            self.control.RightClick()
            return

        # 获取聊天列表可见区域下界，用于裁剪点击坐标
        visible_bottom = ctrl_rect.bottom
        try:
            list_ctrl = self.control.GetParentControl()
            if list_ctrl:
                visible_bottom = list_ctrl.BoundingRectangle.bottom
        except Exception:
            pass

        parent_width = ctrl_rect.width()

        def _find_bubble_rect(parent_ctrl):
            """在 parent_ctrl 内搜索（最多2层），
            返回面积最小、非 ButtonControl、且 ≥30×30 的子控件的 BoundingRectangle。"""
            best_rect = None
            best_area = float('inf')
            for child in (parent_ctrl.GetChildren() or []):
                try:
                    rect = child.BoundingRectangle
                except Exception:
                    continue
                if child.ControlTypeName == "ButtonControl":
                    continue
                w, h = rect.width(), rect.height()
                if w >= 30 and h >= 30 and w * h < best_area:
                    best_rect = rect
                    best_area = w * h
                for grandchild in (child.GetChildren() or []):
                    try:
                        grect = grandchild.BoundingRectangle
                    except Exception:
                        continue
                    if grandchild.ControlTypeName == "ButtonControl":
                        continue
                    gw, gh = grect.width(), grect.height()
                    if gw >= 30 and gh >= 30 and gw * gh < best_area:
                        best_rect = grect
                        best_area = gw * gh
            return best_rect

        # 遍历直接子控件，跳过头像按钮和极小控件
        for child in (self.control.GetChildren() or []):
            try:
                rect = child.BoundingRectangle
            except Exception:
                continue
            if child.ControlTypeName == "ButtonControl":
                continue
            if rect.width() <= 20 or rect.height() <= 20:
                continue
            # 子控件太宽（全宽容器） → 在内部查找气泡
            if rect.width() > parent_width * 0.7:
                bubble = _find_bubble_rect(child)
                if bubble is not None:
                    sx = (bubble.left + bubble.right) // 2
                    sy = min((bubble.top + bubble.bottom) // 2, visible_bottom - 10)
                    wxlog.debug("[HumanMessage.right_click] 气泡定位(内部): (%s,%s) rect=%s", sx, sy, bubble)
                    uia.RightClick(sx, sy)
                    return
            # 子控件宽度合理，直接用其中心
            sx = (rect.left + rect.right) // 2
            sy = min((rect.top + rect.bottom) // 2, visible_bottom - 10)
            wxlog.debug("[HumanMessage.right_click] 气泡定位(直接): (%s,%s) %s rect=%s", sx, sy, child.ControlTypeName, rect)
            uia.RightClick(sx, sy)
            return

        # fallback: 偏移头像位置
        wxlog.debug("[HumanMessage.right_click] 使用 fallback 偏移方式")
        self.head_control.RightClick(x=self._xbias)


    def select_option(self, option: str, timeout=None) -> WxResponse:
        self.root._show()
        def _select_option(self, option):
            if not (roll_result := self.roll_into_view()):
                return roll_result
            self.right_click()
            time.sleep(0.5)  # 等待右键菜单弹出
            menu = CMenuWnd(self.root)
            return menu.select(item=option)

        if timeout:
            t0 = time.time()
            while True:
                if (time.time() - t0) > timeout:
                    return WxResponse(False, '引用消息超时')
                if quote_result := _select_option(self, option):
                    return quote_result
                time.sleep(0.3)  # 失败后短暂等待再重试

        else:
            return _select_option(self, option)
    

    def quote(
            self, text: str, 
            at: Union[List[str], str] = None, 
            timeout: int = 3
        ) -> WxResponse:
        """引用消息
        
        Args:
            text (str): 引用内容
            at (List[str], optional): @用户列表
            timeout (int, optional): 超时时间，单位为秒，若为None则不启用超时设置

        Returns:
            WxResponse: 调用结果
        """
        if not self.select_option('引用', timeout=timeout):
            wxlog.debug(f"当前消息无法引用：{self.content}")
            return WxResponse(False, '当前消息无法引用')
        
        if at:
            self.parent.input_at(at)

        return self.parent.send_text(text)
    

    def reply(
            self, text: str, 
            at: Union[List[str], str] = None
        ) -> WxResponse:
        """引用消息
        
        Args:
            text (str): 回复内容
            at (List[str], optional): @用户列表
            timeout (int, optional): 超时时间，单位为秒，若为None则不启用超时设置

        Returns:
            WxResponse: 调用结果
        """
        if at:
            self.parent.input_at(at)

        return self.parent.send_text(text)


    def forward(self, targets: Union[List[str], str], timeout: int = 3) -> WxResponse:
        """转发消息

        Args:
            targets (Union[List[str], str]): 目标用户列表
            timeout (int, optional): 超时时间，单位为秒，若为None则不启用超时设置

        Returns:
            WxResponse: 调用结果
        """
        if not self.select_option('转发', timeout=timeout):
            return WxResponse(False, '当前消息无法转发')
        
        select_wnd = SelectContactWnd(self)
        return select_wnd.send(targets)