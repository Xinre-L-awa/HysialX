# M4 教程：连接层（一）正向 WebSocket 与动作调用

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。
>
> 配套文档：[设计文档](snowluma-protocol-design.md) §6.2 / §6.4 / §6.5 / §6.6、§11.1-A；
> [M3 教程](m3-mock-snowluma-tutorial.md)（mock 协议端）。
>
> 本教程里的代码在 **Python 3.12.10 + websockets 16.0** 上实际跑通：
> A 组 13 项 + B 组 9 项 = **22/22 通过**。你照着敲完应得到同样结果。
>
> ⚠️ 本文的 Step 6 让 `_call_http` 先抛 `ConnectionUnavailable`（M4 的阶段性占位）。
> **M5 已经把它换成真的 httpx 兜底实现**，现行 `snowluma/connection.py` 的 `_call_http`
> 不再抛"尚未实现"。以 M5 教程与现行代码为准。

---

## 0. 这一步的交付物（DoD）

M4 结束时你应当拥有：

| # | 判据 | 怎么证明 |
| --- | --- | --- |
| 1 | `snowluma/connection.py` 里有可用的 `OneBotConnection` | 能被 import、能 `await start()` |
| 2 | 能连上 mock 的正向 WS（带 token），断线后自动退避重连 | A1 / B6 |
| 3 | 连接建立后自动做登录探测（`get_login_info` → `self_id`） | A2 |
| 4 | 能按配置调用 `_set_model_show` | A3 |
| 5 | 动作调用走 `{action, params, echo}`，按 `echo` 配对 | A6 |
| 6 | 应答缺 `echo` 时有兜底（唯一在途请求） | A7 |
| 7 | `retcode != 0` → `ActionFailed`，带 `status/retcode/wording` | A8 / A10 |
| 8 | 无应答 → 超时 `ConnectionUnavailable`，耗时 ≈ timeout | A9 |
| 9 | WS 断开时在途请求**立即**失败，不悬挂 | A11 |
| 10 | `connected` 随通道增删正确变化 | A1 / A12 |
| 11 | `meta_event` 不进事件队列，普通事件进队列 | A5 |
| 12 | `send_message` 能正确组装 `send_msg` 参数（群/私聊、id 转 int、格式自适应） | B1~B5 |
| 13 | 没有通道时的行为明确（不静默、不重复发） | B8 / B9 |
| 14 | `tests/test_connection.py` 能被 pytest 跑，全过 | `pytest tests/test_connection.py -q` |

**M4 不做**（留给后面）：反向 WS 服务端与 HTTP 兜底（M5）、事件模型 `api/event.py`（M6）、
`api/bot.py` 的 `send/finish/call_api`（M7）、`main.py` 运行层（M8）。

---

## 1. 你的半成品与 M4 的关系

M4 动工前，`snowluma/connection.py` 只有前半段：imports、`_coerce_id`、`_interval`、
`_extract_token`、`Channel`。这些**全部保留**，M4 要做的是：

```
connection.py
├─ 模块头 / 常量 / 三个小工具函数      ✅ 你已写完（不动）
├─ class Channel                     🔧 修 2 处 + 补 1 个方法
└─ class OneBotConnection            ✍️ M4 全部写（本教程 Step 2~9）
```

`__all__ = ["Channel", "OneBotConnection"]` 已经在等第二个名字了。

---

## 2. 开工前：先修 3 个小毛病

### 2.1 `Channel.remote` 把连接对象当成 dict 了

你现在的写法（`connection.py` 第 74 行）：

```python
address = self.raw.get("remote_address")     # ❌ raw 是 websockets 的连接对象，没有 .get
```

`raw` 是 `ClientConnection` / `ServerConnection`，属性访问才对：

```python
    @property
    def remote(self) -> str:
        # raw 是 websockets 的连接对象；getattr 保证它没这个属性时也不炸
        address = getattr(self.raw, "remote_address", None)
        if isinstance(address, tuple) and len(address) >= 2:
            return f"{address[0]}:{address[1]}"
        return self.url
```

顺便把类型标注改对（`raw: Dict[str, Any]` → `raw: Any`，或者 `Union[ClientConnection, ServerConnection]`）。

### 2.2 `Channel` 缺一个 `close()`

`stop()` 要能优雅关闭通道，补上：

```python
    async def close(self, code: int = 1000, reason: str = "") -> None:
        try:
            await self.raw.close(code, reason)
        except Exception:
            # 关不掉就算了：要么已经关了，要么对端先跑了
            pass
```

### 2.3 mock 的 `slow_actions`：少了 `await`，而且不该阻塞读循环（M4 必须修）

`tests/mock_snowluma.py` 第 139-141 行现在是：

```python
                delay = self.slow_actions.get(action or "")
                if delay:
                    asyncio.sleep(delay)        # ❌ 只创建了协程对象，从没等待 → 永远不延迟
```

这里有两个坑，一次修掉：

1. **少了 `await`** → 延迟从未生效；
2. **就算补上 `await` 也是错的** → mock 的 `async for` 是**单读者**，在这儿睡 2 秒会把
   这条连接上**后续所有动作**都堵住。症状是：A9b 跑完之后，紧接着的 A10（未知动作 1404）
   会莫名其妙超时。

正确做法是「延迟应答」交给独立任务，读循环立刻继续：

```python
                delay = self.slow_actions.get(action or "")
                if delay:
                    asyncio.create_task(self.reply_later(connection, request, delay))
                    continue                        # 读循环不阻塞，后续动作照常处理

                await connection.send(json.dumps(self.reply_to(request), ensure_ascii=False))
```

并在 `reply_to` 前面加一个方法（`ConnectionClosed` 已经 import 过了）：

```python
    async def reply_later(self, connection, request: Dict, delay: float) -> None:
        """延迟应答：用 task 而不是 await，避免堵住 mock 自己的单读者循环"""
        await asyncio.sleep(delay)
        try:
            await connection.send(json.dumps(self.reply_to(request), ensure_ascii=False))
        except ConnectionClosed:
            pass
```

顺带把一个笔误改掉（第 124 行，不影响结果，但排障时看着别扭）：

```python
        return connection.respond(401, "Unauthorized\n")    # 原来是 "Unauthorized/n"
```

> **顺手记住一条真实规律**：OneBot 协议端通常是「一条连接上顺序处理动作」。
> 客户端发了慢动作，同一条连接上的后续动作确实要排队——这正说明
> `request_timeout` 为什么要给足，以及为什么 M5 之后「多通道」才有意义。
>
> 而 **M4 必须有可调延迟**的原因是：`no_reply` 只能验证「永远不回」，
> 而**超时边界**（0.2s 的慢应答要在 1s 超时内成功、2.0s 的慢应答要在 0.5s 超时内失败）
> 只能靠它验证。这正是 M3 把故障注入做进 mock 的意义。

---

## 3. 状态设计：一张表看懂 `OneBotConnection`

写代码前先确定「谁是状态、谁读谁写」。这张表就是 `__init__` 的清单：

