"""项目入口。运行: python main.py"""

from src.app import App
from src.config import AppConfig


def main() -> None:
    config = AppConfig(
        listen_chats=["桔梗"],  # 修改为需要监听的聊天（群名或好友名）
    )
    app = App(config)
    app.start()


if __name__ == "__main__":
    main()
