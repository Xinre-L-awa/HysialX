# M5 教程：反向 WebSocket 服务端 + HTTP 兜底通道

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。
>
> 本教程接你现在的代码继续写：[snowluma/connection.py](snowluma/connection.py)（M4 已完成正向 WS 与动作调用）、
> [snowluma/config.py](snowluma/config.py)、[tests/mock_snowluma.py](tests/mock_snowluma.py)、
> [tests/test_connection.py](tests/test_connection.py)。
> 文中 `【实测】` 是我在本机（Python 3.12.10 / websockets 16.0 / httpx 0.28.1）跑出来的结论，
> `【源码】` 是读本机安装的 websockets 源码得到的结论，可以直接当验收依据。
>
> ⚠️ **核对现状（重要）**：§4 的四处改动（`Channel.role`、`start()`/`stop()` 接线、
> `_reverse_server_loop` / `_process_reverse_request` / `_reverse_handler`、`_call_http` 真实现）
> **都已落地**。但 §7 的测试只落地了一部分：
> - §7.1 的 `MockReverseClient` 类**没有进 `tests/mock_snowluma.py`**（现行 `tests/test_reverse.py`
>   直接用 `websockets.connect` + 一个 `echo_reader` 协程，更短）；
> - §7.2 的用例文件叫 **`tests/test_reverse.py`**（不是 `test_reverse_http.py`），
>   覆盖 `_process_reverse_request` 鉴权、`_reverse_handler` 接入、反向收事件、反向发动作、401 拒绝；
> - §7.3 的「翻转 B9」**没有做**：`tests/test_connection.py` 里 B9 仍是「无通道 + auto 抛
>   `ConnectionUnavailable`」（因为 `stop()` 已经把 `_http` 关掉，`_call_http` 里
>   `self._http is None` → 抛同一类异常）。D 组（HTTP 兜底）目前**没有专门用例**。

---

## 0. 本节要交付什么

| # | 任务 | 落点 |
| --- | --- | --- |
| 15 | 反向 WS 服务端：`websockets.serve` + 握手 token 校验（401）+ 多连接 | `snowluma/connection.py` |
| 16 | HTTP 兜底：`httpx.AsyncClient` + Bearer + `POST /{action}` + 信封解析 | 同上 |
| — | 把两条通道接进生命周期（`start()` 起服务、`stop()` 干净收尾） | 同上 |
| — | 补测试：反向接入用例（C 组）+ HTTP 兜底断言（D 组） | `tests/` |

**完成标志**：C 组 6 项 + D 组 6 项断言全绿；M4 的 A/B 组保持全绿（只有 B9 的期望值要改）。

> **现状核对**：`tests/test_reverse.py` 已覆盖 C1/C2/C3/C4/C5 的核心路径（鉴权、接入、
> 收事件、发动作、401）；**C6（两条反向连接互不影响）与整个 D 组仍是用例待补**
> —— 现行 `tests/test_connection.py` 的 B9 还保持"auto 抛异常"的旧期望，所以 D1 也没翻转。

---

## 1. 先把数据流想清楚

```
        ┌──────────── 正向（M4 已完成）────────────┐
HysialX │  websockets.connect → SnowLuma:3001      │
        └──────────────────────────────────────────┘

        ┌──────────── 反向（本节要加）─────────────┐
SnowLuma│  wsClients 主动拨号 → HysialX:6700       │
        └──────────────────────────────────────────┘
```

关键认识：**一条 WebSocket 连接是双向复用的**——SnowLuma 在它上面推事件，我们也能在它上面发动作
（`{"action":..., "params":..., "echo":...}`）。所以反向通道进入 `_channels` 之后，M4 写好的
`_pick_channel / _call_ws / _pump / _handle_payload` **一行都不用改**，这是 M5 最省事的地方：

```
_reverse_handler(connection)   ← 本节新增，只做「注册通道 + _pump」
        ↓ 复用
_pump → _handle_payload → event_queue / _pending[echo] → _unwrap
```

**不要**为反向通道另写一套读循环或应答匹配逻辑。