| 字段 | 类型 | 谁写 | 谁读 | 作用 |
| --- | --- | --- | --- | --- |
| `config` | `SnowLumaConfig` | 构造 | 全体 | 地址/token/超时/退避 |
| `event_queue` | `asyncio.Queue[dict]` | `_emit` | M8 的分发循环 | 事件出口（连接层与插件层的唯一接口） |
| `self_id` | `int \| None` | `_probe_login_info` / lifecycle | M6/M7 | 机器人账号 |
| `login_info` / `version_info` | `dict \| None` | `_probe_login_info` | 日志/排障 | 协议端信息 |
| `message_format_detected` | `str \| None` | `_handle_payload` | `_outgoing_format` | 记录对端用的是 array 还是 string |
| `_channels` | `dict[int, Channel]` | `_register` / `_unregister` | `connected` / `_pick_channel` | 活着的通道 |
| `_channel_seq` | `itertools.count(1)` | `_register` | — | 通道 id |
| `_pending` | `dict[str, Future]` | `_call_ws` / `_handle_payload` | `_fail_pending` | 在途请求（echo → future） |
| `_tasks` | `set[Task]` | `_spawn` | `stop` | 后台任务（正向循环、探测），退出时取消 |
| `_closing` | `bool` | `start` / `stop` | 所有循环 | 退出旗标，防止重连死循环 |
| `_connected` | `asyncio.Event` | `_register` / `_unregister` | `wait_until_connected` | 供启动阶段等待 |
| `_probe_task` | `Task \| None` | `_schedule_probe` | `_schedule_probe` | 防止重复探测 |
| `_http` | `httpx.AsyncClient \| None` | **M5** | `_call_http` | HTTP 兜底（M4 先留 None） |

三个只读属性对外暴露：`connected`、`channels`、`pending_actions`。

---

## 4. 铁律一：单读者模型

### 4.1 现象

`websockets` 的一条连接上，**同一时刻只允许一个协程在读**。下面两种写法都会出问题：

```python
# ❌ 写法 A：在读循环里调用动作 → 自己等自己的应答，永久挂死
async for raw in ws:
    payload = json.loads(raw)
    if payload.get("post_type") == "message":
        await self.call_action("send_msg", ...)   # 这个动作的应答要由本循环投递 → 死锁

# ❌ 写法 B：两个地方同时 recv → 后一个报 RuntimeError（或丢帧）
task1 = asyncio.create_task(ws.recv())
task2 = asyncio.create_task(ws.recv())
```

### 4.2 正确姿势

把「读」收敛成**唯一**的 `_pump(channel)`，它只做两件事：

1. 收到 **有 `echo`** 的报文 → 投递给 `_pending[echo]` 这个 future，**结束**；
2. 收到**有 `post_type`** 的报文 → 塞进 `event_queue`，**结束**。

而「写」可以由任意协程发起（`Channel.send_json` 内部有锁），发完就在
`await future` 上等——等来的结果一定是 `_pump` 投进来的。

```python
_pump（唯一读者）                    call_action（任意协程，可并发多个）
      │                                        │
      │  收到 {"echo": "abc", ...}             │  pending["abc"] = future
      └────────────► set_result ──────────────►│  await future → 拿到应答
```

### 4.3 推论：登录探测必须 `create_task`

连接建立后要发 `get_login_info`。**不能**在 `_register` 之后直接 `await`，
因为那时 `_pump` 还没开始跑（没人投递应答）。正确做法：

```python
self._schedule_probe()      # 内部 create_task(self._probe_login_info())
await self._pump(channel)   # 紧接着进入读循环
```

`create_task` 创建的协程不会立刻执行，而是等到下一个 `await` 点（即 `_pump` 里第一次
`async for`）才开始跑——此时读者已经就位，探测的应答一定有人投递。

> 同理：`_handle_meta_event` 里收到 lifecycle 也不能 `await` 探测，只能 `create_task`。

---

## 5. 铁律二：绝不重复发送

`call_action` 的通道选择策略（M4 只有 WS，但**语义现在就要定死**）：

| `api_transport` | 有 WS 通道 | 无 WS 通道 | 说明 |
| --- | --- | --- | --- |
| `ws` | 走 WS | **抛 `ConnectionUnavailable`** | 显式要求 WS，失败就是失败 |
| `http` | 走 HTTP | 走 HTTP | 显式要求 HTTP |
| `auto`（默认） | 走 WS | 走 HTTP | 只在「压根没有 WS」时才用 HTTP |

**关键规则**：`auto` 下，WS **已经发出去了**但等待应答超时，**不允许**再走 HTTP。

理由：`send_msg` 不是幂等操作。超时只说明「我没收到应答」，**不代表对端没收到**。
再走一次 HTTP = 同一条消息发两遍。真实场景下这就是群里刷屏。

```python
channel = self._pick_channel() if transport in ("auto", "ws") else None
if channel is not None:
    return await self._call_ws(channel, action, params, timeout)   # 超时就抛，不回退
if transport == "ws":
    raise ConnectionUnavailable("没有可用的 WebSocket 通道")
return await self._call_http(action, params, timeout)              # 只有「没有通道」才来这
```

M4 阶段 `_call_http` 先做成**明确的占位**（抛异常），M5 再填实现。这样 B8/B9 两条
断言现在就能把语义锁住，M5 只改 `_call_http` 一个方法。
**M5 已经落地**：现行 `_call_http` 用 httpx 真的 POST `config.http_url(action)`，
body 是 `params`、带上 Bearer 头、非 200/非 JSON 也按信封解析——见
[M5 教程](m5-reverse-ws-http-tutorial.md) §4.4。

---

## 6. 动手：Step 1 → Step 9

> 每一步的代码都是**最终形态**，直接粘进 `connection.py` 对应位置即可。
> 建议顺序：先一口气写完 Step 2~9 的类骨架，再逐个方法填。

### Step 1 — `Channel` 的修正（见 §2.1 / §2.2）

改完后 `Channel` 应该有：`__init__` / `remote` / `send_json` / `close`。

### Step 2 — 类骨架、生命周期、状态查询

在 `Channel` 之后新增（`__all__` 里的 `OneBotConnection` 就是它）：

