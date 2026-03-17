"""项目入口。运行: python main.py"""

import sys

from src.app import App
from src.config import AppConfig


def main() -> None:
    config = AppConfig(
        listen_chats=["桔梗","今天拍了吗？","燕云十六声吉星高高照业主群","南京摄影模特互勉群①"],  # 修改为需要监听的聊天（群名或好友名）
        # 建议始终开启文件日志，便于排查问题；实际文件名会在此基础上追加时间戳
        log_file="wxauto_logs/app.log",
        log_level="DEBUG",  # 临时开启 DEBUG 方便排查，后续可改回 INFO
    )
    app = App(config)
    try:
        app.start()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在退出...", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