### 1.1 角色（role）—— 一个容易被忽略的坑

SnowLuma 的 `wsClients` 支持 `role`：`Api`（只发动作）/ `Event`（只推事件）/ `Universal`（都行）。
事件专用通道收不到动作应答，所以：

* 建议 `Channel` 上加一个 `role` 字段；
* `_pick_channel()` 挑动作通道时**跳过 `event` 角色的通道**，优先 `universal`/正向；
* role 从哪来：OneBot 11 规范建议反向连接握手时带 `X-Client-Role` 头（还有 `X-Self-ID`）。
  这是**规范约定**，不是我从 SnowLuma 源码逐行确认过的行为——第一次联调时把这行加上就能确认：

  ```python
  logger.info(f"反向握手: path={request.path} headers={dict(request.headers)}")
  ```

  读不到就按 `Universal` 处理（保守但可用）。

多账号（`X-Self-ID` 各不相同）属于后续工作：你现在的 `self.self_id` 是单个字段，
反向若接入多个账号，动作会发到任意一条通道上。M5 只需在 `Channel` 上记录 `self_id`，
把「按账号挑通道」留到以后。

---

## 2. websockets 16 的 API 事实（先看这节，能省你两小时）

| 事实 | 说明 |
| --- | --- |
| handler **只能有一个参数** | `async def handler(connection)`【源码 `server.py:376`：`await self.handler(connection)`】【实测】写成 `(ws, path)` 在 `serve()` 时不报错，**连接建立时**才炸：`TypeError: ... missing 1 required positional argument: 'path'` → 客户端收到 1011 |
| `process_request(connection, request)` | 可同步可异步（库会判断返回值是否 awaitable）【源码 `server.py:145-149`】；返回 `None` = 放行，返回 `Response` = 拒绝握手；**抛异常** → 回 500 |
| 拒绝握手 | `return connection.respond(401, "Unauthorized\n")`【源码 `server.py:93-112`】= `protocol.reject(status, text)`；拒绝后 **handler 不会被调用** |
| `request.path` / `request.headers` | `path` 含查询串；`headers` 是大小写不敏感的 `Headers`【实测】 |
| `connection.request` 在 handler 里仍可用 | 握手时 `self.request = event` 且之后不清空【源码 `server.py:215-218`】——所以在 handler 里还能读 headers，不必自己传参 |
| `ServerConnection` 有 `__dict__` | 可以直接 `connection.xxx = ...` 挂自定义属性【实测】 |
| `Server.close(close_connections=True, code=1001)` | 会拒绝未完成握手的连接（503）并给活着的连接发 1001，然后等 handler 退出【源码 `server.py:408-437`】 |
| ⚠️ `await server.serve_forever()` 是陷阱 | 见下面 §3 |
| httpx `base_url` 合并 | `base_url="http://h:3000/api"` + `url="/send_msg"` → `http://h:3000/api/send_msg`（前导 `/` **不会**丢掉 base 的路径，和 `urljoin` 不同）【实测】。你已有 `config.http_url()`，直接用它最省事 |
| `AsyncClient` 生命周期 | 必须在事件循环里创建，退出时 `await client.aclose()`；否则连接泄漏 / `ResourceWarning` |

---

## 3. ⚠️ 必须避开的陷阱：`serve_forever()` 会让 `stop()` 永久卡住

这是本节最值钱的一条。本机实测（客户端全程保持连接，然后取消服务端任务）：

| 写法 | 结果 |
| --- | --- |
| A：`async with websockets.serve(...): await asyncio.Future()` | 取消后 **0.01s** 正常结束 ✅ |
| B：`server = await websockets.serve(...); await server.serve_forever()` | 取消后 **>2s 仍未结束（挂死）** ❌ |
| C：B + `except CancelledError: server.close(); await server.wait_closed()` | **同样挂死**（`except` 根本轮不到执行）❌ |

原因【源码】：