```python
class OneBotConnection:
    """SnowLuma(OneBot v11) 连接管理器（M4：正向 WS + 动作调用）"""

    def __init__(self, config: SnowLumaConfig, *, event_queue_size: int = _EVENT_QUEUE_SIZE) -> None:
        self.config = config
        self.event_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=event_queue_size)

        # ---- 对端信息（登录探测写入）
        self.self_id: Optional[int] = None
        self.login_info: Optional[Dict[str, Any]] = None
        self.version_info: Optional[Dict[str, Any]] = None
        self.message_format_detected: Optional[str] = None

        # ---- 内部状态
        self._channels: Dict[int, Channel] = {}
        self._channel_seq = itertools.count(1)
        self._pending: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}
        self._tasks: Set["asyncio.Task[Any]"] = set()
        self._closing = False
        self._connected = asyncio.Event()
        self._probe_task: Optional["asyncio.Task[Any]"] = None
        self._http: Optional[httpx.AsyncClient] = None       # M5 才创建

    # ---------------------------------------------------------------- 生命周期
    async def start(self) -> None:
        """启动连接（M4 只有正向；反向/HTTP 在 M5）"""
        self._closing = False
        if self.config.forward_enabled:
            self._spawn(self._forward_loop(), name="forward-ws")
        else:
            logger.warning("配置未启用正向 WebSocket，且 M4 尚未实现反向通道，当前没有任何通道")

    async def stop(self) -> None:
        """取消后台任务、关闭通道、唤醒所有等待者"""
        self._closing = True
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for channel in list(self._channels.values()):
            await channel.close(1001, "HysialX shutting down")
        self._channels.clear()
        self._connected.clear()
        self._fail_pending(ConnectionUnavailable("连接已关闭"))

    def _spawn(self, coro: Awaitable[Any], name: Optional[str] = None) -> "asyncio.Task[Any]":
        """创建后台任务并登记，方便 stop() 统一取消"""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)      # 跑完自动摘掉，别让集合无限长
        return task

    # ---------------------------------------------------------------- 状态查询
    @property
    def connected(self) -> bool:
        return bool(self._channels)

    @property
    def channels(self) -> List[Channel]:
        return list(self._channels.values())

    @property
    def pending_actions(self) -> int:
        """在途动作数（排障与测试用）"""
        return len(self._pending)

    async def wait_until_connected(self, timeout: Optional[float] = None) -> bool:
        if self.connected:
            return True
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _outgoing_format(self) -> str:
        """发出去的 message 用哪种形态：配置写死 > 跟随对端 > 默认 array"""
        configured = (self.config.message_format or "auto").lower()
        if configured in ("array", "string"):
            return configured
        return self.message_format_detected or "array"

    def _pick_channel(self, preferred: Optional[str] = None) -> Optional[Channel]:
        """挑一条通道发动作；正向优先（反向是 M5 的事，这里先把顺序定好）"""
        if not self._channels:
            return None
        for mode in ([preferred] if preferred else []) + ["forward", "reverse"]:
            for channel in self._channels.values():
                if channel.mode == mode:
                    return channel
        return next(iter(self._channels.values()))
```

**自查**：`OneBotConnection(cfg)` 能构造、`connected is False`、`start()` 不会卡住。

### Step 3 — 通道注册 / 注销 / 在途请求失败

```python
    # ---------------------------------------------------------------- 通道登记
    def _register(self, raw: Any, mode: str, url: str) -> Channel:
        channel = Channel(raw, mode, url, next(self._channel_seq))
        self._channels[channel.id] = channel
        self._connected.set()
        return channel

    def _unregister(self, channel: Channel) -> None:
        self._channels.pop(channel.id, None)
        if not self._channels:
            # 最后一条通道没了：所有在途请求立即失败，不要让调用方干等到超时
            self._connected.clear()
            self._fail_pending(ConnectionUnavailable("所有 WebSocket 通道都已断开"))

    def _fail_pending(self, exc: BaseException) -> None:
        for echo, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(exc)
            self._pending.pop(echo, None)
```

**要点**：`_fail_pending` 是所有在途 future 的**唯一兜底出口**，断开/关闭都必须走它。
A11 测的就是这条路径。

### Step 4 — 唯一的读者：`_pump`

```python
    # ------------------------------------------------------------------ 读循环
    async def _pump(self, channel: Channel) -> None:
        """一条通道上唯一的读循环；它只负责「投递」，不做任何业务"""
        try:
            async for raw in channel.raw:
                channel.last_seen = time.time()
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"收到无法解析的报文（{channel.mode}）: {str(raw)[:200]}")
                    continue
                if isinstance(payload, dict):
                    self._handle_payload(channel, payload)
        except ConnectionClosed:
            # 正常断开，交给调用方决定要不要重连
            pass
```

> `channel.raw` 既可以是 `ClientConnection`（正向）也可以是 `ServerConnection`（M5 反向），
> 两者都支持 `async for`，所以这一个 `_pump` 未来能直接复用。

### Step 5 — 报文分发：echo 配对、meta 分流、事件入队

```python
    # ------------------------------------------------------------------ 分发
    def _handle_payload(self, channel: Channel, payload: Dict[str, Any]) -> None:
        """唯一的分发点：先配对应答，再处理 meta，最后把事件入队"""
        echo = payload.get("echo")
        if echo is not None and echo in self._pending:
            future = self._pending.pop(echo)
            if not future.done():
                future.set_result(payload)
            return

        # 容错：极少数实现不回填 echo。只有「在途请求恰好 1 个」时才敢认领
        if echo is None and "post_type" not in payload and ("retcode" in payload or "status" in payload):
            if len(self._pending) == 1:
                only_echo, future = next(iter(self._pending.items()))
                self._pending.pop(only_echo)
                logger.debug("收到没有 echo 的动作应答，按唯一在途请求匹配")
                if not future.done():
                    future.set_result(payload)
                return

        post_type = payload.get("post_type")
        if post_type is None:
            logger.debug(f"忽略无法识别的报文: {str(payload)[:200]}")
            return

        if post_type == "meta_event":
            self._handle_meta_event(payload)          # meta 不进事件队列
            return

        if post_type in ("message", "message_sent"):
            detected = message_format_of(payload.get("message"))
            if detected and detected != self.message_format_detected:
                self.message_format_detected = detected
                logger.debug(f"检测到对端 messageFormat = {detected}")

        if self.self_id is None and payload.get("self_id"):
            self.self_id = int(payload["self_id"])

        self._emit(payload)

    def _emit(self, payload: Dict[str, Any]) -> None:
        """入队；队列满时丢最旧的，别把读循环堵死（堵住会让心跳和应答全超时）"""
        try:
            self.event_queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                dropped = self.event_queue.get_nowait()
                logger.warning(f"事件队列已满，丢弃最旧事件: {dropped.get('post_type')}")
            except asyncio.QueueEmpty:
                pass
            try:
                self.event_queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.error("事件队列仍然写满，事件被丢弃")

    def _handle_meta_event(self, payload: Dict[str, Any]) -> None:
        meta_type = payload.get("meta_event_type")
        if meta_type == "lifecycle":
            if payload.get("self_id"):
                self.self_id = int(payload["self_id"])
            logger.opt(colors=True).success(
                f"SnowLuma 上报生命周期事件 <y>{payload.get('sub_type')}</y>，"
                f"当前机器人账号 <y>{self.self_id}</y>"
            )
            self._schedule_probe()                   # 注意：只能 create_task，不能 await
        elif meta_type == "heartbeat":
            status = payload.get("status") or {}
            logger.debug(
                f"心跳: online={status.get('online')} good={status.get('good')} "
                f"interval={payload.get('interval')}ms"
            )
        else:
            logger.debug(f"收到 meta 事件: {meta_type}")
```

**注意 import**：`message_format_of` 来自你的 `segment.py`：

```python
from .segment import MessageLike, message_format_of, message_to_payload
```

