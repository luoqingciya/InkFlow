# 书源体系（Source Engine）

## 三级书源模型

InkFlow 支持三种书源，复杂度递增、能力递增：

| 级别 | 类型 | 形态 | 能力 |
|---|---|---|---|
| Level 1 | **Native Source** | 声明式 YAML | 静态页面：CSS / XPath / JSONPath / 正则 |
| Level 2 | **Legado JSON Source** | Legado 书源 JSON | 同上，且能复用庞大的既有书源生态 |
| Level 3 | **Legado JS / Browser** | 含 JS 或需浏览器 | 签名、加密、动态渲染、登录态（尚未实现） |

原生书源最容易维护、性能最高、可静态校验 —— **能写原生就别写 Legado**。

---

## 统一契约：SourceAdapter

```python
class SourceAdapter(Protocol):
    source: BookSource

    async def search(self, keyword: str, page: int = 1) -> list[BookResult]: ...
    async def book_info(self, book_url: str) -> BookResult: ...
    async def chapters(self, book_url: str) -> list[ChapterResult]: ...
    async def content(self, chapter_url: str) -> ContentResult: ...
    async def aclose(self) -> None: ...
```

实现约束：

- 方法**要么返回结果，要么抛 `InkFlowError`**，不允许返回 `None` 或吞掉异常。
- `chapters()` 返回的 `index` 必须从 0 连续递增，顺序即阅读顺序。
- 分页（目录 / 正文）由适配器负责翻页，且**必须有页数上限** ——
  规则写错时必须能停下来，否则会陷入死循环。

---

## 注册表与工厂：兼容层隔离点

`inkflow-source` 不认识任何具体书源类型。每种类型由自己的包注册：

```python
# inkflow-source 内部（原生）
register_native(registry, loader)

# inkflow-legado（可选依赖）
register_legado(registry, loader)
```

工厂签名是 `(BookSource, HttpClient | None) -> SourceAdapter`。
HTTP 客户端由注册表注入，这样全局配置（超时、并发上限、内网访问开关）
才能真正作用到每个书源 —— 否则适配器自己去读配置，全局设置就是摆设。

---

## HTTP 引擎

**Source Adapter 不得自行创建 HTTP 客户端。** 所有出站请求都经过 `HttpClient`，
才能保证超时、重试、限速、安全校验、缓存、日志口径一致。

关键行为：

| 行为 | 说明 |
|---|---|
| 重定向 | 默认 `follow_redirects=True`。站点 302 是常态，不跟随会拿到空正文，表现为「解析失败」实为「没拿到页面」 |
| 重试 | 只对**可恢复**错误重试：连接错误、超时、429、5xx。4xx（除 429）直接失败，重试只是浪费配额 |
| 退避 | 指数退避 + 抖动，避免多个 worker 在同一时刻集体重试；429 额外延长等待 |
| 编码 | Content-Type → `<meta charset>` → 逐候选试解（utf-8 / gb18030 / big5 / shift_jis）→ latin-1 兜底 |
| 安全 | 每次请求前做协议白名单 + 内网地址校验（见 [security.md](../development/security.md)） |

---

## 三级限流

```text
全局并发上限        保护本机资源
    ↓
域名并发上限        跨书源共享，保护目标站点
    ↓
书源并发上限        书源自带配置
    ↓
令牌桶              请求速率（每秒 N 次）
```

取**最严**的一级生效。书源配置只能收紧，不能放宽全局值 ——
否则一个写得激进的书源就能把整个进程拖垮。

---

## 解析原语

统一输出为 Python 原生类型，规则层不感知底层解析库：

| 模块 | 能力 |
|---|---|
| `parsers.html` | CSS Selector、XPath、文本/属性/HTML 取值、节点移除 |
| `parsers.json` | JSONPath 查询与类型转换 |
| `parsers.text` | 正则提取/替换、`{{key}}` 模板渲染 |

`parsers.html.element_to_text()` 会显式把 `<br>` 与块级标签转成换行 ——
直接用 `text_content()` 会把整章挤成一行。

---

## 正文清洗（ContentNormalizer）

```text
网页正文
  ↓  移除节点（script / style / 明确标注的广告容器）
  ↓  DOM → 文本（保留段落）
  ↓  逐行清理（零宽字符、首尾空白）
  ↓  广告行剔除（整行匹配，锚定行首）
  ↓  重复段落合并
  ↓  空行规范化
  ↓  首尾噪声裁剪
标准正文
```

两条重要的设计约束：

1. **广告行模式必须锚定整行。** 正文里出现「请记住，无论发生什么」不该被误删。
2. **短行的重复不去重。** 小说里连续出现三次「……」是正常表达。

清洗规则可以按书源追加（`NormalizeRules`），默认规则始终生效。
因为 `raw_content` 始终保留，**改清洗规则不需要重新抓取**。

---

## 搜索聚合与排序

```text
关键词
  ↓  并行请求多个 Source（单源失败不影响整体）
  ↓  按 (归一化书名, 归一化作者) 归并
  ↓  评分排序
返回
```

**去重但不合并。** 同一本书在三个来源命中时只返回一条 `SearchResult`，
但 `sources` 数组保留全部来源。不同来源的更新速度、章节数、正文质量、
可用性都不同，选择权属于用户。

评分维度（`score_book`）：标题匹配度、源权重、响应速度、信息完整度。
分数**只用于排序**，不代表内容质量，也不用于隐藏任何来源。

---

## 目录结构

```text
sources/
├── official/     随项目分发的书源（模板与已验证可用的）
├── community/    社区贡献（不入库，见 .gitignore）
└── test/         测试与调试用（含 mock 站点书源）
```

每个书源建议记录：`source_id`、`version`、`author`、`homepage`、
`license`、`last_updated`、`compatibility_level`。

---

## 相关文档

- 写一个原生书源 → [authoring.md](authoring.md)
- Legado 兼容细节 → [legado.md](legado.md)
- 兼容等级 → [compatibility-levels.md](compatibility-levels.md)
