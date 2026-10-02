# 测试体系

## 分层

```text
tests/
├── unit/            纯逻辑，无 IO，毫秒级
│   ├── test_models.py            领域模型、状态机、归一化
│   ├── test_normalizer.py        正文清洗
│   ├── test_legado_compiler.py   规则编译
│   ├── test_export.py            TXT / EPUB / Markdown
│   └── test_log.py               日志落盘 / 轮转 / JSON Lines
│
├── integration/     API 与适配器，走真实 HTTP（对 mock 站点）
│   ├── test_api.py               路由、鉴权、错误格式、书源导入
│   ├── test_native_source.py     原生书源完整流程
│   ├── test_download.py          下载任务全链路（含重试 / 暂停 / 取消）
│   ├── test_cache.py             HTTP 缓存（存取 / 过期 / LRU 淘汰 / 只缓存 GET）
│   └── test_websocket.py         进度推送（含真实 uvicorn 流式验证）
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

### 下载任务测试

`library` 夹具已经把「导入书源 → 搜索 → 抓目录」准备好：
`.client` 是测试客户端，`.book_id` 是那本备好目录的书。

```python
def test_download(library: _Library) -> None:
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)
    assert task["status"] == "COMPLETED"
```

**别用 `sleep`，用 `wait_for_terminal`。** 下载是异步的，`POST /tasks`
返回时任务才刚 `PENDING`；拍脑袋睡一个时长，快了会假红、慢了会拖慢 CI。

`library` 为什么必须带着 `book_id` 一起给：搜索会把 mock 站点的三本书
（三体 / 三体 II / 三体 III）**全部**入库，而夹具只给「三体」抓了目录。
**走 `/api/v1/books` 列表拿第一本是错的** —— 那按更新时间倒序，返回的是
「三体 III」，它没有目录，建任务会直接 502。

### 注入失败：`flaky` 夹具

要测重试、失败隔离这类路径，用 `flaky` 让指定章节失败 N 次：

```python
def test_retry(library: _Library, flaky, state):
    state.settings.download.retry_backoff = 0  # 测试里不等退避
    adapter = flaky({"2": 1})  # /chapter/2 失败一次

    task_id = ...  # 建任务、等终态
    assert adapter.calls.count("2") == 2  # 一次失败 + 一次重试
```

键是章节 URL 的**尾段数字**（mock 站点是 1-based 的 `/chapter/1`…`/chapter/6`）。

### 异步测试

`asyncio_mode = "auto"`，直接写 `async def` 即可：

```python
async def test_search(adapter) -> None:
    results = await adapter.search("三体")
    assert len(results) == 3