### Step 6 — 动作调用：`call_action` / `_call_ws` / `_unwrap`

```python
    # ------------------------------------------------------------------ 动作调用
    async def call_action(
        self,
        action: str,
        *,
        transport: Optional[str] = None,
        timeout: Optional[float] = None,
        **params: Any,
    ) -> Any:
        """调用一个 OneBot 动作，返回应答信封里的 data。

        通道策略见 §5：只有「完全没有 WS 通道」才退到 HTTP；
        WS 已发出但超时**绝不**回退，避免同一条消息发两遍。
        """
        transport = (transport or self.config.api_transport or "auto").lower()
        timeout = self.config.request_timeout if timeout is None else timeout
        channel = self._pick_channel() if transport in ("auto", "ws") else None

        if channel is not None:
            try:
                return await self._call_ws(channel, action, params, timeout)
            except (ConnectionClosed, OSError) as exc:
                # 发送瞬间连接断了：统一成 ConnectionUnavailable，调用方只需处理一种异常
                raise ConnectionUnavailable(f"动作 {action} 发送失败: {exc}") from exc
        if transport == "ws":
            raise ConnectionUnavailable("没有可用的 WebSocket 通道")
        return await self._call_http(action, params, timeout)

    async def _call_ws(
        self,
        channel: Channel,
        action: str,
        params: Dict[str, Any],
        timeout: float,
    ) -> Any:
        loop = asyncio.get_running_loop()
        echo = uuid.uuid4().hex
        future: "asyncio.Future[Dict[str, Any]]" = loop.create_future()
        self._pending[echo] = future
        started = time.perf_counter()
        try:
            await channel.send_json({"action": action, "params": params, "echo": echo})
            payload = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectionUnavailable(f"动作 {action} 等待应答超时（{timeout}s）") from exc
        finally:
            # 无论成功/超时/发送失败，都要把这一条从在途表里摘掉
            self._pending.pop(echo, None)
            if not future.done():
                future.cancel()      # 取消掉，避免 set_exception 之后没人取 → "never retrieved" 警告
        logger.debug(f"动作 {action} 完成，用时 {time.perf_counter() - started:.3f}s")
        return self._unwrap(action, payload)

    @staticmethod
    def _unwrap(action: str, payload: Any) -> Any:
        """校验应答信封：retcode == 0 才算成功（HTTP 200 也可能是业务失败）"""
        if not isinstance(payload, dict):
            raise ActionFailed(action, message=f"应答格式异常: {payload!r}")

        status = payload.get("status")
        retcode = payload.get("retcode")
        ok = retcode == 0 or (retcode is None and status in ("ok", "async", "accepted", None))
        if not ok:
            raise ActionFailed(
                action,
                status=status,
                retcode=retcode,
                message=str(payload.get("message") or ""),
                wording=str(payload.get("wording") or ""),
                data=payload.get("data"),
            )
        return payload.get("data")

    async def _call_http(self, action: str, params: Dict[str, Any], timeout: float) -> Any:
        """HTTP 兜底 —— M4 先占位，M5 换成真实现（见 [M5 教程](m5-reverse-ws-http-tutorial.md) §4.4）"""
        raise ConnectionUnavailable(f"HTTP 兜底通道尚未实现（M5）: {action}")
```

**三个细节，别省**：

1. `finally` 里的 `pop` + `cancel`：少了 `cancel`，发送失败时 future 带着异常被丢弃，
   日志里会出现 `Future exception was never retrieved`。
2. 超时用 `asyncio.wait_for`，**不要**用 `asyncio.sleep` 轮询。
3. `_unwrap` 判成功用 `retcode == 0`；`status` 只是辅助（真机实测未知动作是
   `status="failed", retcode=1404`）。

### Step 7 — 登录探测与机型

```python
    # ------------------------------------------------------------------ 登录探测
    def _schedule_probe(self) -> None:
        """连接建立 / lifecycle 时拉一次登录信息；同一时刻只允许一个在途"""
        if self._probe_task is not None and not self._probe_task.done():
            return
        self._probe_task = self._spawn(self._probe_login_info(), name="login-probe")

    async def _probe_login_info(self) -> None:
        try:
            info = await self.call_action("get_login_info")
            self.login_info = info if isinstance(info, dict) else {}
            user_id = (self.login_info or {}).get("user_id")
            if user_id is not None:
                self.self_id = int(user_id)
            nickname = (self.login_info or {}).get("nickname", "")
            logger.opt(colors=True).success(
                f"Connected successfully! 当前机器人账号 <y>{self.self_id}</y>"
                + (f"（{nickname}）" if nickname else "")
            )
        except Exception as exc:
            logger.warning(f"获取登录信息失败: {exc}")

        try:
            version = await self.call_action("get_version_info")
            self.version_info = version if isinstance(version, dict) else {}
            if self.version_info:
                logger.info(
                    "协议端: {app} {ver} / OneBot {proto}".format(
                        app=self.version_info.get("app_name", "SnowLuma"),
                        ver=self.version_info.get("app_version", "?"),
                        proto=self.version_info.get("protocol_version", "v11"),
                    )
                )
        except Exception as exc:
            logger.debug(f"获取版本信息失败: {exc}")

        await self._apply_device_name()

    async def _apply_device_name(self) -> None:
        name = (self.config.device_name or "").strip()
        if not name:
            return
        try:
            await self.call_action("_set_model_show", model=name, model_show=name)
            logger.opt(colors=True).success(f"设置机型 <y>{name}</y> 成功!")
        except Exception as exc:
            logger.warning(f"设置机型 {name} 失败: {exc}")
```

**为什么探测里可以 `await call_action`**：它自己就是被 `create_task` 起来的独立任务，
不在读循环里——读者（`_pump`）正跑在别的任务上，应答有人投递。

### Step 8 — 发送封装 `send_message`

```python
    # ------------------------------------------------------------------ 发送消息
    async def send_message(
        self,
        message: MessageLike,
        *,
        message_type: Optional[str] = None,
        user_id: Optional[Union[int, str]] = None,
        group_id: Optional[Union[int, str]] = None,
        auto_escape: bool = False,
    ) -> Dict[str, Any]:
        """调用 SnowLuma 的 send_msg（按群号/好友号自动路由）"""
        if message_type is None:
            message_type = "group" if group_id is not None else "private"

        params: Dict[str, Any] = {
            "message_type": message_type,
            # 关键：按对端 messageFormat 决定发段数组还是 CQ 字符串
            "message": message_to_payload(message, self._outgoing_format(), auto_escape=auto_escape),
            "auto_escape": bool(auto_escape),
        }
        if message_type == "group":
            if group_id is None:
                raise ValueError("群消息必须提供 group_id")
            params["group_id"] = _coerce_id(group_id)
        else:
            if user_id is None:
                raise ValueError("私聊消息必须提供 user_id")
            params["user_id"] = _coerce_id(user_id)

        data = await self.call_action("send_msg", **params)
        return data if isinstance(data, dict) else {}

    async def send_group_message(self, message: MessageLike, group_id: Union[int, str], **kwargs: Any) -> Dict[str, Any]:
        return await self.send_message(message, message_type="group", group_id=group_id, **kwargs)

    async def send_private_message(self, message: MessageLike, user_id: Union[int, str], **kwargs: Any) -> Dict[str, Any]:
        return await self.send_message(message, message_type="private", user_id=user_id, **kwargs)
```

