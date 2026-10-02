# Legado 兼容层

## 定位

> **这是一个隔离的 Compatibility Runtime，不是 Legado 的二次实现。**

```text
InkFlow Core
      │
      ├── 自有代码
      │
      └── Legado Compatibility Layer（inkflow-legado）
              ├── 格式解析   schema.py
              ├── Rule Compiler   compiler.py
              └── Runtime Adapter  adapter.py
```

三条硬边界：

1. **不复制 Legado 项目的任何源代码。** 兼容层依据其公开的规则格式独立实现。
2. **不让 Legado 的规则语义渗进业务代码。** 业务层只认识 `SourceAdapter`。
3. **Legado 规则变化时只升级这一个包。** Core / API / CLI / Desktop 不受影响。

详见 [licensing.md](../development/licensing.md)。

---

## 数据流

```text
Legado 书源 JSON
      ↓  LegadoBookSource（Pydantic 校验，未知字段保留）
      ↓  LegadoRuleCompiler（DSL → AST）
   Rule 对象
      ↓  LegadoSourceAdapter（执行 + 统一为 inkflow_core 模型）
BookResult / ChapterResult / ContentResult
```

编译一次、多次执行：适配器构造时就编译好全部规则，执行阶段不再解析字符串。

---

## 规则语法映射

### 选择器

| Legado 写法 | 含义 | 编译结果 |
|---|---|---|
| `class.book-item` | 类选择器 | `.book-item` |
| `tag.a` | 标签 | `a` |
| `id.content` | ID | `#content` |
| `tag.div.highlight` | 标签 + 类 | `div.highlight` |
| `class.a@tag.b` | 逐级下钻 | `['.a', 'b']` |
| `@css:...` | 强制 CSS | 整段作为 CSS |
| `@XPath:...` | 强制 XPath | 整段作为 XPath |
| `@json:$.a.b` | JSONPath | 走 JSON 求值分支 |
| `@js:...` | JavaScript | 标记为 L2，执行时抛错 |

### 取值动作

规则末段会被识别为取值动作：

| 写法 | 含义 |
|---|---|
| `text` / `textNodes` | 元素文本（折叠空白） |
| `ownText` | 仅元素自身的直接文本 |
| `html` / `all` | 元素 HTML |
| `href` / `src` / `data-src` | 属性值，且自动转绝对地址 |
| 任意属性名 | 取该属性 |

**识别规则**（`compiler.py`）：

- 规则只有一段时，仅当它是**明确的取值动作**（如 `text` / `href`）才算 ——
  这类写法表示「作用于元素自身」，在 `chapterName` / `chapterUrl` 里非常常见。
- 规则有多段时，末段只要长得像属性名就算，因为选择器不会写成裸单词。

> 这条判断曾经出过 bug：把「只有取值动作没有选择器」的规则判定为空规则，
> 导致所有 Legado 目录规则的 `chapterName` / `chapterUrl` 被丢弃，目录永远是空的。
> 现在 `Rule.is_empty` 以**原始规则串是否为空**为唯一依据。

### 正则替换与备选

```text
class.author@text##作者：##        → 取文本后把「作者：」替换为空
class.a@tag.a@text||tag.b@text     → 第一条无结果时用第二条
```

替换段在切分选择器**之前**就被隔离，因此替换内容里出现 `@` 或 `|` 不会干扰解析。

---

## 字段映射

| Legado 字段 | InkFlow 模型 |
|---|---|
| `ruleSearch.bookList` | 搜索结果的条目选择器 |
| `ruleSearch.name` / `author` / `kind` / `intro` / `coverUrl` / `bookUrl` / `lastChapter` / `wordCount` | `BookResult` 对应字段 |
| `ruleBookInfo.*` | `BookResult` |
| `ruleBookInfo.tocUrl` | 目录页地址（从详情页取） |
| `ruleToc.chapterList` | 目录条目选择器 |
| `ruleToc.chapterName` / `chapterUrl` / `isVip` | `ChapterResult` |
| `ruleToc.nextTocUrl` | 目录翻页 |
| `ruleContent.content` | 正文容器 |
| `ruleContent.nextContentUrl` | 正文翻页 |
| `searchUrl` | 搜索地址模板（支持 `{{key}}` / `{{page}}`） |
| `header` | 请求头（JSON 字符串，解析失败退化为空） |
| `customOrder` | 书源优先级 |
| `concurrentRate` | 并发数（形如 `"3/1000"`，只取并发数） |

---

## 容错策略

书源生态里存在大量不规范的写法，严格校验会让用户的书源根本导不进来。
因此在**不影响正确性**的地方一律宽容：

| 情况 | 处理 |
|---|---|
| 未知字段 | 保留（`extra="allow"`），不报错 |
| `header` 是半截 JSON | 退化为空字典 |
| 正则语法错误 | 跳过该条替换，保留原值 |
| 规则为空 | 视为「未配置」，不参与求值 |

但在**影响正确性**的地方一律严格 —— 失败必须看得见：

| 情况 | 处理 |
|---|---|
| 规则含 `@js:` / `<js>` | 抛 `SOURCE_EXECUTION_ERROR`，明确说明需要 L2 |
| 正文规则匹配不到内容 | 抛 `CONTENT_PARSE_FAILED`，带上规则原文 |
| 目录页请求失败 | 抛 `CHAPTER_PARSE_FAILED` |

静默返回空结果是最糟的处理方式 —— 用户会以为是「网站挂了」，
而不是「这个书源需要更高兼容等级」。

---

## 尚未支持

| 能力 | 等级 | 说明 |
|---|---|---|
| JS 规则（`@js:` / `<js>`） | L2 | 需要独立 JS 沙箱运行时 |
| 登录态 / Cookie 注入 | L3 | 需要浏览器上下文 |
| 浏览器渲染（`webView`） | L3 | 需要 Chromium 运行时 |
| `ruleSearch.init` / `ruleBookInfo.init` | — | 详情页预处理规则 |
| 复杂的 URL 选项（POST body 模板） | 部分 | `url,{json}` 的基础形式已支持 |

遇到未支持的能力时，适配器会**明确报错并指出所需等级**，而不是静默降级。

---

## 测试

兼容性测试集位于 [`tests/source/`](../../tests/source/)，对着 mock 站点
（[`tests/mock_server.py`](../../tests/mock_server.py)）运行，不依赖真实网站。

```bash
uv run pytest tests/source -v
```

覆盖内容：

- L0：结构解析、未知字段保留、破损 `header` 容错、等级判定、稳定 ID
- L1：搜索、详情（含正则替换）、目录（含分页与「元素自身」规则）、正文清洗
- 等级边界：JS 规则报错、规则失效报错、AST 可被调试接口读取

详见 [compatibility-levels.md](compatibility-levels.md)。