```

### WebSocket 测试：两套驱动方式

**这是本项目最容易踩的一个坑。** `TestClient` 看起来最方便，但它每个
HTTP 请求都会新起一个 anyio portal（一个全新的事件循环），请求返回后
循环即销毁；WebSocket 会话也跑在自己的 portal 里。于是
「用 REST 启动任务、再用 WebSocket 收进度」这种真实用法在 `TestClient`
下**永远收不到事件** —— 下载协程和 WS 不在同一个循环里，测试会挂死。

所以 `test_websocket.py` 里分成两组：

| 场景 | 驱动方式 |
|---|---|
| 快照形状、鉴权、任务不存在、连接关闭、Broker 语义 | `TestClient`（便宜） |
| 真的收到 progress / completed / status 的流式用例 | `live_server` 夹具：后台线程跑真实 uvicorn + `websockets` 客户端 |

`live_server` 让 REST 与 WebSocket 共享同一事件循环，这才是线上跑的样子。

另外注意：**WebSocket 鉴权失败发生在握手阶段**，`websocket_connect`
本身就抛 `WebSocketDisconnect(code=4401)`，不是进去之后再收一条错误消息。

### 缓存测试：怎么证明「真的省掉了一次请求」

`test_cache.py` 里最容易写虚的一条是「命中缓存」。只断言
`from_cache is True` 是不够的 —— 那个标志是我们在
`SqliteHttpCache.get()` 里自己设的，设错了测试照样绿。

有说服力的做法是**把 mock 站点关掉之后再取一次**：

```python
first = await client.get(f"{site.url}/book/1")
site.stop()  # 站点下线
second = await client.get(f"{site.url}/book/1")
assert second.from_cache is True
```

缓存没生效的话，第二次会因连接失败抛 `SourceError`，测试立刻红。

几条容易踩的边界：

- **`ttl=0` 是「立即过期」，不是「永不过期」。** 写 `if ttl:` 会把 0
  也判成假值，于是落进「不过期」分支。要显式区分 `None` 与 `0`。
- **`ttl=None` 才是永不过期**，两者语义不同。
- **LRU 的排序键是 `coalesce(hit_at, created_at)`** —— 从未命中的条目
  按写入时间排，所以测淘汰顺序时要控制时间。测试里用 `monkeypatch`
  替换 `inkflow_api.services.cache.utcnow`，比 `sleep` 可靠且快。

### 日志测试：为什么不能只断言「函数被调用了」

`test_log.py` 的核心断言是**真的写一条日志，再从文件里读回来**：

```python
setup_logging(LogConfig(), tmp_path)
logging.getLogger("inkflow.test").warning("落盘测试")
assert "落盘测试" in (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
```

只断言「handler 被加上了」是不够的 —— handler 加上了但级别不对、编码不对、
或者 uvicorn 把日志截走了，测试照样绿，而线上就是没日志。

几条容易踩的边界：

- **root logger 是进程级状态**，必须用 autouse fixture 还原 handler，
  否则前一个用例的 handler 会把后一个用例的日志写进它的临时目录。
  模块级的 `_file_handler` 也要一起重置，否则幂等判断会误判。
- **`delay=True` 意味着没日志就不产生文件** —— 有专门用例断言这一点，
  免得将来有人去掉 delay，变成每次启动都留一个空文件。
- **轮转要真的写超上限**（写 1.2MB 越过 1MB 阈值）。只读 `maxBytes`
  配置值证明不了轮转真的会发生。
- **中文往返要单独测**：Windows 默认 cp1252，没显式指定编码时
  中文会乱码甚至抛 `UnicodeEncodeError`。

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
| WebSocket 测试挂死 | 用 `TestClient` 想收流式事件 —— REST 与 WS 不在同一事件循环（见上方「两套驱动方式」） |
| `zipfile.BadZipFile` 偶发 | 导出在 `asyncio.to_thread` 里跑，DB 里的 `output_path` 可能早于字节落盘。用 `_open_zip_when_ready` 轮询 |
| 拿到没有目录的书 | `library` 夹具别用 `/api/v1/books` 第一本，搜索会入库 3 本 |
| 全量 `pytest` 偶发 exit 1，但**没有 `F`**、也没有 summary | pytest teardown 删 `%TEMP%\pytest-of-*\garbage-*` 时被环境的批量删除保护拦下。**测试是全绿的** |
| `--basetemp=` 指向**项目目录内** → 稳定 `151 errors` | 守门器把 basetemp 下的 `…current` 符号链接解析成整个工作区，报「上千个文件」直接 `SystemExit(1)`，连 fixture setup 都进不去 |

> 这两条值得单独说：**退出码不一定来自测试失败。**
> 遇到「偶发红、单独跑却全过」时，先确认 stdout 里到底有没有 `F` ——
> 没有 `F` 就该去查退出码的其他来源，而不是反复重跑碰运气。
>
> 本机跑全量的稳妥方式是把临时目录放在**工作区之外**：
>
> ```bash
> uv run pytest -p no:cacheprovider --basetemp="$TEMP/inkflow_pt_$RANDOM"
> ```
>
> （`--basetemp` 千万别指向仓库内目录，会触发上表中的第二条。）

---

## 当前覆盖

```bash
uv run pytest -q
# 208 passed
```

| 层 | 数量 | 覆盖内容 |
|---|---|---|
| unit | 83 | 模型与状态机、归一化、正文清洗、规则编译（含各类语法分支）、三种导出器、EPUB 结构合法性、**日志落盘与轮转** |
| integration | 112 | 全部路由、鉴权、错误结构、书源导入幂等、SSRF 拦截、原生书源完整流程、**下载任务全链路**、**HTTP 缓存**、**WebSocket 进度推送** |
| source | 13 | Legado L0/L1、等级判定、JS 规则报错、规则失效报错、AST 调试接口 |

按文件看：

| 文件 | 数量 |
|---|---|
| `unit/test_legado_compiler.py` | 22 |
| `unit/test_log.py` | 19 |
| `unit/test_export.py` | 17 |
| `unit/test_models.py` | 15 |
| `unit/test_normalizer.py` | 10 |
| `integration/test_download.py` | 33 |
| `integration/test_cache.py` | 32 |
| `integration/test_api.py` | 19 |
| `integration/test_websocket.py` | 16 |
| `source/test_legado_compat.py` | 13 |
| `integration/test_native_source.py` | 12 |

---

## 尚未覆盖

诚实地说，以下是当前测试的空白：

| 缺口 | 说明 |
|---|---|
| 桌面端 | 无前端测试（`vue-tsc` 类型检查是唯一的静态保障） |
| 真实书源样本 | 只有 mock 站点，兼容性评分尚未建立 |
| 缓存的长期运行 | 容量淘汰只在测试里验证过，未在真实使用中跑过 |
| 日志的长期运行 | 轮转只在单测里触发过一次，未在长时间运行中验证 |

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