> ⚠️ **参数顺序是 `(message, group_id)`**（私聊同理 `(message, user_id)`）：消息在前、收件人在后，
> 与 `send_message(message, *, group_id=...)` 保持一致。早期版本写成 `(group_id, message)`，已改。

> 注意 `message_to_payload` 的签名是 `(message, message_format="array", auto_escape=False)`，
> 用关键字传 `auto_escape` 更稳。

### Step 9 — 正向连接循环（含指数退避）

```python
    # ------------------------------------------------------------ 正向 WS 客户端
    async def _forward_loop(self) -> None:
        backoff = max(1.0, self.config.reconnect_interval)
        while not self._closing:
            uri = self.config.ws_uri()                       # token 走查询参数
            headers = self.config.auth_headers(self.config.forward_token)
            try:
                async with websockets.connect(
                    uri,
                    additional_headers=headers or None,      # websockets>=14 的参数名
                    max_size=_MAX_MESSAGE_SIZE,              # 事件里可能有 base64 图片
                    open_timeout=10,
                    ping_interval=_interval(self.config.ping_interval, 30.0),
                    ping_timeout=_interval(self.config.ping_timeout, 30.0),
                    close_timeout=5,
                    proxy=None,                              # 本机直连，忽略环境变量里的代理（见 §10 第 8 条）
                ) as raw:
                    channel = self._register(raw, "forward", self.config.forward_url)
                    backoff = max(1.0, self.config.reconnect_interval)   # 连上了就复位
                    logger.opt(colors=True).success(
                        f"已连接 SnowLuma 正向 WebSocket: <y>{self.config.ws_uri(mask=True)}</y>"
                    )
                    self._schedule_probe()                   # 探测：create_task，别 await
                    try:
                        await self._pump(channel)
                    finally:
                        self._unregister(channel)
                        logger.warning("与 SnowLuma 的 WebSocket 连接已断开")
            except asyncio.CancelledError:
                raise                                        # 退出时必须原样抛出
            except _CONNECTION_ERRORS as exc:
                logger.opt(colors=True).warning(
                    f"连接 SnowLuma 失败（{type(exc).__name__}: {exc}），{backoff:.0f}s 后重试"
                )
            except Exception as exc:
                logger.exception(exc)

            if self._closing:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)                  # 1s → 2s → … → 60s 封顶
```

**要点**：

- `finally: self._unregister(channel)` 必须在 `async with` 内部，否则通道永远摘不掉。
- `CancelledError` 要 `raise`，不能被宽泛的 `except Exception` 吃掉（否则 `stop()` 关不掉）。
- 退避在「成功连上」后复位，避免一次抖动就永久 60s。

---

## 7. 组装检查清单

`connection.py` 最终顺序（对照一遍，别漏）：

```
"""docstring"""
from __future__ import annotations
import asyncio / itertools / json / time / uuid
from typing import Any, Awaitable, Dict, List, Optional, Set, Union
from urllib.parse import parse_qs, urlsplit
import httpx / websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus
from log import logger
from .config import SnowLumaConfig
from .exception import ActionFailed, ConnectionUnavailable
from .segment import MessageLike, message_format_of, message_to_payload     # ← M4 新增

__all__ = ["Channel", "OneBotConnection"]
_MAX_MESSAGE_SIZE / _EVENT_QUEUE_SIZE / _CONNECTION_ERRORS                  # 已有
_coerce_id / _interval / _extract_token                                     # 已有
class Channel:  __init__ / remote(修) / send_json / close(新)
class OneBotConnection:
    __init__ / start / stop / _spawn
    connected / channels / pending_actions / wait_until_connected
    _outgoing_format / _pick_channel
    _register / _unregister / _fail_pending
    _pump
    _handle_payload / _emit / _handle_meta_event
    _schedule_probe / _probe_login_info / _apply_device_name
    call_action / _call_ws / _unwrap / _call_http(占位)
    send_message / send_group_message / send_private_message
    _forward_loop
```

> `_extract_token` 与 `httpx` 在 M4 用不到（分别给 M5 的反向鉴权和 HTTP 兜底），
> 留着即可；不想看 lint 警告就加 `# noqa: F401` 或先注释掉。

---

## 8. 测试：填 `tests/test_connection.py`

把你现在那个占位文件整个替换成下面内容（`CaseRunner` / 事件工厂都来自 M3 的 mock）：

