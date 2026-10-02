# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 inkflow CLI 打成单文件可执行程序。

CLI 只依赖 ``inkflow-core``（数据目录约定、错误码），
不打包书源引擎与 API 服务，产物因此比后端小一个数量级。

    uv run pyinstaller packaging/inkflow-cli.spec --noconfirm
"""

import os

from PyInstaller.utils.hooks import collect_all

# SPECPATH 由 PyInstaller 注入；spec 里的相对路径是按运行时 cwd 解析的，
# 用相对路径会在从仓库根调用时找不到入口
ENTRY = os.path.join(SPECPATH, "cli_entry.py")

datas = []
binaries = []
hiddenimports = []

for package in ("inkflow_core", "inkflow_cli"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# typer / rich 有运行时动态查找的部分，显式声明更稳
hiddenimports += [
    "typer",
    "typer.main",
    "click",
    "rich",
    "rich.console",
    "rich.table",
    "rich.panel",
    "httpx",
    "httpcore",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.client",
    "pydantic",
    "pydantic_core",
]

a = Analysis(
    [ENTRY],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        # CLI 用不到书源引擎与 API 服务
        "inkflow_source",
        "inkflow_legado",
        "inkflow_api",
        "inkflow_export",
        "lxml",
        "sqlalchemy",
        "fastapi",
        "uvicorn",
        "pyinstaller",
        "pytest",
        "mypy",
        "ruff",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="inkflow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 命令行程序，必须保留控制台
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