1. `websockets.Server.serve_forever()` 只是转发给 `asyncio.Server.serve_forever()`；
2. `asyncio.Server.serve_forever()` 捕获 `CancelledError` 后调用的是 **asyncio 的** `close()`，
   它**不会关闭已有连接**，紧接着 `await self.wait_closed()`——而 `wait_closed()` 要等
   `_active_count == 0` 才返回，客户端还连着就永远不返回（`base_events.py:359-378`）；
3. 相比之下 `async with websockets.serve(...)` 的 `__aexit__` 调的是 **websockets 自己的**
   `Server.close()`，它会主动给连接发 1001、等 handler 退出，所以能立刻收尾。

**结论：反向服务端一律用 `async with websockets.serve(...)`，内部用 `await asyncio.Future()`
（或你自己的 `asyncio.Event().wait()`）保持监听，别用 `serve_forever()`。**

想自己复现/回归这条，把下面这段存成临时脚本跑一次（客户端全程保持连接）：

```python
import asyncio, time, websockets

async def handler(conn):
    try:
        async for _ in conn:
            pass
    except Exception:
        pass

async def variant_context_manager(port):          # A
    async with websockets.serve(handler, "127.0.0.1", port):
        await asyncio.Future()

async def variant_serve_forever(port):            # B
    server = await websockets.serve(handler, "127.0.0.1", port)
    await server.serve_forever()

async def case(name, target, port):
    task = asyncio.create_task(target(port))
    await asyncio.sleep(0.3)
    client = await websockets.connect(f"ws://127.0.0.1:{port}/")   # 保持连接
    await asyncio.sleep(0.2)
    started = time.monotonic()
    task.cancel()
    done, pending = await asyncio.wait({task}, timeout=2.0)        # 注意别用 wait_for：它会重抛 CancelledError
    print(f"[{name}] {'挂死' if pending else f'{time.monotonic() - started:.2f}s 结束'}")
    if pending:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await client.close()

asyncio.run(case("A async with", variant_context_manager, 18991))
asyncio.run(case("B serve_forever", variant_serve_forever, 18992))
```

对你的代码意味着：现在的 `stop()` 是「先取消全部任务，再关通道」。如果用了 B 写法，
`await asyncio.gather(*self._tasks, ...)` 会永久卡住，`stop()` 后面的关通道、`_fail_pending` 都执行不到。
用 A 写法就没这个问题。

---

## 4. 改 `snowluma/connection.py`（4 处）

### 4.1 `Channel` 加 `role`（可选但推荐）

```python
class Channel:
    def __init__(self, raw, mode, url, channel_id, *, role: str = "universal", self_id: int | None = None):
        ...
        self.role = role.lower()        # universal | api | event
        self.self_id = self_id          # 反向时来自 X-Self-ID
```

顺手修一个类型标注：`self._channels: Dict[str, Channel]` → `Dict[int, Channel]`
（`_register()` 里 key 是 `next(self._channel_seq)`，是 int）。**这条已经改好了**：
现行 `OneBotConnection.__init__` 里就是 `Dict[int, Channel]`。

### 4.2 `start()` / `stop()` 接线（现行实现见 `OneBotConnection.start` / `OneBotConnection.stop`）

```python
async def start(self) -> None:
    self._closing = False
    # ① HTTP 客户端只在这里建一次
    self._http = httpx.AsyncClient(
        timeout=httpx.Timeout(self.config.request_timeout),
        headers=self.config.auth_headers(self.config.http_token),
    )
    # ② 反向优先起（先能收，再谈发）
    if self.config.reverse_enabled:
        self._spawn(self._reverse_server_loop(), name="reverse-ws")
    if self.config.forward_enabled:
        self._spawn(self._forward_loop(), name="forward-ws")
    if not (self.config.forward_enabled or self.config.reverse_enabled):
        logger.warning("正向与反向 WebSocket 都没开，只能靠 HTTP 发送（收不到事件）")
```

```python
async def stop(self) -> None:
    ...  # 现有的：取消任务 → 关通道 → _fail_pending
    if self._http is not None:                 # ③ 收尾别忘 aclose
        await self._http.aclose()
        self._http = None
```