```python
# tests/test_connection.py —— M4：正向 WS + 动作调用（由 tests/mock_snowluma.py 驱动）
import asyncio
import time

from mock_snowluma import (                      # pytest 会把 tests/ 加进 sys.path
    CaseRunner,
    MockSnowLuma,
    group_message,
    meta_heartbeat,
)
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection
from snowluma.exception import ActionFailed, ConnectionUnavailable

SELF_ID = 999
DEVICE = "HysialX 测试机型"


def config_for(mock: MockSnowLuma, **overrides) -> SnowLumaConfig:
    """把 mock 的地址/token 塞进配置；用例里只关心差异项"""
    cfg = SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/",
        forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}",
        http_token=mock.http_token,
        api_transport="ws",          # M4 只有 WS；auto 的 HTTP 分支留到 M5
        message_format="auto",
        request_timeout=1.0,
        reconnect_interval=1.0,      # 重连快一点，别让用例等 5 秒
        ping_interval=0,             # 关掉 ws 心跳，避免干扰计时
        ping_timeout=0,
        device_name=DEVICE,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


async def wait_until(predicate, timeout: float = 3.0) -> bool:
    """轮询等待条件成立。

    mock 的 CaseRunner 只负责断言，等待逻辑放在用例这边（断言与等待分开，失败信息更干净）。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


async def _case() -> int:
    runner = CaseRunner()
    mock = await MockSnowLuma().start()
    conn = OneBotConnection(config_for(mock))
    try:
        # ============================================== A 组：正向 WS + 动作（13 项）
        await conn.start()
        runner.check("A1 正向连接建立", await conn.wait_until_connected(3))

        # 注意：self_id 会被 lifecycle 事件提前填上，等它 == 999 并不代表探测完成；
        #       探测完成的标志是 login_info 里有内容（这是实测踩到的坑，见 §10）
        ok = await wait_until(lambda: (conn.login_info or {}).get("user_id") == SELF_ID)
        runner.check(
            "A2 登录探测拿到 self_id / nickname",
            ok and conn.self_id == SELF_ID and (conn.login_info or {}).get("nickname") == "Mock",
            f"self_id={conn.self_id} login_info={conn.login_info}",
        )

        ok = await wait_until(lambda: bool(mock.actions_named("_set_model_show")))
        params = (mock.last_action("_set_model_show") or {}).get("params", {})
        runner.check(
            "A3 按 device_name 调 _set_model_show 且参数正确",
            ok and params == {"model": DEVICE, "model_show": DEVICE},
            str(params),
        )

        version = await conn.call_action("get_version_info")
        runner.check(
            "A4 get_version_info 可解析",
            version.get("app_name") == "SnowLuma" and version.get("protocol_version") == "v11",
            str(version),
        )

        before = conn.event_queue.qsize()
        await mock.push(meta_heartbeat())
        await asyncio.sleep(0.2)
        await mock.push(group_message("ping"))
        got_message = await wait_until(lambda: conn.event_queue.qsize() == before + 1)
        payload = await asyncio.wait_for(conn.event_queue.get(), 1)
        runner.check(
            "A5 meta 不进队列、message 进队列",
            conn.event_queue.qsize() == before and got_message
            and payload.get("post_type") == "message",
            f"qsize={conn.event_queue.qsize()}/{before} payload={payload.get('post_type')}",
        )

        results = await asyncio.gather(
            conn.call_action("get_status"),
            conn.call_action("get_group_info", group_id=111),
            conn.call_action("get_group_info", group_id=222),
        )
        runner.check(
            "A6 并发动作 echo 不串台",
            results[0].get("online") is True
            and results[1].get("group_id") == 111
            and results[2].get("group_id") == 222,
            str(results),
        )

        tolerant = await conn.call_action("echo_less")
        runner.check("A7 应答缺 echo 时按唯一在途请求匹配", tolerant == {"message_id": 1}, str(tolerant))

        try:
            await conn.call_action("fail_test")
            runner.check("A8 retcode!=0 抛 ActionFailed", False, "没有抛异常")
        except ActionFailed as exc:
            runner.check(
                "A8 retcode!=0 抛 ActionFailed 且带上信封字段",
                exc.retcode == 100 and exc.status == "failed" and exc.detail == "请求失败",
                str(exc),
            )

        started = time.monotonic()
        try:
            await conn.call_action("no_reply", timeout=0.5)
            runner.check("A9 无应答超时抛 ConnectionUnavailable", False, "没有抛异常")
        except ConnectionUnavailable:
            elapsed = time.monotonic() - started
            runner.check("A9 无应答超时抛 ConnectionUnavailable", elapsed < 2.0, f"{elapsed:.2f}s")

        # 超时边界：0.2s 的慢应答要在 1s 超时内成功
        mock.slow_actions["get_status"] = 0.2
        slow_ok = await conn.call_action("get_status", timeout=1.0)
        # 2.0s 的慢应答必须在 0.5s 超时内失败
        mock.slow_actions["get_status"] = 2.0
        slow_failed = False
        try:
            await conn.call_action("get_status", timeout=0.5)
        except ConnectionUnavailable:
            slow_failed = True
        finally:
            mock.slow_actions.pop("get_status", None)
        runner.check(
            "A9b 慢应答边界（0.2s 内成功 / 2.0s 超时）",
            slow_ok.get("online") is True and slow_failed,
            f"slow_ok={slow_ok} slow_failed={slow_failed}",
        )

        try:
            await conn.call_action("definitely_not_an_action")
            runner.check("A10 未知动作 1404 按失败处理", False, "没有抛异常")
        except ActionFailed as exc:
            runner.check("A10 未知动作 1404 按失败处理", exc.retcode == 1404, str(exc))

        # A11：发一个「永远不回」的动作，然后从 mock 侧掐断连接
        pending_task = asyncio.create_task(conn.call_action("no_reply", timeout=10))
        in_flight = await wait_until(lambda: conn.pending_actions == 1)
        await mock.clients[0].close()
        try:
            await asyncio.wait_for(pending_task, 3)
            runner.check("A11 断线后在途请求立即失败", False, "没有抛异常")
        except ConnectionUnavailable:
            runner.check("A11 断线后在途请求立即失败", in_flight)
        except asyncio.TimeoutError:
            runner.check("A11 断线后在途请求立即失败", False, "一直等到超时了")

        runner.check("A12 断线后 connected=False", await wait_until(lambda: not conn.connected))

        # ============================================== B 组：发送与边界（9 项）
        runner.check(
            "B6 断线后自动重连（指数退避）",
            await wait_until(lambda: conn.connected and len(mock.clients) == 1, 6),
        )

        mock.actions.clear()
        data = await conn.send_message("hi", message_type="group", group_id=123456)
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B1 send_msg 群消息参数正确",
            data.get("message_id") == 1
            and sent.get("message_type") == "group"
            and sent.get("group_id") == 123456
            and sent.get("auto_escape") is False,
            str(sent),
        )
        runner.check(
            "B2 message 是消息段数组（跟随 array 格式）",
            isinstance(sent.get("message"), list)
            and sent["message"][0]["type"] == "text"
            and sent["message"][0]["data"]["text"] == "hi",
            str(sent.get("message")),
        )

        mock.actions.clear()
        await conn.send_message("hi", message_type="private", user_id="169699201")
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B3 私聊不带 group_id，且 id 转成 int",
            sent.get("message_type") == "private"
            and sent.get("user_id") == 169699201
            and "group_id" not in sent,
            str(sent),
        )

        await mock.push(group_message("ping", message_format="string"))
        detected = await wait_until(lambda: conn.message_format_detected == "string")
        mock.actions.clear()
        await conn.send_message("hi", message_type="group", group_id=1)
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B4 收到 string 事件后改为 CQ 字符串出参",
            detected and isinstance(sent.get("message"), str) and sent["message"] == "hi",
            str(sent.get("message")),
        )

        mock.actions.clear()
        await conn.send_message("[CQ:at,qq=1]", message_type="group", group_id=1, auto_escape=True)
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B5 auto_escape=True 时 CQ 码原样透传",
            sent.get("auto_escape") is True and sent.get("message") == "[CQ:at,qq=1]",
            str(sent),
        )

        await conn.stop()
        runner.check("B7 stop() 后 connected=False", not conn.connected)
        try:
            await conn.call_action("get_status", transport="ws")
            runner.check("B8 无通道 + transport=ws 抛 ConnectionUnavailable", False, "没有抛异常")
        except ConnectionUnavailable:
            runner.check("B8 无通道 + transport=ws 抛 ConnectionUnavailable", True)
        try:
            await conn.call_action("get_status", transport="auto")
            runner.check("B9 无通道 + auto 时暂抛（M5 接上 HTTP 后会改）", False, "没有抛异常")
        except ConnectionUnavailable:
            runner.check("B9 无通道 + auto 时暂抛（M5 接上 HTTP 后会改）", True)
    finally:
        await conn.stop()
        await mock.stop()
    return runner.finish()


def test_connection_against_mock():
    # 断言失败时 finish() 返回 1 → 测试红；全过返回 0 → 测试绿
    assert asyncio.run(_case()) == 0
```

---

## 9. 跑起来

```powershell
# ① 先确认 mock 自检还是绿的（M3 的成果）
python tests\mock_snowluma.py

# ② 跑 M4 用例
python -m pytest tests\test_connection.py -q

# ③ 想看逐条 PASS/FAIL 明细（pytest 会吞掉 print，加 -s）
python -m pytest tests\test_connection.py -q -s
```

