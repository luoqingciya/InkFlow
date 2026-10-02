# Legado 兼容等级

## 为什么分级

Legado 书源生态里，能力的跨度非常大：从纯 CSS 选择器到依赖 `fetch`、加密签名、
浏览器渲染的复杂书源都有。如果一开始就承诺「100% 兼容」，结果是大部分书源
跑不通，而且**用户不知道是哪一步跑不通**。

分级的意义是：**让「能跑到哪一步」变成可预期的、可检查的事实。**

---

## 等级定义

| 等级 | 能力 | 典型书源 |
|---|---|---|
| **L0** | 能读取 Legado JSON 结构 | 所有 Legado 书源 |
| **L1** | CSS / XPath / JSONPath / 正则规则可执行 | 静态站点书源（占绝大多数） |
| **L2** | Legado JS Source 可在沙箱中执行 | 需要签名、加密、多步请求的书源 |
| **L3** | 浏览器 / Cookie / 登录环境 | 动态渲染、需要登录的站点 |

等级是**有序**的：L2 书源同时满足 L0 与 L1。

---

## 当前覆盖

```text
L0  ✅ 已实现
L1  ✅ 已实现
L2  ⬜ 未实现（Milestone 3）
L3  ⬜ 未实现（Milestone 4）
```

**当前版本覆盖 L0 + L1。**

---

## 等级如何判定

导入书源时自动判定（`inkflow_legado.detect_level`）：

```text
书源规则里出现 webView 等浏览器指令  →  L3
书源规则里出现 @js: / <js> / java.   →  L2
规则非空且不含上述特征               →  L1
规则全为空                           →  L0
```

判定结果写入 `BookSource.compatibility_level`，可以在书源列表里看到：

```bash
inkflow sources list
```

```text
┌──────────────────────┬───────────┬────────┬────────┬──────┬──────┐
│ ID                   │ 名称      │ 类型   │ 等级   │ 启用 │ 搜索 │
├──────────────────────┼───────────┼────────┼────────┼──────┼──────┤
│ src_72b0e86b156f08eb │ Mock 书站 │ native │ native │ ✓    │ ✓    │
└──────────────────────┴───────────┴────────┴────────┴──────┴──────┘
```

---

## 未达等级的运行时行为

**绝不静默降级。** 遇到超出当前等级的能力时，适配器抛出明确错误：

```json
{
  "error": {
    "code": "SOURCE_EXECUTION_ERROR",
    "message": "正文 规则包含 JavaScript，需要 L2 兼容等级（当前版本未实现）",
    "details": {
      "source_id": "src_xxx",
      "rule": "@js:result.replace(/广告/g,'')",
      "required_level": "L2"
    },
    "trace_id": "..."
  }
}
```

这样用户能立刻判断：是书源坏了，还是兼容等级不够。

---

## 路线图

| 里程碑 | 内容 |
|---|---|
| Milestone 1（MVP） | L0 + L1 |
| Milestone 3 | L2：Node.js sidecar 沙箱，支持 Promise / fetch / DOM / Cookie / 变量上下文 |
| Milestone 4 | L3：浏览器运行时（Playwright 或 Electron），支持渲染、登录态、Cookie |

设计约束（现在就要守住）：

- **JS 不得运行在 Python 主进程里。** 走独立 sidecar，通过 JSON-RPC 通信。
- **JS 是第三方代码。** 必须限制超时、内存、请求数、响应体积，
  并禁止文件系统、子进程、native module。
- **浏览器能力只在书源明确要求时启用**，不作为默认路径。

---

## 兼容性评分

维护官方兼容性测试集：

```text
tests/source/
├── test_legado_compat.py     L0 / L1 / 等级边界
└── fixtures/mock-site/       本地 mock 书站
```

测试**不请求真实网站** —— 站点一改版 CI 就整片红，而且不可重复。

将来引入真实书源样本后，会产出 `Source Compatibility Score`：

```text
Score = 通过的测试项 / 总测试项
```

> 这个分数只作为**测试覆盖指标**，不是产品里的「书源排名」。
> 产品不排名书源 —— 不同来源的可用性会随时间变化，排序结果没有稳定含义。

---

## 相关文档

- 兼容层实现方式 → [legado.md](legado.md)
- 写原生书源（比 Legado 更可控） → [authoring.md](authoring.md)