> `stop()` 里的顺序不用改：`async with serve(...)` 让反向任务能被立刻取消（§3）。

### 4.3 反向服务端三件套

```python
# ------------------------------------------------------------ 反向 WS 服务端
async def _reverse_server_loop(self) -> None:
    reverse = self.config.reverse
    retry = max(1.0, self.config.reconnect_interval)
    while not self._closing:
        try:
            # 必须用 async with（§3）；内部不要 await serve_forever()
            async with websockets.serve(
                self._reverse_handler,
                reverse.host,
                reverse.port,
                process_request=self._process_reverse_request,
                max_size=_MAX_MESSAGE_SIZE,
                ping_interval=_interval(self.config.ping_interval, 30.0),
                ping_timeout=_interval(self.config.ping_timeout, 30.0),
                close_timeout=5,
            ):
                retry = max(1.0, self.config.reconnect_interval)
                logger.opt(colors=True).success(
                    f"反向 WebSocket 已监听 <y>ws://{reverse.host}:{reverse.port}{reverse.path}</y>"
                    "（等待 SnowLuma 的 wsClients 接入）"
                )
                await asyncio.Future()            # 保持监听；被 cancel 时由 __aexit__ 收尾
        except asyncio.CancelledError:
            raise
        except OSError as exc:                    # 端口被占用等
            logger.error(f"反向 WebSocket 监听 ws://{reverse.host}:{reverse.port} 失败: {exc}，{retry:.0f}s 后重试")
        except Exception as exc:
            logger.exception(exc)
        if self._closing:
            break
        await asyncio.sleep(retry)                # 和 _forward_loop 一样的退避
        retry = min(retry * 2, 60.0)

def _process_reverse_request(self, connection: ServerConnection, request: Request):
    """握手鉴权：SnowLuma 的 wsClients 带着 accessToken 连过来"""
    expected = self.config.reverse.access_token
    if not expected:                              # 没配 token 就不校验（与 SnowLuma 默认一致）
        return None
    provided = _extract_token(request.path, request.headers)   # M4 已写好的复用
    if provided and hmac.compare_digest(provided, expected):   # 常数时间比较
        return None
    logger.warning(f"拒绝反向 WebSocket 连接（来自 {connection.remote_address}）：access token 不匹配")
    return connection.respond(401, "Unauthorized\n")           # 回 401，客户端会拿到 InvalidStatus

async def _reverse_handler(self, connection: ServerConnection) -> None:
    """一条反向通道的一生：注册 → 探测 → 读循环 → 注销"""
    request = getattr(connection, "request", None)             # handler 里仍可读握手信息
    headers = request.headers if request is not None else {}
    role = str(headers.get("X-Client-Role") or "universal").lower()
    remote_id = headers.get("X-Self-ID")

    channel = self._register(connection, "reverse", str(remote_id or "reverse"), role=role, self_id=...)
    logger.opt(colors=True).success(
        f"SnowLuma 反向 WebSocket 已接入: <y>{channel.remote}</y>（role={role}）"
    )
    self._schedule_probe()                                     # 复用 M4：登录探测
    try:
        await self._pump(channel)                              # 复用 M4：读循环
    finally:
        self._unregister(channel)
        logger.warning(f"反向 WebSocket 连接已断开: {channel.remote}")
```

要点：

* `_register()` 需要加 `role` / `self_id` 参数（或者注册后直接赋值，见 §4.1）。
* 监听失败要能自愈：**不能**让异常冒出去把进程带走。
* 若你想严格校验路径（`config.reverse.path` 与 `request.path` 不符就 404），放在
  `_process_reverse_request` 里；默认建议宽松（只记一条 debug），因为不同集成方给的路径五花八门。
* 多连接不需要额外处理：`_channels` 本来就是字典，几条反向连接就是几个 key。

### 4.4 `_call_http()`（**已不是桩**：现行实现见 `OneBotConnection._call_http`）

