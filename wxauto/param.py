from typing import Literal
import os
import sys

PROJECT_NAME = "wxauto"


def _get_app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class WxParam:
    LANGUAGE: Literal["cn", "cn_t", "en"] = "cn"
    ENABLE_FILE_LOGGER: bool = True
    DEFAULT_SAVE_PATH: str = os.path.join(_get_app_base_dir(), "wxauto文件下载")
    MESSAGE_HASH: bool = False
    DEFAULT_MESSAGE_XBIAS = 51
    FORCE_MESSAGE_XBIAS: bool = False
    LISTEN_INTERVAL: int = 1
    SEARCH_CHAT_TIMEOUT: int = 5


class WxResponse(dict):
    def __init__(self, status: str, message: str, data: dict = None):
        super().__init__(status=status, message=message, data=data)

    def __str__(self):
        return str(self.to_dict())

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        return {
            "status": self["status"],
            "message": self["message"],
            "data": self["data"],
        }

    def __bool__(self):
        return self.is_success

    @property
    def is_success(self):
        return self["status"] == "成功"

    @classmethod
    def success(cls, message=None, data: dict = None):
        return cls(status="成功", message=message, data=data)

    @classmethod
    def failure(cls, message: str, data: dict = None):
        return cls(status="失败", message=message, data=data)

    @classmethod
    def error(cls, message: str, data: dict = None):
        return cls(status="错误", message=message, data=data)
