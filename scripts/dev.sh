#!/usr/bin/env bash
# 启动开发环境（后端 + 桌面端）。
#
#   ./scripts/dev.sh          启动后端并打印连接信息
#   ./scripts/dev.sh server   只起后端
#   ./scripts/dev.sh desktop  只起桌面端（需先起后端）
#   ./scripts/dev.sh mock     起 mock 书站，用于书源调试
#
# 需要 uv 与 Node.js 20+。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-server}"

case "$MODE" in
  server)
    echo "启动 InkFlow 后端（Ctrl+C 停止）…"
    exec uv run inkflow-server
    ;;

  desktop)
    echo "启动桌面端…"
    cd desktop
    if [ ! -d node_modules ]; then
      echo "首次运行，安装前端依赖…"
      npm install
    fi
    exec npm run dev
    ;;

  mock)
    echo "启动 mock 书站（端口 8765）…"
    exec uv run python -m tests.mock_server --port 8765
    ;;

  *)
    echo "用法：$0 [server|desktop|mock]" >&2
    exit 2
    ;;
esac