期望输出（③）：

```
  [PASS]  A1 正向连接建立
  [PASS]  A2 登录探测拿到 self_id / nickname
  ...
==== 共 22 项，失败 0 项 ====
1 passed
```

> **`pytest tests/` 现在是安全的**：`tests/test.py` 已经删除；而且 pytest 默认只收集
> `test_*.py` / `*_test.py`，非 `test_*.py` 的文件本来就不会被收集。想快一点也可以直接指定文件跑。

想看 debug 级日志：在用例开头加一个 stdout sink 即可（`log.py` 的默认级别由
`record["extra"].get("log_level", "INFO")` 决定），例如：

```python
from loguru import logger
logger.add(sys.stdout, level="DEBUG")
```

### 9.1 别把库文件当脚本跑（`No module named 'log'`）

**症状**：直接运行库文件，或让 IDE「运行当前文件」：

```powershell
python snowluma\connection.py
# Traceback (most recent call last):
#   File "D:\Projects\HysialX\snowluma\connection.py", line 22, in <module>
#     from log import logger
# ModuleNotFoundError: No module named 'log'
```

**原因**：`log` 是**项目根目录下的顶层模块**，只在「项目根在 `sys.path` 上」时才 import 得到。
而 Python 决定 `sys.path[0]` 的规则是：

| 启动方式 | `sys.path[0]` | 结果 |
| --- | --- | --- |
| `python snowluma\connection.py` | `...\HysialX\snowluma`（**脚本所在目录**） | ❌ 找不到 `log` |
| `python -m pytest tests\test_connection.py` | `...\HysialX`（**当前工作目录**） | ✅ |
| `python -c "import snowluma.connection"` | `''` → 即当前工作目录 | ✅ |
| `python -m snowluma.connection` | `...\HysialX`（当前工作目录） | ✅ 相对导入正常，但模块里没有 `__main__` 块，所以**什么都不会打印** |

> 顺便说：即便你把 `log` 找出来了，第 24 行的 `from .config import SnowLumaConfig` 也会接着报
> `attempted relative import with no known parent package`——因为文件是被当**脚本**执行的，
> 不属于任何包。**库文件只能用「导入」的方式跑，不能直接执行。**

**三种正确做法**（都在项目根执行）：

```powershell
# ① 快速自检「能不能 import」（推荐用来替代直接运行文件）
python -c "import snowluma.connection as c; print('OK', c.__all__)"

# ② 跑测试（-m 会把当前目录放进 sys.path）
python -m pytest tests\test_connection.py -q -s

# ③ 真的需要一段命令行脚本时，把它放到 tests/ 或 tools/ 下用 -m 跑，别塞进 snowluma/
```

**为什么改 import 救不了它**：把 `from .config import ...` 改成 `from snowluma.config import ...`
（绝对导入）在「脚本方式」下**照样失败**——脚本方式下 `sys.path[0]` 是 `snowluma\`，
项目根不在路径上，所以 `import snowluma` 本身就 `ModuleNotFoundError`。
一句话：**包内模块 + 脚本方式 = 死路**，只能用「导入」跑。

**要是你就想让 `python -m snowluma.connection` 有个输出**（纯开发便利，可选）：
在 `connection.py` 末尾加一个自检块——

```python
if __name__ == "__main__":          # 只在使用 python -m snowluma.connection 时执行
    print("connection.py OK:", __all__)
