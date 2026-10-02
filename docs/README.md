# InkFlow 文档

> 本目录是 InkFlow 的**设计依据**。代码回答「怎么做」，这里回答「为什么这么做」
> 以及「改动时必须守住什么」。

## 阅读路径

**我是新加入的开发者** → [development/setup.md](development/setup.md) → [architecture/overview.md](architecture/overview.md) → [development/roadmap.md](development/roadmap.md)

**我要写一个书源** → [source/authoring.md](source/authoring.md) → [source/overview.md](source/overview.md)

**我要用 API / 做客户端** → [api/rest-api.md](api/rest-api.md) → [api/errors.md](api/errors.md) → [api/websocket.md](api/websocket.md)

**我要搞清楚 Legado 兼容边界** → [source/compatibility-levels.md](source/compatibility-levels.md) → [source/legado.md](source/legado.md)

**我在做安全 / 发布审查** → [development/security.md](development/security.md) → [development/licensing.md](development/licensing.md)

**我要发一个版本** → [development/cicd.md](development/cicd.md) → [development/setup.md](development/setup.md)

---

## 目录

### architecture — 架构

| 文档 | 内容 |
|---|---|
| [overview.md](architecture/overview.md) | 分层、依赖方向、数据流、模块职责 |
| [decisions.md](architecture/decisions.md) | 关键设计决策记录（ADR）与理由 |

### source — 书源体系

| 文档 | 内容 |
|---|---|
| [overview.md](source/overview.md) | Source Engine 的三级书源模型、规则 AST、HTTP 与限流 |
| [authoring.md](source/authoring.md) | 原生书源编写指南（含完整示例与调试方法） |
| [legado.md](source/legado.md) | Legado 兼容层的实现方式与规则语法映射 |
| [compatibility-levels.md](source/compatibility-levels.md) | L0~L3 兼容等级的定义与当前覆盖范围 |

### api — 接口

| 文档 | 内容 |
|---|---|
| [rest-api.md](api/rest-api.md) | 全部 REST 端点、请求/响应结构 |
| [errors.md](api/errors.md) | 错误码表与错误处理约定 |
| [websocket.md](api/websocket.md) | 下载进度的实时推送协议 |

### development — 开发

| 文档 | 内容 |
|---|---|
| [setup.md](development/setup.md) | 环境搭建、常用命令、版本号约定、排障 |
| [testing.md](development/testing.md) | 测试分层、mock 站点、如何写测试 |
| [cicd.md](development/cicd.md) | GitHub Actions 流水线、本地复现、发版步骤 |
| [roadmap.md](development/roadmap.md) | 里程碑划分与当前进度 |
| [security.md](development/security.md) | 威胁模型与防护措施 |
| [licensing.md](development/licensing.md) | 许可证选择、与 Legado 的关系、内容边界 |

---

## 文档约定

- 文档写**决策与约束**，不重复代码里显而易见的东西。接口签名看代码与 `/docs`。
- 每条关键决策在 [decisions.md](architecture/decisions.md) 里有一条 ADR，包含「背景 / 决策 / 后果」。
- 与实现不一致的文档视为 bug，改代码时同步改文档。
