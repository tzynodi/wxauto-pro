# Windows 打包说明

当前项目适合用 `PyInstaller` 打包为 Windows 可直接运行程序。

## 推荐方式

优先使用 `onedir`：

- 兼容性更稳，特别是 `pywin32`、`comtypes` 这类 Windows 依赖
- 出问题时更容易排查
- 同样可以做到闭源分发

单文件 `onefile` 也可用，但启动更慢，某些环境下更容易遇到依赖释放问题。

## 准备

```powershell
python -m pip install pyinstaller
```

## 构建

默认构建 `onedir`：

```powershell
.\build_exe.ps1
```

构建 `onefile`：

```powershell
.\build_exe.ps1 -OneFile
```

输出目录：

- `dist\wxauto-pro\wxauto-pro.exe` (`onedir`)
- `dist\wxauto-pro.exe` (`onefile`)

## 运行注意事项

- 需要在 Windows 上运行
- 目标机器需要安装并登录微信桌面版
- 首次运行时建议右键“以管理员身份运行”，避免 UI Automation 权限不一致
- 程序运行后会在程序目录下生成 `data`、`downloads`、`wxauto_logs`

## 闭源说明

`PyInstaller` 能把源码打进可执行文件里，普通用户不能直接像 `.py` 那样查看源码，适合作为闭源交付。

但它不是强加密：

- 有经验的人仍然可以逆向部分 Python 字节码
- 如果你对“防逆向”要求高于“方便交付”，更建议评估 `Nuitka`

## 更强闭源方案

如果你后续更关注“更难被还原”，可以考虑 `Nuitka`：

- 生成更接近原生程序
- 逆向门槛更高
- 打包更慢，配置更复杂
- 对 Windows 自动化项目同样可用