```

但正式验证还是要走 pytest：`python -m pytest tests\test_connection.py -q -s`
（它会在真实 mock 断连/超时/风控失败下跑完 22 项，比「能不能 import」有用得多）。

**IDE 配置**（PyCharm / VSCode 都会踩）：

- Working directory / `cwd` 设成 `D:\Projects\HysialX`；
- 别用「Run Python File」跑 `snowluma/*.py`（它等价于 `python snowluma\connection.py`）；
  要跑就配一个 **pytest 运行配置**，target 选 `tests/test_connection.py`；
- PyCharm 勾上 `Add content roots to PYTHONPATH`、VSCode 用 `python -m pytest` 即可。

**可选加固 ①（推荐，改 2 行）**：让协议内核不依赖项目根的 `log` 模块。
loguru 的 `logger` 是**全局单例**，`log.py` 只是给它 `remove()` + `add()` 配 sink，
所以内核直接 `from loguru import logger` 也能拿到同一个 logger——只要程序入口
（`main.py`）import 过 `log`，格式与文件 sink 全都照旧：

```python
# snowluma/connection.py 与 snowluma/config.py
from loguru import logger        # 原来是 from log import logger
```

好处：`snowluma/` 变成自包含的内核包，任何 cwd、任何宿主项目都能 import；
跑单测时也不会往 `logs/HysialLog.log` 里写测试日志（这其实是好事）。
只有当「谁都没 import 过 `log.py`」时，你看到的是 loguru 默认格式——对单测来说正合适。

**可选加固 ②（更省事但略丑）**：保留原样，加一层兜底：

```python
try:
    from log import logger                 # 正常：走项目统一的格式与 sink
except ModuleNotFoundError:                # 兜底：被当脚本/独立导入时不至于炸
    from loguru import logger
```

> 记住这条：**`ModuleNotFoundError: No module named 'xxx'` 里 xxx 是项目根下的顶层模块时，
> 九成是「运行方式」问题，而不是代码问题。** 先看 `sys.path[0]` 是谁。

---

## 10. 排障表

| 症状 | 原因 | 修法 |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'log'`（指向 `snowluma/connection.py`） | 把库文件当脚本跑了：`python snowluma\connection.py` 时 `sys.path[0]` 是 `snowluma\` 而不是项目根；IDE「运行当前文件」同罪 | 从项目根 `python -m pytest ...`；自检用 `python -c "import snowluma.connection"`（§9.1） |
| 接着 `log` 之后又报 `attempted relative import with no known parent package` | 同上：文件被当脚本执行，不属于任何包 | 同上；库文件只能用导入方式跑 |
| A2 时好时坏 / `login_info=None` | 断言等的是 `self_id`，而它已被 lifecycle 事件提前填上（探测还没回来） | 改成等 `login_info` 有内容（§8 A2 的注释） |
| A9b 之后紧接着的动作全部超时 | mock 的 `slow_actions` 用 `await` 睡，把 mock 的单读者堵住了 | 改成 `create_task` 延迟应答（§2.3） |
| A2 一直不过，日志里没有「Connected successfully!」 | 探测是在读循环之前 `await` 的 → 自己等自己 | 探测必须 `create_task`（§4.3） |
| A2/A3 时好时坏 | `_probe_task` 没做去重，lifecycle 又触发了一次 | `_schedule_probe` 里判 `not done()` |
| 所有动作都超时，但 mock 明明回了 | 应答被当成事件丢弃了：`_handle_payload` 里先判了 `post_type` | echo 判定必须在 `post_type` 之前 |
| `Future exception was never retrieved` 警告 | `_call_ws` 的 `finally` 少了 `future.cancel()` | 见 Step 6 |
| A11 失败（一直等到 10s 超时） | `_unregister` 没调 `_fail_pending` | 最后一条通道注销时必须唤醒在途请求 |
| `stop()` 之后进程不退出 | `except Exception` 吃掉了 `CancelledError` | `except asyncio.CancelledError: raise` 放最前 |
| 断线后疯狂重连、日志刷屏 | 退避没有递增/封顶，或 `_closing` 没判 | `backoff = min(backoff*2, 60)`，循环头判 `_closing` |
| 连不上真实 SnowLuma，报 `TypeError: connect() got an unexpected keyword argument 'proxy'` | websockets 14 没有 `proxy` 参数 | 删掉 `proxy=None`（本机 16.0 可留） |
| 真实雪花事件里图片丢帧 / 连接被重置 | `max_size` 用了默认 1MB | `max_size=_MAX_MESSAGE_SIZE`（16MB） |
| 连上后**立刻**断开、日志刷 `sent 1000 (OK); then received 1000 (OK)`、每秒重连一次 | `_forward_loop` 里没有 `await self._pump(channel)`：`async with` 的 body 一执行完就正常退出并关连接（关闭码 1000） | 补上 `try: await self._pump(channel) finally: self._unregister(channel)`（Step 9） |
| 连得上，但**所有动作都超时**，日志里又没有任何异常 | `_pump` 里把 `json.loads` 写成了 `json.dumps` → payload 是 `str`，`isinstance(payload, dict)` 恒为 False，应答永远投递不到 future | `payload = json.loads(raw)`（Step 4） |
| `RuntimeError: dictionary changed size during iteration`（在 `_fail_pending`） | 一边 `for ... in self._pending.items()` 一边 `pop` | 遍历 `list(self._pending.items())`（Step 3） |
| `TypeError: ConnectionClosed.__init__() missing 1 required positional argument: 'sent'` | 把 websockets 的 `ConnectionClosed` 当成普通异常来构造了（它需要 `sent`/`received` 两个连接状态对象） | 换成 `ConnectionUnavailable("连接已关闭")`（Step 2 的 `stop()`） |
| `RuntimeWarning: coroutine 'wait_for' was never awaited`，而且断言**假通过** | `wait_until_connected` 里少了 `await` → 函数走到 `return True`，根本没等 | 补 `await asyncio.wait_for(self._connected.wait(), timeout)` |
| `stop()` 里 `await channel.close("HysialX shutting down")` 没关掉连接 | `Channel.close(code, reason)` 的**第一个参数是 code**，字符串被当成关闭码，异常又被 `except Exception` 静默吞掉 | 写全：`await channel.close(1001, "HysialX shutting down")` |

### 10.1 三条诊断手艺（这次调试里学到的）

**① 关闭码能告诉你「谁先关的」**

| 关闭码 | 含义 | 第一反应 |
| --- | --- | --- |
| `1000 (OK)` | 正常关闭 | **多半是自己这边主动关的**：检查 `async with` / `try-finally` 的结构 |
| `1001 (going away)` | 收摊（进程退出、服务端关闭监听） | 对端在关，看对端日志 |
| `1006 (ABNORMAL_CLOSURE)` | 异常断开 | 网络问题、端口被占、对端进程被杀 |

异常串 `sent 1000 (OK); then received 1000 (OK)` 里 **`sent` 在前 = 关闭帧是我们先发的**。
所以「连上就断 + 1000」几乎总是本地代码结构问题，不是网络问题。

**② 「测试变绿」不等于「代码正确」**

这次 A1 曾经是**假通过**：`wait_until_connected` 少了 `await`，函数直接 `return True`，
哪怕连接根本没建立。识别办法是看 pytest 的 warnings 段——`RuntimeWarning: coroutine ... was never awaited`
就是「有协程被创建却没被等待」。所以 §11 验收清单里「故意让断言变红」那两条不是形式主义：
**只有能变红的断言才算断言。**

**③ 退避被重置 = 连接其实每次都成功**

日志显示「每秒重连一次、退避始终 1s」时，别急着查网络——`backoff` 在 `_register` 之后会被重置为
`reconnect_interval`，所以「始终 1s」恰恰证明**每次 `connect()` 都成功了**，问题出在「连上之后谁把连接关了」。
反过来，如果日志里间隔按 1→2→4→8… 递增，那才是真的连不上。

---

## 11. 验收清单

- [ ] `Channel` 修完 `remote`、补上 `close`
- [ ] `mock_snowluma.py` 的 `slow_actions` 补上 `await`
- [ ] `OneBotConnection` 的 13 个字段与 3 个只读属性齐全
- [ ] `_pump` 是唯一的读循环；探测走 `create_task`
- [ ] `call_action` 实现了「只有没通道才走 HTTP」的策略
- [ ] `tests/test_connection.py` 跑出 **22 项，失败 0 项 / 1 passed**
- [ ] 故意把 mock 的 `no_reply` 改成会回应答 → A9 变红（**证明断言有效**）
- [ ] 故意删掉 `_fail_pending` 的调用 → A11 变红
- [ ] 故意把 `forward_url` 改成错误端口 → A1 变红、日志出现递增退避（**证明 A1 不是假通过**）
- [ ] `git diff` 里只有 `snowluma/connection.py`、`tests/mock_snowluma.py`、`tests/test_connection.py` 三个文件

---

## 12. 下一步（M5 预告）

M5 = **反向 WS 服务端 + HTTP 兜底**，你需要：

| 要做的事 | 位置 | 关键点 |
| --- | --- | --- |
| 反向服务端 | `OneBotConnection._reverse_server_loop` | `websockets.serve(handler, host, port, process_request=...)`；新 API 的 handler **只接一个参数** |
| 握手鉴权 | `_process_reverse_request` | 用你已写好的 `_extract_token(path, headers)`；不匹配 `return connection.respond(401, "Unauthorized\n")` |
| 反向接入处理 | `_reverse_handler` | 复用 `_register` / `_pump` / `_schedule_probe`，一行都不用改 |
| HTTP 兜底 | 把 `_call_http` 换成真实现（**已完成**） | `httpx.AsyncClient(base_url, headers=auth)` + `post(config.http_url(action), json=params)` |
| 端口占用重试 | 反向循环 | 捕获 `OSError` 记日志并按间隔重试，**不能让进程退出** |
| mock 扩展 | `tests/mock_snowluma.py` | M3 教程 §9.1 已给出 `connect_reverse()` / `drop_clients()` 的写法（把 `_ws_handler` 的循环体抽成 `_pump` 复用） |
| 用例 | `tests/test_connection.py` | C 组 6 项（错 token 401、接入成功、反向发 `send_msg`、反向收事件、反向探测、多连接）+ D 组 5 项（HTTP 兜底、Bearer、URL、body=params、不偷偷走 HTTP） |

M5 完成后，`api_transport` 的三条语义（§5 的表）就全齐了，`B9` 那条断言要改成
「无通道 + auto → 走 HTTP 成功」。