```python
async def _call_http(self, action: str, params: Dict[str, Any], timeout: float) -> Any:
    if self._http is None:
        raise ConnectionUnavailable("HTTP 客户端未初始化（连接层还没 start()）")
    try:
        response = await self._http.post(
            self.config.http_url(action), json=params, timeout=timeout   # body 就是 params
        )
    except httpx.HTTPError as exc:
        raise ConnectionUnavailable(f"HTTP 调用 {action} 失败: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        # 非 JSON（网关 502 / 空 body 等）：按 HTTP 状态报错
        raise ActionFailed(action, status=str(response.status_code),
                           retcode=response.status_code, message=response.text[:200]) from None
    return self._unwrap(action, payload)        # 复用 M4：retcode != 0 → ActionFailed
```

要点：

* **请求体就是 `params` 本身**，不是 `{"action":..., "params":...}` 的信封（信封只用于 WS）。
* 非 200 **也可能带信封**（鉴权失败常是 `401 + retcode 1403`）。所以先尝试解析 JSON 再统一走
  `_unwrap()`，这样调用方拿到的仍然是带 `retcode/wording` 的 `ActionFailed`，而不是一个含糊的网络错误。
* 超时用「按请求传」的 `timeout=`，不要只依赖 client 的默认值——`call_action()` 允许逐次指定。
* 你现在的 `call_action()` 逻辑已经是对的（`transport="http"` 时不挑通道、直接走 HTTP），本节只需填桩。

### 4.5 顺带确认「不重复发送」铁律仍在

`call_action()` 的现行语义（见 `OneBotConnection.call_action`）：

```
transport = auto 时：有 WS 通道 → 只走 WS（超时不回退 HTTP）
                     没有 WS 通道 → 走 HTTP
transport = ws  时：没有通道 → 直接抛 ConnectionUnavailable
```

这正是设计文档 §8.3 要求的语义，M5 不要为了「更健壮」而加上「WS 超时后重试 HTTP」——
那会让同一条消息发两遍。§6.4 会给一个专门守这条的回归测试。

---

## 5. 反向通道的验收清单（C 组，6 项）

| # | 断言 | 怎么造 |
| --- | --- | --- |
| C1 | 错误 token 被拒（`InvalidStatus`，状态码 401） | 反向客户端用 `access_token=wrong` 拨号 |
| C2 | 正确 token 接入，`connected` 为真且 `len(channels) == 1` | 带对 token 拨号后轮询 `conn.connected` |
| C3 | 接入后自动完成登录探测 | 等 `conn.login_info["user_id"] == 999` |
| C4 | 反向通道上动作可用 | `conn.call_action("get_status")` 返回 `online is True` |
| C5 | 反向通道收到的事件进队列 | 反向客户端 push `group_message("ping")`，等队列 +1 |
| C6 | 两条反向连接互不影响 | 同时接两条，各自都能收到动作/事件；`len(channels) == 2` |

> **用例落点**：C1~C5 已由 `tests/test_reverse.py` 的 `test_reverse_ws_end_to_end` 覆盖
> （鉴权 401、接入后 `conn.connected`、反向收事件、反向 `call_action`）。
> **C6 目前没有用例**（待补）。

（可选 C7：`X-Client-Role: event` 的通道不被 `_pick_channel()` 选中——前提是你实现了 role。）

## 6. HTTP 兜底的验收清单（D 组，6 项）

| # | 断言 | 备注 |
| --- | --- | --- |
| D1 | 无 WS 通道 + `transport="auto"` → 自动走 HTTP 成功 | **这就是要翻转的 M4-B9** |
| D2 | 请求带 `Authorization: Bearer httptoken` | 断言 mock 记录的 `auth` |
| D3 | 打到 `/{action}` 正确路径 | mock 记录的 `action == "send_msg"` |
| D4 | 请求体就是 params（不是信封） | 断言 mock 记录的 `params` |
| D5 | HTTP token 错误 → `ActionFailed`（retcode 1403），不是 `ConnectionUnavailable` | 用 mock 的 401+信封分支 |
| D6 | **WS 超时后不会改走 HTTP**（防重复发送） | mock 设 `slow_actions["send_msg"] = 2.0`，`timeout=0.5` 调 `send_msg`；等它在 HTTP 侧**没有任何** `send_msg` 记录 |

