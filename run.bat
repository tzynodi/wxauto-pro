@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo 正在启动 wxauto-pro 消息监听...
python -m src.app
if errorlevel 1 (
    echo.
    echo 启动失败，请检查：
    echo   1. 已安装 Python 并加入 PATH
    echo   2. 已执行 pip install -r requirements.txt
    echo   3. 微信已登录并保持运行
    pause
    exit /b 1
)

pause
