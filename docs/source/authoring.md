# 原生书源编写指南

原生书源（Level 1）用声明式 YAML 描述「请求什么、从哪里取什么」，不含代码。

参考模板：[`sources/official/example.yaml`](../../sources/official/example.yaml)

---

## 最小可用书源

```yaml
name: Example 书源
url: https://example.com

search:
  url: /search
  params:
    q: "{{key}}"
  list:
    selector: div.book-item
    fields:
      name: { selector: "h3 a", attr: text }
      book_url: { selector: "h3 a", attr: "@href", absolute: true }

toc:
  url: "{{bookUrl}}"
  list:
    selector: "ul#chapter-list li a"
    fields:
      name: { selector: "", attr: text }
      url: { selector: "", attr: "@href", absolute: true }

content:
  url: "{{chapterUrl}}"
  selector: "div#content"
```

导入并验证：

```bash
inkflow sources import sources/official/example.yaml
inkflow sources test <source-id> --kind search --keyword 三体
inkflow sources test <source-id> --kind toc --url https://example.com/book/1
inkflow sources test <source-id> --kind content --url https://example.com/chapter/1
```

---

## 字段取值语法

每个字段是一个 `FieldSpec`：

```yaml
name:
  selector: "h3 a"        # CSS，或以 / 开头的 XPath；留空表示「当前元素自身」
  attr: text              # text | html | @属性名
  regex: '第(\d+)章'      # 可选：取值后再提取一次
  regex_group: 1          # 可选：分组序号或名称
  absolute: false         # 可选：相对 URL 转绝对
  default: ""             # 可选：取不到时的兜底值
```

### `attr` 的取值

| 写法 | 含义 |
|---|---|
| `text` | 元素的纯文本，已折叠空白 |
| `html` | 元素的内部 HTML |
| `@href` / `@src` / `@data-id` | 取属性值 |
| `href` / `src`（不带 `@`） | 同上，容错写法 |

`href` / `src` / `data-src` / `data-original` 会自动转成绝对地址。

### `selector` 的写法

- CSS：`div#content`、`ul.chapter-list > li > a`
- XPath：以 `/` 或 `(` 开头，如 `//div[@id="content"]`
- 留空：作用于当前元素自身（目录条目、正文容器这类场景很常用）

> XPath 里 `@class="book-item"` 是**精确**匹配。节点上还有别的类名
> （如 `class="book-item odd"`）就匹配不上，要写
> `contains(@class,'book-item')`。

---

## URL 模板

支持 `{{key}}`（关键词）、`{{page}}`（页码）、`{{page0}}`（页码从 0 起），
以及调用方传入的 `{{bookUrl}}` / `{{chapterUrl}}`。

地址解析规则（`_resolve`）：

| 模板 | 结果 |
|---|---|
| 留空 | 用调用方传入的地址 |
| `https://...` 绝对地址 | 原样使用 |
| `/search` 相对地址 | 相对调用方传入的地址拼接 |

---

## 分页

目录与正文都支持自动翻页，**必须配 `next_page` 与 `max_pages`**：

```yaml
toc:
  url: "{{bookUrl}}"
  next_page: "a.next-page"    # 下一页链接的选择器
  max_pages: 20               # 页数上限，防止规则写错时死循环
  list: { ... }

content:
  url: "{{chapterUrl}}"
  selector: "div#content"
  next_page: "a.next-content"
  max_pages: 20
  strip: ["script", "style", "div.ad"]
```

适配器会自动拼接分页正文，并按 URL 去重、防止下一页指回自己。

---

## 正文清洗

`content.strip` 里的选择器会在提取前被移除：

```yaml
content:
  selector: "div#content"
  strip:
    - "script"
    - "style"
    - "div.ad"
    - "div.ad-inline"
```

除此之外，`ContentNormalizer` 还会自动：

- 移除 `script` / `style` / `noscript` / `iframe` / `svg`
- 移除常见广告容器（`.ad` / `.ads` / `.advert` / `[class^='ad-']` 等）
- 剔除整行匹配的推广文案（「请记住本站…」「手机用户请访问…」等）
- 合并重复段落、折叠多余空行、裁剪首尾噪声

**清洗前的内容始终保存在 `raw_content`**，因此改清洗规则不需要重新抓取。

---

## 请求层配置

```yaml
concurrency: 3              # 并发上限（只能收紧全局值）
requests_per_second: 2      # 每秒请求数
timeout: 20
retry: 3
headers:
  Referer: https://example.com/
user_agent: "Mozilla/5.0 ..."
```

---

## 调试方法

### 1. 看规则有没有匹配上

```bash
inkflow sources test <source-id> --kind toc --url https://example.com/book/1
```

返回里会带 `count`（匹配到的条目数）与 `preview`（前 5 条结果）。
`count: 0` 说明选择器没匹配上。

### 2. 看编译后的规则结构

```bash
inkflow sources rules <source-id>
```

对原生书源返回其声明式规格；对 Legado 书源返回编译后的 AST。

### 3. 对着 mock 站点跑

```bash
# 终端 1
uv run python -m tests.mock_server --port 8765

# 终端 2
inkflow sources import sources/test/mock-site.yaml
inkflow sources test <source-id> --kind search --keyword 三体
```

注意 mock 站点监听 `127.0.0.1`，需要在 `config.toml` 里设
`source.allow_private_network = true`，否则会被 SSRF 防护拦下。

---

## 常见问题

| 症状 | 原因 |
|---|---|
| `count: 0`，无报错 | 选择器没匹配上。检查是 CSS 还是 XPath 写法，以及是否漏了 `tag.` / `class.` 前缀（Legado 语法） |
| `CONTENT_PARSE_FAILED` | 正文容器选择器失效，或站点改版 |
| `SOURCE_BLOCKED` | URL 指向内网 / 回环地址，且未开启 `allow_private_network` |
| `SOURCE_TIMEOUT` | 目标站点慢或不可达；调大 `timeout`，或检查是否需要代理 |
| 正文挤成一行 | 站点用 `<div>` 而非 `<p>` 分段，且没有 `<br>`。清洗器只能按现有结构还原段落 |
| 章节顺序乱 | 目录页本身顺序即阅读顺序，`index` 由遍历顺序决定；站点若倒序排列需要单独处理 |
| YAML 解析失败 | 双引号字符串里的 `\S` 是非法转义，正则请用单引号：`regex: '第(\d+)章'` |