D6 是本节最有价值的回归测试，**目前还没有落地**，建议务必加上：

```python
mock.slow_actions["send_msg"] = 2.0
try:
    await conn.call_action("send_msg", timeout=0.5, message_type="group", group_id=1, message="hi")
except ConnectionUnavailable:
    pass
await asyncio.sleep(0.3)                      # 给「错误的回退」留出发生的时间
runner.check("D6 WS 超时后没有回退到 HTTP（不会重复发送）",
             not [a for a in mock.http_actions if a["action"] == "send_msg"],
             str(mock.http_actions[-2:]))
```

---

## 7. 测试要动的东西

### 7.1 给 `tests/mock_snowluma.py` 加一个「反向客户端」（**建议方案，未采用**）

> **现状**：这条**没有做**——`tests/mock_snowluma.py` 里只有 `REVERSE_PORT` / `REVERSE_TOKEN`
> 两个常量，没有 `MockReverseClient`。现行做法更省事：`tests/test_reverse.py` 直接用
> `websockets.connect(...)` 拨号，再起一个 `echo_reader()` 协程按 `echo` 回包。
> 下面这段保留作"如果反向用例变多、需要复用动作分派表"时的参考。

你现在的 mock 只扮演**服务端**（正向场景）。反向场景需要扮演 SnowLuma 的 `wsClients`——
也就是**反向拨号到被测框架**。如果要做，建议直接复用 `MockSnowLuma.reply_to()` 的动作分派表，
避免两处维护：

```python
class MockReverseClient:
    """扮演 SnowLuma 的 wsClients：主动连到 HysialX 的反向服务端。"""

    def __init__(self, owner: MockSnowLuma, url: str, token: str = REVERSE_TOKEN,
                 *, role: str = "Universal", self_id: int = SELF_ID,
                 with_token_header: bool = True):
        ...

    async def start(self) -> "MockReverseClient":
        headers = {"X-Self-ID": str(self.self_id), "X-Client-Role": self.role}
        if self.token and self.with_token_header:
            headers["Authorization"] = f"Bearer {self.token}"      # 也可以只用查询参数
        self.conn = await websockets.connect(
            f"{self.url}?access_token={self.token}" if self.token else self.url,
            additional_headers=headers, max_size=None,
        )
        self.task = asyncio.create_task(self._reader())
        return self

    async def _reader(self) -> None:
        async for raw in self.conn:
            request = json.loads(raw)
            self.actions.append(request)
            action = request.get("action")
            if action == "no_reply":
                continue
            await self.conn.send(json.dumps(self.owner.reply_to(request), ensure_ascii=False))

    async def push(self, payload: dict) -> None:          # 推事件给被测框架
        await self.conn.send(json.dumps(payload, ensure_ascii=False))

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        await self.conn.close()
```

`REVERSE_PORT = 18082` / `REVERSE_TOKEN = "revtoken"` 已经在 `tests/mock_snowluma.py` 的常量区声明好了。

### 7.2 新增 `tests/test_reverse.py`（**已落地**）

现行文件是 `tests/test_reverse.py`（不是 `test_reverse_http.py`），**只用一个文件**：
`test_reverse_ws_end_to_end()` 同步入口 + `asyncio.run(_case())`，里面用
`_free_port()` 取空闲端口、`_connect_with_retry()` 等反向服务端 listen 起来。要点：

