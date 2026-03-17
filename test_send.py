"""发送消息测试脚本 — 仅测试引用文字消息。

用法：
    python test_send.py

使用前修改下方 CONFIG 区域的配置。
"""

import os
import sys
import time

from wxauto import WeChat

# ============================================================
# CONFIG — 修改这里
# ============================================================

TARGET = "文件传输助手"
TEXT_CONTENT = "1"
WAIT_SECONDS = 2

# ============================================================


def main():
    print(f"目标聊天: {TARGET}")
    print()

    wx = WeChat(debug=True)
    print(f"当前登录: {wx.nickname}")
    print()

    # ----------------------------------------------------------
    # 引用文字消息 + 发送文字
    # ----------------------------------------------------------
    print("=" * 50)
    print("测试: 引用文字消息 + 发送文字")
    print("=" * 50)

    wx.ChatWith(TARGET)
    time.sleep(1)
    msgs = wx.GetAllMessage()

    quotable = None
    for msg in reversed(msgs):
        if getattr(msg, "type", "") == "text" and getattr(msg, "attr", "") in ("friend", "self"):
            quotable = msg
            break

    if quotable:
        print(f"引用消息: [{quotable.attr}/{quotable.type}] {quotable.content[:50]}")
        result = quotable.quote(TEXT_CONTENT)
        print(f"结果: {result}")
    else:
        print("未找到可引用的文字消息，跳过")

    print("\n测试完成。")


if __name__ == "__main__":
    main()
