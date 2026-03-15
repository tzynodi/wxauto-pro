"""wxauto 适配层：对 WeChat / AddListenChat / KeepRunning 的薄封装。"""

import logging
from typing import Callable

logger = logging.getLogger("wxauto_pro.facade")


class WxFacade:
    """wxauto WeChat 的薄封装，隔离 wxauto 依赖。"""

    def __init__(self) -> None:
        from wxauto import WeChat

        logger.info("初始化 WeChat...")
        # 启用 wxauto 自身的 debug 模式，让 wxlog 输出 DEBUG 级别日志，便于排查
        self._wx = WeChat(debug=True)
        logger.info("WeChat 初始化完成, 昵称: %s", self._wx.nickname)

    def add_listen_chat(self, nickname: str, callback: Callable) -> None:
        """注册监听。callback 签名: (msg: Message, chat_name: str) -> None"""
        logger.info("注册监听: %s", nickname)
        result = self._wx.AddListenChat(nickname, callback)
        # AddListenChat 成功时返回 Chat，失败时返回 WxResponse
        if hasattr(result, "is_success") and not result.is_success:
            logger.error("注册监听失败: %s, %s", nickname, result)
        else:
            logger.info("注册监听成功: %s", nickname)

    def keep_running(self) -> None:
        """主线程保活，阻塞直到进程退出。"""
        logger.info("主线程保活 KeepRunning() 启动")
        self._wx.KeepRunning()
