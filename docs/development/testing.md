# 测试体系

## 分层

```text
tests/
├── unit/            纯逻辑，无 IO，毫秒级
│   ├── test_models.py            领域模型、状态机、归一化
│   ├── test_normalizer.py        正文清洗
│   ├── test_legado_compiler.py   规则编译
│   └── test_export.py            TXT / EPUB / Markdown
│
├── integration/     API 与适配器，走真实 HTTP（对 mock 站点）
│   ├── test_api.py               路由、鉴权、错误格式、书源导入
│   └── test_native_source.py     原生书源完整流程
│
├── source/          书源兼容性
│   └── test_legado_compat.py     L0 / L1 / 等级边界
│
├── fixtures/mock-site/           静态 HTML 夹具
├── mock_server.py                mock 书站
├── sources_data.py               测试书源定义（共享）
└── conftest.py                   全局夹具
```

按标记运行：

```bash
uv run pytest -m unit        # 只跑单元测试
uv run pytest -m integration
uv run pytest -m source
```

---

## 核心原则：不请求真实网站

**测试对着本地 mock 书站跑。** 理由：

- 站点改版会让 CI 整片红，而且原因与本次改动无关
- 真实站点有速率限制，跑一次全量测试可能被封
- 测试结果不可重复（内容会变）

mock 站点是标准库实现的只读 HTTP 服务（[`tests/mock_server.py`](../../tests/mock_server.py)），
把路径映射到 [`tests/fixtures/mock-site/`](../../tests/fixtures/mock-site/) 下的固定 HTML。

夹具刻意包含**脏数据**，用来验证清洗逻辑真的生效：

```html
<div class="ad">请记住本站域名：mock.example.com</div>
<div id="content">
  <p>汪淼觉得自己是在做梦。</p>
  <script>console.log('tracking')</script>
  <div class="ad-inline">手机用户请访问 m.mock.example.com</div>
  <p>电话是丁仪打来的。</p>
  <p>汪淼觉得自己是在做梦。</p>   <!-- 重复段落 -->
  ...
</div>
```

---

## 环境隔离

`conftest.py` 里的两个 autouse 夹具保证测试不碰用户环境：

### `_isolated_home`

把 `INKFLOW_HOME` 指向 `tmp_path`，因此测试不会读写真实的 `~/.inkflow`。

### `_clean_proxy_env`

**清除代理环境变量。** 开发机上若有 `http_proxy`，发往 `127.0.0.1` 的请求
会被代理转出去，症状是 mock 站点「连不上」—— 看起来像服务没起，其实是代理劫持。

---

## 数据库

测试用**临时文件**数据库，不是 `:memory:`：

```python
database_url = sqlite_url(paths.database_dir / "test.db")
```

> SQLite 的内存库是「每连接一个独立数据库」。SQLAlchemy 用连接池，
> 换一个连接就看不到表了，症状是随机的 `OperationalError: no such table`。
> 用 `StaticPool` 也能解决，但临时文件更接近真实运行环境。

---

## 写测试

### 单元测试

不需要任何夹具，直接构造对象：

```python
pytestmark = pytest.mark.unit


def test_normalize_book_name_strips_punctuation() -> None:
    assert normalize_book_name("《三体》") == normalize_book_name("三体")
```

### 集成测试

用 `client`（免鉴权）或 `authed_client`（带 token）：

```python
pytestmark = pytest.mark.integration


def test_import_native_source(client: TestClient, mock_site: str) -> None:
    response = client.post(
        "/api/v1/sources/import",
        json={"content": NATIVE_SOURCE.format(base=mock_site)},
    )
    assert response.status_code == 200
```

### 异步测试

`asyncio_mode = "auto"`，直接写 `async def` 即可：

```python
async def test_search(adapter) -> None:
    results = await adapter.search("三体")
    assert len(results) == 3
```

### 书源定义共享

测试书源定义放在 [`tests/sources_data.py`](../../tests/sources_data.py)，
API 测试与兼容性测试共用同一份 —— 否则两处会各自漂移，
测出来的东西就不是一回事了。

---

## 测试里踩过的坑

这些都是**真实发生过**的，写新测试时留意：

| 现象 | 原因 |
|---|---|
| YAML 解析失败 | 双引号字符串里 `\S` 是非法转义。正则用单引号：`regex: '第(\d+)章'` |
| `count: 0` 但无报错 | XPath 的 `@class="x"` 是精确匹配，节点上还有别的类名就匹配不上，要写 `contains(@class,'x')` |
| 目录永远为空 | `chapterName: "text"` 这类「只有取值动作」的规则被误判为空规则（已修，见 [legado.md](../source/legado.md)） |
| 随机的 `no such table` | 用了 `:memory:` 数据库 |
| 连接超时但服务正常 | 代理环境变量劫持了 `127.0.0.1` |
| 断言「原始数据里还有广告」失败 | 广告节点可能在正文容器**外面**，压根不在 `raw` 里 |

---

## 当前覆盖

```bash
uv run pytest -q
# 108 passed
```

| 层 | 数量 | 覆盖内容 |
|---|---|---|
| unit | 72 | 模型与状态机、归一化、正文清洗、规则编译（含各类语法分支）、三种导出器、EPUB 结构合法性 |
| integration | 25 | 全部路由、鉴权、错误结构、书源导入幂等、SSRF 拦截、原生书源完整流程 |
| source | 11 | Legado L0/L1、等级判定、JS 规则报错、规则失效报错、AST 调试接口 |

---

## 尚未覆盖

诚实地说，以下是当前测试的空白：

| 缺口 | 说明 |
|---|---|
| 下载任务的端到端测试 | 目前靠手动 E2E 验证（见 [roadmap.md](roadmap.md) 的验收记录），缺自动化 |
| WebSocket 进度推送 | 未写自动化测试，只做了手动验证 |
| 暂停 / 恢复 / 取消 | 状态机有单测，调度层没有 |
| 桌面端 | 无前端测试（`vue-tsc` 类型检查是唯一的静态保障） |
| 缓存层 | `HttpCache` 协议尚无默认实现，因此无测试 |
| 真实书源样本 | 只有 mock 站点，兼容性评分尚未建立 |

---

## CI

```text
push
 ↓
ruff check / ruff format --check
 ↓
mypy
 ↓
pytest（全部标记）
 ↓
构建（Python 包 + Electron）
```

本地用同一个入口，避免「本地过了 CI 挂」：

```bash
uv run python scripts/check.py
```

---

## 相关文档

- 环境搭建 → [setup.md](setup.md)
- 书源编写与调试 → [../source/authoring.md](../source/authoring.md)