```python
# tests/test_reverse.py（现行实现的骨架）
from mock_snowluma import group_message
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection

TOKEN = "revtok"

def reverse_config(port): ...            # mode="reverse"、api_transport="ws"、cfg.reverse.* 手填
def _free_port() -> int: ...             # 绑 0 号端口让系统分配，避免撞端口
def test_reverse_ws_end_to_end(): asyncio.run(_case())

async def _case() -> None:
    conn = OneBotConnection(reverse_config(port))
    await conn.start()
    client = await _connect_with_retry(f"ws://127.0.0.1:{port}/event?access_token={TOKEN}",
        additional_headers={"X-Self-ID": "999", "X-Client-Role": "Universal"})
    assert conn.connected
    await client.send(json.dumps(group_message("hi")))      # 反向收事件
    assert (await asyncio.wait_for(conn.event_queue.get(), 3))["post_type"] == "message"
    ...                                                     # 反向发动作：echo_reader 按期回包
    with pytest.raises(InvalidStatus):                      # 错 token 必须 401
        await websockets.connect(f"ws://127.0.0.1:{port}/event?access_token=wrong")
```

注意 `mode="reverse"` + `cfg.reverse.enabled=True` ⇒ `config.reverse_enabled` 为真、
`forward_enabled` 为假，正好是「只有反向通道」的场景；**D 组（HTTP 兜底）目前还没有用例**
——测 D 组时用 `mode="reverse"` 且不拨号，就得到「完全没有 WS 通道」，再让 mock 的 HTTP 服务开着。

### 7.3 翻转 M4 的 B9（**没有做，且不必做**）

`tests/test_connection.py` 里 B9 现在仍然是「无通道 + `transport="auto"` → 抛
`ConnectionUnavailable`」，而且**它依然是对的**：那条断言跑在 `await conn.stop()` **之后**，
`stop()` 已经把 `_http` 关成 `None`，于是 `_call_http` 会在入口抛
`ConnectionUnavailable("HTTP 客户端未初始化(连接层还没 start())")`——和 M4 时期的期望结果一致。

所以 B9 不需要改。真正该测的是「有 HTTP 客户端、但没有 WS 通道」那条路径：

```python
# 在 conn.start() 之后、conn.stop() 之前，且**不要**拨反向客户端 → 没有 WS 通道
status = await conn.call_action("get_status", transport="auto")
runner.check("D1 无 WS 通道 + auto → 走 HTTP 成功", status.get("online") is True, str(status))
```

再补一条「HTTP 也不可用」的失败分支（把 mock 的 HTTP 服务停掉，或把 `http_base` 指到空端口）：

```python
cfg.http_base = "http://127.0.0.1:1"          # 必然连不上
try:
    await conn.call_action("get_status", transport="auto")
    runner.check("D1b HTTP 也不可用 → ConnectionUnavailable", False, "没有抛异常")
except ConnectionUnavailable:
    runner.check("D1b HTTP 也不可用 → ConnectionUnavailable", True)
```

---

## 8. 真机验证（可选，只读）

M5 阶段不必让真实 SnowLuma 反向连你（那要改它的 `wsClients` 并重载适配器），
但 **HTTP 通道可以立刻对着本机真实实例做只读验证**：

```python
# 手动脚本，别放进 pytest（依赖外部进程）
import asyncio
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection

async def main():
    cfg = SnowLumaConfig(mode="reverse", api_transport="http",
                         http_base="http://127.0.0.1:3000", request_timeout=5)
    conn = OneBotConnection(cfg)
    await conn.start()                       # mode=reverse 且没配 reverse → 不会有 WS 通道
    print(await conn.call_action("get_login_info"))
    print(await conn.call_action("get_status"))
    print(await conn.call_action("get_version_info"))
    await conn.stop()

asyncio.run(main())
```

预期（我这边实测过）：

```
{'user_id': 3508166608, 'nickname': 'Hysial'}
{'online': True, 'good': True}
{'app_name': 'SnowLuma', 'app_version': '1.14.19-node', 'protocol_version': 'v11'}
```

真机反向联调留到 M9；那时在 SnowLuma 的 `wsClients` 里加 `ws://127.0.0.1:6700/`、
`role: Universal`、`accessToken` 与你配置一致（注意 `reconnectIntervalMs` 最小 1000），
**改完记得恢复它的配置**。

---

## 9. 常见错误速查

