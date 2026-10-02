# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 inkflow-server 打成单文件可执行程序。

产物会作为 extraResources 打进 Electron 安装包，
所以桌面端用户不需要自己装 Python。

    uv run pyinstaller packaging/inkflow-server.spec --noconfirm
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH 由 PyInstaller 注入，指向本 spec 文件所在目录。
# 不用相对路径：spec 里的相对路径是相对**运行时 cwd** 解析的，
# 从仓库根跑就会找不到入口文件。
ENTRY = os.path.join(SPECPATH, "entry.py")

datas = []
binaries = []
hiddenimports = []

# 自己的包全部整包收集 —— 里面有不少动态导入（书源工厂注册、
# 格式解析器注册），静态分析抓不全
for package in (
    "inkflow_core",
    "inkflow_source",
    "inkflow_legado",
    "inkflow_export",
    "inkflow_api",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# uvicorn 的协议实现是运行时按字符串动态加载的，PyInstaller 看不到
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# sqlalchemy 的方言同样是动态导入
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")

# pydantic v2 的 Rust 扩展
hiddenimports += ["pydantic_core", "annotated_types"]

a = Analysis(
    [ENTRY],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 显式排除用不到的重量级依赖，能显著缩小体积
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "PyQt5",
        "PySide2",
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
    name="inkflow-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 控制台程序：Desktop 靠读它的 stdout 拿握手信息，不能隐藏窗口
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
