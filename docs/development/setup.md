# 开发环境搭建

## 环境要求

| 工具 | 版本 | 用途 |
|---|---|---|
| Python | **3.12+** | 后端全部代码 |
| [uv](https://docs.astral.sh/uv/) | 0.5+ | Python 依赖与 workspace 管理 |
| Node.js | **20+** | 仅桌面端需要 |

uv 负责 Python；Electron 的依赖仍由 npm 管理。两者不互相替代。

---

## 安装

```bash
git clone <repo>
cd InkFlow
uv sync --all-packages
```

> ⚠️ **必须带 `--all-packages`。**
> uv workspace 里 `uv sync` 默认只安装根项目的依赖，
> 6 个成员包（`inkflow-core` / `-source` / `-legado` / `-api` / `-cli` / `-export`）
> 不会被装进虚拟环境。漏掉这个参数的症状是：
> `uv run inkflow` 报 `ModuleNotFoundError: No module named 'inkflow_cli'`。

---

## 启动后端

```bash
uv run inkflow-server
```

启动后会打印：

```text
InkFlow —— API-First 小说资源聚合与下载平台
  数据目录      C:\Users\you\.inkflow
  配置文件      C:\Users\you\.inkflow\config\config.toml
  InkFlow API  http://127.0.0.1:53421
  接口文档      http://127.0.0.1:53421/docs
INKFLOW_READY port=53421 token=xxxxx
```

最后一行是**进程间握手信息**，Desktop 靠解析它拿到端口与 token（见 [ADR-013](../architecture/decisions.md)）。

常用参数：

| 参数 | 说明 |
|---|---|
| `--port 8765` | 固定端口（默认 0 = 系统分配） |
| `--host 0.0.0.0` | 绑定到所有网卡（**有安全风险**，会警告） |
| `--no-token` | 关闭鉴权（仅本机调试） |
| `--reload` | 代码变更自动重载 |
| `--log-level DEBUG` | 日志级别 |

---

## 启动桌面端

```bash
cd desktop
npm install
npm run dev
```

桌面端主进程会自动拉起后端（通过 `uv run inkflow-server`），
并注入正确的连接信息。不需要手动起后端。

如果 `uv` 不在 PATH 上，设置环境变量：

```bash
export INKFLOW_UV="D:/DevEnv/uv/uv.exe"
```

---

## 使用 CLI

CLI 会自动发现正在运行的后端（读 `~/.inkflow/server.json`）：

```bash
uv run inkflow info
uv run inkflow search 三体
uv run inkflow sources list
```

显式指定：

```bash
uv run inkflow --url http://127.0.0.1:8765 --token xxx search 三体
# 或
export INKFLOW_API_URL=http://127.0.0.1:8765
export INKFLOW_TOKEN=xxx
```

`--json` 是**全局选项**，要写在子命令前面：

```bash
uv run inkflow --json search 三体
```

---

## 常用命令

```bash
# 依赖
uv sync --all-packages          # 安装/同步全部包
uv add <pkg> --package inkflow-api   # 给某个包加依赖

# 检查
uv run ruff check .             # 静态检查
uv run ruff check . --fix       # 自动修复
uv run ruff format .            # 格式化
uv run mypy .                   # 类型检查

# 测试
uv run pytest                   # 全部
uv run pytest -m unit           # 只要单元测试
uv run pytest -m "not network"  # 排除需要真实网络的
uv run pytest tests/source -v   # 书源兼容性测试

# 一键（lint + format check + mypy + pytest）
uv run python scripts/check.py
uv run python scripts/check.py --fast   # 跳过 mypy
```

---

## 版本号

唯一来源是 `packages/inkflow-core/src/inkflow_core/__init__.py` 的 `__version__`，
格式为 **PEP 440**（当前 `0.1.0.dev0`）。其余位置都是派生的：

| 位置 | 方式 |
|---|---|
| 各成员包 `pyproject.toml` | `dynamic = ["version"]` + `[tool.hatch.version] path` 跨目录读取 |
| 各成员包 `__init__.py` | `from inkflow_core import __version__` |
| 根 `pyproject.toml` | 展示用（根是虚拟包），与来源保持一致 |
| `desktop/package.json` | npm 生态用 semver，取等价写法（`0.1.0.dev0` → `0.1.0-dev.0`） |

改版本号**只需改一处**，然后同步：

```bash
uv sync --all-packages
uv run python scripts/check_version.py   # 校验一致性
```

CI 会跑同一个检查 —— 硬编码版本号或忘记同步会被直接拦下。

> 副作用：成员包用了动态版本，**不能脱离 workspace 单独 `pip install`**
> —— hatch 需要能读到 `../inkflow-core/`。本项目始终在 workspace 内构建。

---

## 调试书源

```bash
# 终端 1：起 mock 书站（不需要真实网站）
uv run python -m tests.mock_server --port 8765

# 终端 2：导入并测试
uv run inkflow sources import sources/test/mock-site.yaml
uv run inkflow sources test <source-id> --kind search --keyword 三体
```

mock 站点监听 `127.0.0.1`，需要放开内网访问限制：

```bash
export INKFLOW_SOURCE__ALLOW_PRIVATE_NETWORK=true
uv run inkflow-server
```

---

## 配置

配置优先级（从高到低）：

1. 环境变量 `INKFLOW_*`（嵌套用双下划线，如 `INKFLOW_SERVER__PORT=8765`）
2. `config.toml`（当前工作目录，或 `INKFLOW_CONFIG` 指定的路径）
3. 内置默认值

模板见 [`config.example.toml`](../../config.example.toml)。

### 数据目录（便携优先）

数据默认放在**运行目录**下的 `.inkflow/`，拷贝整个程序目录即可迁移：

```text
.inkflow/
├── config/       运行时配置
├── database/     inkflow.db
├── cache/        HTTP 与正文缓存
├── exports/      导出的 TXT / EPUB
├── logs/
├── sources/      导入的书源
└── server.json   后端握手信息（端口 + token），退出时删除
```

解析顺序：

1. `INKFLOW_HOME` 环境变量 —— 显式指定（测试、特殊部署）
2. 运行目录下的 `.inkflow` —— 打包后是**可执行文件所在目录**，源码运行是**当前工作目录**
3. `~/.inkflow` —— 兜底

第 3 步不是多余的：macOS 的 `.app` 内部、部分 Linux 安装位置是只读的，
硬往里写只会让程序起不来。桌面端也会自己探测可写性后再决定。

> **副作用**：CLI 在不同目录下运行会用到不同的数据目录。
> 想让 Desktop 与 CLI 共用数据，把它们放在同一目录即可 ——
> CLI 会在所有候选目录里找 `server.json`，找得到就能连上。

---

## 排障

### `ModuleNotFoundError: No module named 'inkflow_xxx'`

漏了 `--all-packages`。见上文。

### 服务起不来 / CLI 连不上

```bash
uv run inkflow -v info   # -v 会打印「我是怎么找到服务的」
```

三种发现途径：环境变量 → `~/.inkflow/server.json` → 默认 `http://127.0.0.1:8765`。

### 访问本机服务报 502 / `os error 10061`

本机若配置了 `http_proxy`，发往 `127.0.0.1` 的请求也会被代理转出去，
看起来像「服务挂了」其实服务好好的。

```bash
curl --noproxy '*' http://127.0.0.1:8765/health
```

Python 里清掉代理环境变量，或设置 `NO_PROXY=127.0.0.1,localhost`。

### Windows 上路径传给原生程序不对

Git Bash 的 `/d/Project/x` 交给 `python.exe` / `node.exe` 会被解析成 `D:\d\Project\x`。

```bash
# 先 cd 再执行，让子进程继承已翻译好的工作目录
cd /d/Project/InkFlow && python -m http.server

# 或显式转换
cygpath -w /d/Project/InkFlow
```

### `uv run inkflow` 卡住不返回

后端没起来。CLI 会等 60 秒然后报 `CONNECTION_REFUSED`（这个错误码是明确的，
不会含糊地说「后端可能未就绪」）。

### 桌面端白屏

后端启动失败。界面会显示具体错误（而不是白屏），
先看 DevTools 控制台里的 `[inkflow-backend]` 日志。

---

## 相关文档

- 测试怎么写 → [testing.md](testing.md)
- 当前进度 → [roadmap.md](roadmap.md)
- 安全边界 → [security.md](security.md)
