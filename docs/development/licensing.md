# 许可证与合规

> ⚠️ 本文是**工程规划**，不是法律意见。正式发布前应做逐项审查。

---

## InkFlow 的许可证

**Apache-2.0**

选择理由：

- 宽松许可，允许闭源衍生与商业使用，使用者没有顾虑
- **含明确的专利授权条款** —— 这对工具类项目比 MIT 更稳妥
- 与 GPL 系不兼容的方向相反：Apache-2.0 可以被 GPL-3.0 项目使用，反之不行

完整文本见仓库根的 [`LICENSE`](../../LICENSE)，版权与第三方说明见 [`NOTICE`](../../NOTICE)。

### 这两个文件怎么分发

| 文件 | 作用 |
|---|---|
| `LICENSE` | Apache-2.0 全文 |
| `NOTICE` | 版权归属、与 Legado 的关系说明、第三方依赖提示 |

Apache-2.0 对分发有两条硬要求，它们是**绑定的**，不能只带一个：

- **§4(a)**：必须向接收者提供许可证副本
- **§4(d)**：作品含 `NOTICE` 时，分发必须携带其中的归属声明

具体落到三处：

1. **根 `pyproject.toml`** 的 `license-files` 写 `["LICENSE", "NOTICE"]`。
   PEP 639 下**显式列出后只包含列出的文件**，只写 `LICENSE` 会漏掉 NOTICE。
2. **发版流水线**把 `LICENSE` 与 `NOTICE` 一并拷进 Release 产物 ——
   分发二进制（安装包、单文件可执行程序）同样受 §4 约束，
   不能因为「仓库里有」就省略。
3. **各成员包**各自声明 `license = "Apache-2.0"`。它们不单独发布到索引，
   许可证文件由仓库根统一提供，因此不重复挂 `license-files`。

---

## 与 Legado 的关系

Legado（开源阅读）官方仓库标注为 **GPL-3.0**。这直接影响 InkFlow 的实现路径。

### 两条不同的路

| 做法 | 许可证后果 |
|---|---|
| **读取 Legado 书源格式、独立实现兼容运行时** | 不构成对 Legado 代码的衍生，InkFlow 可自选许可证 |
| **复制 Legado 源码、修改后作为 InkFlow 内核** | 属于衍生作品，InkFlow 必须以 GPL-3.0 发布 |

### InkFlow 选的是第一条

```text
InkFlow Core
      │
      ├── 自有代码（Apache-2.0）
      │
      └── Legado Compatibility Layer（inkflow-legado）
              ├── 格式解析       依据公开的规则格式独立实现
              ├── Rule Compiler  独立实现的 DSL → AST 编译
              └── Runtime Adapter 独立实现的执行器
```

具体地说：

- **没有复制** Legado 的源代码、资源文件或内部实现细节
- 兼容层依据的是**书源格式的公开描述**与**大量书源样本的实际结构**
- 「Legado」「开源阅读」等名称及相关权利归其各自权利人所有，
  InkFlow 与其无隶属、赞助或背书关系

这也是架构上「外层隔离」的另一个收益：许可证边界与代码边界是同一条线
（见 [ADR-002](../architecture/decisions.md)）。

### 需要持续注意的事

- 兼容层里**不要**粘贴来自 Legado 仓库的代码片段（哪怕是"就几行"）
- 参考其文档描述实现是可以的；翻译其实现代码不可以
- 如果将来确实需要复用 Legado 的某段实现，正确做法是：
  单独隔离成独立模块、明确标注来源与许可证、评估对整体许可证的影响
- 本项目**不复制** Legado 的书源集合

---

## 内容与版权边界

InkFlow 的定位是：

> **内容获取与个人资料整理工具，而不是内容分发平台。**

### 项目本身不做的事

```text
✗ 不内置小说正文数据库
✗ 不维护盗版内容仓库
✗ 不默认提供第三方书源合集
✗ 不提供内容检索服务
```

### 实际的使用链路

```text
用户导入书源
     ↓
用户自行选择目标
     ↓
获取内容
     ↓
保存到本地
```

每一步的决策权都在用户手里。项目提供的是**工具**，不是内容。

### 用户责任

README 与 NOTICE 中明确说明：使用本书源抓取内容时，用户需自行遵守

```text
来源网站的服务条款
版权规定
访问权限限制
所在司法辖区的法律
```

### 关于 `sources/` 目录

```text
sources/official/    随项目分发 —— 只放模板与结构示例，指向占位地址
sources/community/   社区贡献 —— .gitignore 排除，不入库
sources/test/        测试用（含 mock 站点书源，指向 127.0.0.1）
```

**项目仓库不承载任何指向真实盗版站点的书源。** 官方目录里的示例都是
结构模板，直接导入不会工作。

---

## 第三方依赖

Python 侧依赖清单以 `uv.lock` 为准，前端以 `desktop/package-lock.json` 为准。

当前直接依赖：

| 包 | 许可证 | 用途 |
|---|---|---|
| fastapi / starlette | MIT / BSD | HTTP 框架 |
| uvicorn | BSD | ASGI 服务器 |
| pydantic / pydantic-settings | MIT | 数据校验与配置 |
| sqlalchemy | MIT | ORM |
| httpx | BSD | HTTP 客户端 |
| lxml | BSD | HTML/XML 解析 |
| cssselect | BSD | CSS 选择器 |
| jsonpath-ng | Apache-2.0 | JSONPath |
| pyyaml | MIT | YAML 解析 |
| typer / rich | MIT | CLI |
| websockets | BSD | WebSocket 客户端 |
| pytest / ruff / mypy | MIT | 开发工具 |
| electron / vue / vite | MIT | 桌面端 |

全部为宽松许可，与 Apache-2.0 兼容。

**EPUB 生成没有引入第三方库** —— 用标准库 `zipfile` 手写（见 [ADR-009](../architecture/decisions.md)），
少一个依赖就少一份审查成本与打包体积。

---

## 发布前审查清单

- [ ] 对 `uv.lock` 与 `package-lock.json` 中的**全部**依赖逐项确认许可证
- [ ] 用 `pip-licenses` / `license-checker` 之类的工具生成许可证清单
- [ ] 确认兼容层中没有任何来自 Legado 仓库的代码片段
- [ ] 确认 `sources/official/` 里没有指向真实盗版站点的书源
- [ ] 确认 `NOTICE` 与实际依赖一致
- [ ] 确认 **Release 产物里带上了 `LICENSE` 与 `NOTICE`**（§4(a) / §4(d)）
- [ ] 确认各 `pyproject.toml` 的 `license` 与 `license-files` 与实际一致
- [ ] 确认 README 中的合规声明与实际行为一致
- [ ] 若计划上架应用商店，确认商店对"内容获取工具"的额外要求

---

## 相关文档

- 架构决策中的许可证考量 → [../architecture/decisions.md](../architecture/decisions.md)
- 安全边界 → [security.md](security.md)
- 兼容等级（哪些能力已实现） → [../source/compatibility-levels.md](../source/compatibility-levels.md)
