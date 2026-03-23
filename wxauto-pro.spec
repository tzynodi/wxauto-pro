# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).resolve().parent
hiddenimports = [
    "pythoncom",
    "pywintypes",
    "comtypes",
    "comtypes.client",
    "comtypes.gen",
    "comtypes.gen.UIAutomationClient",
]
datas = []
wxauto_bin_dir = project_root / "wxauto" / "bin"
if wxauto_bin_dir.exists():
    datas.append((str(wxauto_bin_dir), "wxauto/bin"))

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["comtypes.test", "setuptools", "wheel"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="wxauto-pro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="wxauto-pro",
)
