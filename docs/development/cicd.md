# CI / CD

## 流水线总览

```text
push / PR
    │
    ▼
CI ── 版本号一致性 → ruff → mypy → pytest（Ubuntu + Windows）
   └─ 桌面端：类型检查 + 构建

push tag v*
    │
    ▼
Release ── ① 后端打包（三平台）+ 冒烟测试
        └─ ② 桌面端打包（依赖 ①）
            └─ ③ 汇总产物 → 创建 GitHub Release
```

---

## CI

文件：`.github/workflows/ci.yml`

触发：push 到 `main`、任何 PR、手动触发。

| Job | 内容 |
|---|---|
| `python` | 矩阵 `ubuntu-latest` + `windows-latest`：版本号一致性 → `ruff check` → `ruff format --check` → `mypy` → `pytest` |
| `desktop` | `npm ci` → 主进程/preload 类型检查 → 渲染进程类型检查 → `npm run build` |

### 为什么 Python 要跑两个平台

Windows 是主要分发目标，Linux 覆盖 CI 常见环境。两个都跑是为了提前发现
路径分隔符、行尾、文件名大小写敏感这类只在特定平台暴露的差异。

### 为什么版本号检查放在最前面

它最快（不到一秒），而且能拦住「改了代码忘了改版本」这种低级但难查的问题。
放在流水线最后的话，前面几分钟的检查都白跑了。

---

## Release

文件：`.github/workflows/release.yml`

触发：push tag `v*`。

### ① 后端打包（`backend`）

```text
windows-latest  →  inkflow-server.exe
ubuntu-latest   →  inkflow-server
macos-latest    →  inkflow-server
```

**PyInstaller 不能交叉编译** —— Windows 上只能产出 `.exe`，
macOS 上只能产出 Mach-O。所以必须在三个平台各跑一次。

打包后立刻跑**冒烟测试**（`scripts/smoke_test_backend.py`）：
真的启动一次产物、读握手行、请求 `/health`。

这一步不是形式主义。PyInstaller 的失败模式往往是**静默的** ——
构建成功、文件存在，一运行却 `ModuleNotFoundError` 或直接退出。
只看「构建通过」会把这些漏到用户手里。

### ② 桌面端打包（`desktop`）

取回**对应平台**的后端产物，放进 `desktop/resources/backend/`，
再由 electron-builder 作为 `extraResources` 打进安装包。

这样桌面端用户不需要自己装 Python。

产物：

| 平台 | 文件 |
|---|---|
| Windows | `InkFlow-<版本>-setup.exe`（安装版）、`InkFlow-<版本>-win-x64.zip`（免安装） |
| macOS | `InkFlow-<版本>-<arch>.dmg`（arm64 + x64） |
| Linux | `InkFlow-<版本>.AppImage` |

**免安装版用 zip 而不是 portable.exe**：zip 解压后就是一个完整目录，
数据目录（`.inkflow`）与程序同级，整个文件夹拷走即可迁移；
portable.exe 每次运行会自解压到临时目录，数据反而落不到程序旁边。

另外还单独发布**命令行工具**与**后端本体**：

| 文件 | 说明 |
|---|---|
| `inkflow-cli-windows-x64.exe` / `-linux-x64` / `-macos` | CLI，纯 HTTP 客户端，约 19 MB |
| `inkflow-server-windows-x64.exe` / `-linux-x64` / `-macos` | 后端，约 27 MB |

桌面端安装包里**已经内嵌**了对应平台的后端，这两组产物是给
「只想跑服务」或「想用命令行」的人准备的。

### ③ 发布（`publish`）

汇总所有 artifact，用 `softprops/action-gh-release` 创建 Release，
`generate_release_notes: true` 自动生成变更日志。

**后端产物会按平台重命名**（`inkflow-server-linux-x64` / `inkflow-server-macos` /
`inkflow-server-windows-x64.exe`）—— Linux 与 macOS 的 PyInstaller 产物同名，
直接汇总到同一目录会互相覆盖，最后只剩一个。

含 `-` 的 tag（如 `v0.1.0-dev.0`）会标记为 **prerelease**，不占用 Latest 标记。

---

## 本地复现

CI 上跑的每一步都能在本地复现，不需要等推送。

```bash
# CI 的全部检查
uv run python scripts/check.py

# 版本号一致性
uv run python scripts/check_version.py

# 后端打包 + 冒烟测试
uv run pyinstaller packaging/inkflow-server.spec --noconfirm
uv run python scripts/smoke_test_backend.py

# 桌面端
cd desktop
npm ci
npm run typecheck
npm run build
npx electron-builder --publish never
```

---

## 发版步骤

### 1. 改版本号

**只有一处**需要手写（见 [setup.md](setup.md) 的「版本号」一节）：

```python
# packages/inkflow-core/src/inkflow_core/__init__.py
__version__ = "0.2.0"
```

同步 `desktop/package.json` 的 semver 等价写法（`0.2.0` 就是 `0.2.0`；
若带预发布后缀则 `0.2.0.dev0` → `0.2.0-dev.0`），然后：

```bash
uv sync --all-packages
uv run python scripts/check_version.py
```

### 2. 更新文档

`docs/development/roadmap.md` 的验收记录里追加本次内容。

### 3. 提交并打 tag

```bash
git add -A
git commit -m "chore: 发布 v0.2.0"
git tag v0.2.0
git push origin main --tags
```

推送 tag 后 Release 流水线自动开始。产物会挂在仓库的 Releases 页面。

### 4. 验证

流水线跑完后检查：

- [ ] Release 页面有全部四个平台的产物
- [ ] 下载 Windows 免安装版，双击能启动
- [ ] 应用内「书源」页能导入书源，搜索能出结果
- [ ] 下载一章，导出 EPUB 能用阅读器打开

---

## 已知限制

| 限制 | 影响 | 计划 |
|---|---|---|
| **未做代码签名** | Windows SmartScreen 会拦（「未知发布者」），macOS Gatekeeper 需要右键打开 | 需要证书，视分发需求决定 |
| **未做自动更新** | 用户需手动下载新版本 | Milestone 5 |
| **桌面端无自动化测试** | 只有 `vue-tsc` 类型检查兜底 | 待补 |
| **macOS 产物未公证** | 首次打开需要绕过 Gatekeeper | 需要 Apple 开发者账号 |
| **缓存未启用** | CI 每次重新装依赖（已有 uv 与 npm 缓存，但 PyInstaller 无缓存） | 可接受 |

---

## 相关文档

- 环境搭建与常用命令 → [setup.md](setup.md)
- 测试体系 → [testing.md](testing.md)
- 路线图 → [roadmap.md](roadmap.md)