| 症状 | 原因 | 修法 |
| --- | --- | --- |
| 连上就 1011 / `missing 1 required positional argument: 'path'` | handler 写成两个参数 | `async def handler(connection)` 单参（§2） |
| `stop()` 卡住不返回，日志停在「取消任务」 | 用了 `await server.serve_forever()` | 换成 `async with serve(...)` + `await asyncio.Future()`（§3） |
| 反向一直 401 | token 位置不对／配置里填的是 HTTP token／多了空格 | `_extract_token` 三个位置都试；`hmac.compare_digest` 前先 `strip()`；区分 `http_token` 与 `reverse.access_token` |
| 事件收得到，动作永远超时 | 对端是 `Event` 角色通道 | `_pick_channel()` 跳过 `role == "event"`；或改用 `Universal` |
| 端口占用导致进程退出 | 监听异常没兜住 | `except OSError` + 退避重试，别让异常冒泡 |
| HTTP 调用报 `ConnectionUnavailable` 但 SnowLuma 明明在跑 | URL 拼错（`http_path` 前缀重复/缺失）或 method 不是 POST | 用 `config.http_url()`；先 `curl -X POST` 手工确认 |
| 请求体带 `{"action":...}` 导致对端 1404 | 把 WS 信封直接发给了 HTTP | HTTP body 只放 params（§4.4） |
| token 错误时收到 `ConnectionUnavailable` 而不是 `ActionFailed` | 非 200 时没解析信封就抛了 | 先尝试 `response.json()` 再 `_unwrap()` |
| 退出时 `ResourceWarning: unclosed client` | 忘了 `await self._http.aclose()` | §4.2 |
| 消息发了两遍 | WS 超时后又走了 HTTP | 守住 §4.5 的语义，并用 D6 测试锁住 |

---

## 10. 提交前自检（Definition of Done）

- [x] `_reverse_server_loop` 用 `async with`，被取消时能在 1s 内结束（可用 §3 的探针脚本自测）
- [x] `_process_reverse_request` 在 token 为空时不校验、不匹配时回 401
- [x] 反向连接接入后自动登录探测，且 `_channels` 里能看到它
- [ ] 两条反向连接同时可用，断开一条不影响另一条（**C6，用例待补**）
- [x] `_call_http` 用 `config.http_url()`、body 是 params、Bearer 头正确、非 200 走信封
- [x] `start()` 建 `_http`、`stop()` `aclose()`
- [x] 反向监听端口被占用时只重试、不崩
- [ ] C 组 6 项 + D 组 6 项全绿（**现状：C1~C5 有用例；C6 与 D 组待补**；
      M4 的 A/B 组仍全绿，且 B9 **无需**改写，见 §7.3）
- [ ] D6（WS 超时不回退 HTTP）通过（**用例待补**）
- [ ] 真机 HTTP 只读三项（`get_login_info` / `get_status` / `get_version_info`）通过

---

## 附：本教程里所有实测/源码结论的出处

| 结论 | 依据 |
| --- | --- |
| handler 单参，两参数在连接时报 TypeError → 1011 | 本机 websockets 16.0 实测 + `websockets/asyncio/server.py:376` |
| `process_request` 可同步可异步，返回 None/Response | `websockets/asyncio/server.py:145-170` |
| `respond(status, text)` 用于拒绝握手，拒绝后不调用 handler | `websockets/asyncio/server.py:93-112`、`:203-207` |
| `connection.request` 在 handler 中可读 | `websockets/asyncio/server.py:209-221` |
| `ServerConnection` 可挂自定义属性 | 本机实测 `__dict__` 存在 |
| `async with serve()` 可被立刻取消；`serve_forever()` 在有连接时挂死 | 本机探针实测（0.01s vs >2s）+ `asyncio/base_events.py:359-378` |
| websockets `Server.close()` 会给连接发 1001 并等 handler 退出 | `websockets/asyncio/server.py:408-449` |
| httpx `base_url` 合并保留路径前缀 | 本机 httpx 0.28.1 实测 |
| 真实 SnowLuma HTTP 只读应答 | 本机 SnowLuma 1.14.19-node 实测 |
