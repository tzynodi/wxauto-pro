from .attr import *
from .type import OtherMessage
from . import self as selfmsg
from . import friend as friendmsg
from wxauto.languages import *
from wxauto.logger import wxlog
from wxauto.param import WxParam
from wxauto import uiautomation as uia
from typing import Literal
import re

class MESSAGE_ATTRS:
    SYS_TEXT_HEIGHT = 33
    TIME_TEXT_HEIGHT = 34
    CHAT_TEXT_HEIGHT = 52
    FILE_MSG_HEIGHT = 115
    VOICE_MSG_HEIGHT = 55

    TEXT_MSG_CONTROL_NUM = (8, 9, 10, 11)
    TIME_MSG_CONTROL_NUM = (1,)
    SYS_MSG_CONTROL_NUM = (4,5,6)
    IMG_MSG_CONTROL_NUM = (9, 10, 11, 12)
    # 标准文件气泡 (21,22,23,24)；部分客户端/样式下气泡结构不同（如长 hash 文件名、无「微信电脑版」），扩大范围
    FILE_MSG_CONTROL_NUM = tuple(i for i in range(18, 29))
    VOICE_MSG_CONTROL_NUM = tuple(i for i in range(10, 30))
    VIDEO_MSG_CONTROL_NUM = (13, 14, 15, 16)

def _lang(text: str) -> str:
    return MESSAGES.get(text, {WxParam.LANGUAGE: text}).get(WxParam.LANGUAGE)

SEPICIAL_MSGS = [
    _lang(i)
    for i in [
        '[图片]',     # ImageMessage
        '[视频]',     # VideoMessage
        '[语音]',     # VoiceMessage
        '[文件]',     # FileMessage
    ]
]

def parse_msg_attr(
        control: uia.Control, 
        parent,
    ):
    msg_rect = control.BoundingRectangle
    height = msg_rect.height()
    mid = (msg_rect.left + msg_rect.right) / 2
    for length, _ in enumerate(uia.WalkControl(control)):length += 1

    # TimeMessage
    if (
        height == MESSAGE_ATTRS.TIME_TEXT_HEIGHT
        and length in MESSAGE_ATTRS.TIME_MSG_CONTROL_NUM
    ):
        return TimeMessage(control, parent)
    
    # FriendMessage or SelfMessage
    if (head_control := control.ButtonControl(searchDepth=2)).Exists(0):
        head_rect = head_control.BoundingRectangle
        if head_rect.left < mid:
            return parse_msg_type(control, parent, 'Friend')
        else:
            return parse_msg_type(control, parent, 'Self')
    
    # SystemMessage or TickleMessage
    else:
        if length in MESSAGE_ATTRS.SYS_MSG_CONTROL_NUM:
            return SystemMessage(control, parent)
        elif control.ListItemControl(RegexName=_lang('re_拍一拍')).Exists(0):
            return TickleMessage(control, parent)
        else:
            return OtherMessage(control, parent)

def parse_msg_type(
        control: uia.Control,
        parent,
        attr: Literal['Self', 'Friend']
    ):
    for length, _ in enumerate(uia.WalkControl(control)):length += 1
    content = control.Name
    msg_rect = control.BoundingRectangle
    height = msg_rect.height()

    if attr == 'Friend':
        msgtype = friendmsg
    else:
        msgtype = selfmsg

    # 文件消息判断条件（打日志便于排查）
    _file_lang = _lang('[文件]')
    _file_len_range = (min(MESSAGE_ATTRS.FILE_MSG_CONTROL_NUM), max(MESSAGE_ATTRS.FILE_MSG_CONTROL_NUM))
    _is_file_length = length in MESSAGE_ATTRS.FILE_MSG_CONTROL_NUM
    _is_file_content = content == _file_lang or (content and '[文件]' in content)
    _looks_like_filename = (
        content
        and len(content) > 4
        and ('.' in content or re.search(r'\d+\.?\d*[KM]', content))
    )
    _file_final = _is_file_length and (_is_file_content or _looks_like_filename)
    # 只要任一条件沾边就打一条 INFO，带上全部条件，方便后续排查文件识别问题
    if _is_file_length or _is_file_content or _looks_like_filename:
        wxlog.info(
            '[msg] 文件判断 | content_len=%s content_preview=%s | length=%s range=%s | '
            'is_file_length=%s is_file_content=%s looks_like_filename=%s | result=%s',
            len(content or ''),
            (content[:50] + '...') if content and len(content) > 50 else (content or ''),
            length,
            _file_len_range,
            _is_file_length,
            _is_file_content,
            _looks_like_filename,
            'FileMessage' if _file_final else '非文件',
        )
    if _file_final:
        return getattr(msgtype, f'{attr}FileMessage')(control, parent)
    
    # Special Message Type
    if content in SEPICIAL_MSGS:
        # ImageMessage
        if content == _lang('[图片]') and length in MESSAGE_ATTRS.IMG_MSG_CONTROL_NUM:
            wxlog.debug('[msg] 识别为 ImageMessage content=%r length=%s', content[:40], length)
            return getattr(msgtype, f'{attr}ImageMessage')(control, parent)
        
        # VideoMessage
        elif content == _lang('[视频]') and length in MESSAGE_ATTRS.VIDEO_MSG_CONTROL_NUM:
            wxlog.debug('[msg] 识别为 VideoMessage content=%r length=%s', content[:40], length)
            return getattr(msgtype, f'{attr}VideoMessage')(control, parent)
        
        # FileMessage：已在上面统一处理（含 content 为文件名的情况），此处仅 content 为 [文件] 且 length 在范围内时兜底
        elif content == _lang('[文件]') and length in MESSAGE_ATTRS.FILE_MSG_CONTROL_NUM:
            return getattr(msgtype, f'{attr}FileMessage')(control, parent)
    
    # TextMessage
    if length in MESSAGE_ATTRS.TEXT_MSG_CONTROL_NUM:
        wxlog.debug('[msg] 识别为 TextMessage length=%s', length)
        return getattr(msgtype, f'{attr}TextMessage')(control, parent)
    
    # VoiceMessage    
    elif (
        rematch := re.compile(_lang('re_语音')).match(content)
        and length in MESSAGE_ATTRS.VOICE_MSG_CONTROL_NUM
    ):
        wxlog.debug('[msg] 识别为 VoiceMessage content=%r length=%s', content[:40], length)
        return getattr(msgtype, f'{attr}VoiceMessage')(control, parent)

    wxlog.debug('[msg] 识别为 OtherMessage content=%r length=%s', (content[:60] if content else ''), length)
    return getattr(msgtype, f'{attr}OtherMessage')(control, parent)

def parse_msg(
    control: uia.Control,
    parent
):
    result = parse_msg_attr(control, parent)
    return result