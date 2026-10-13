# M3 教程：自建 SnowLuma（OneBot v11）mock 协议端

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。
>
> 配套文档：[设计文档](snowluma-protocol-design.md) §11.1（39 项断言清单）、§2（协议事实）。
> 本教程里的完整代码已在**本机 Python 3.12.10 + websockets 16.0** 上实际跑通，
> 自检 11/11 通过；你照着敲完就能得到同样的结果。

---

## 0. 这一步的交付物（DoD）

M3 结束时，你应当拥有一个**不依赖 SnowLuma、不依赖 QQ、只依赖 `websockets` + 标准库**的
假协议端，它满足：

| # | 判据 | 怎么证明 |
| --- | --- | --- |
| 1 | 能起一个正向 WS 服务端，带 token 校验 | 错 token 连接返回 401 |
| 2 | 连接建立后自动推 `lifecycle` meta 事件 | 客户端 `recv()` 第一帧就是它 |
| 3 | 能按动作返回不同的 `data`，并回填 `echo` | 手工发 `get_login_info` 能收到信封 |
| 4 | 能注入三类故障：不回应答、不回填 echo、`retcode != 0` | 自检里各有一项断言 |
| 5 | 能起一个 HTTP API 服务端，校验 `Authorization: Bearer` | 缺 token 返回 401 |
| 6 | 能把事件「推」给已连接的客户端 | 自检里推一条群消息并被收到 |
| 7 | 记录所有收到的动作请求，供用例断言 | `mock.actions` / `mock.http_actions` |
| 8 | 自带 `check()` / 退出码 | `check()` 收集断言，`finish()` 全过返回 0、有一条失败返回 1（**`CaseRunner` 没有 `wait_until`**，等待逻辑写在用例里，见 `tests/test_connection.py` 的 `wait_until`） |
| 9 | 提供事件工厂函数，用例读起来像自然语言 | `group_message("ping")`、`notice("group_increase")` |
| 10 | `python tests/mock_snowluma.py` 能自检自己 | `_self_test()` 返回退出码、末行打印「共 N 项，失败 N 项」（`__main__` 只 print，进程退出码恒为 0） |

**注意**：M3 只写 mock，**不写** `snowluma/connection.py`。mock 先行的意义就在于此。

---

## 1. 为什么必须先写 mock

1. **把不确定性前移**。收发层最大的风险不是「写不出来」，而是「不知道对端到底怎么回」。
   mock 把你对协议的理解**固化成一个可执行的假设**；等你连真机时，两边不一致的地方会
   自动暴露成一条失败的断言，而不是「消息发出去了但没人回」这种玄学。
2. **真机不可控、不可重复**。真实 SnowLuma 不会为了你牺牲一次：不会给你发 1404、不会
   在半路断线、不会延迟 3 秒才回应答、更不会等你把超时逻辑调好。mock 可以随便折腾。
3. **不碰真实 QQ 账号**。M4~M8 有大量「故意制造失败」的测试（超时、断连、风控错误码）。
   对着真实账号做这些，轻则刷屏，重则风控。
4. **回归成本**。收发层改一行、39 项断言跑 5 秒；连真机验证一次要有人发消息配合。

**反例**（本仓库真实踩过的坑）：没有 mock 时，验证只能靠「连真机 → 群里发消息」，
结果就是 `plugins/XHuaLao` 的统计插件把 `DataForXPlugin/GroupStatistics.json` 写了，
`plugins/t` 的签到把 `wealth.json` 覆盖了。数据文件的污染就是这么来的。
**动手前先备份**：

```powershell
Copy-Item DataForXPlugin DataForXPlugin.bak -Recurse -Force
```

---

## 2. mock 要模拟的「最小协议子集」

不要试图实现 115 个动作。只需要下面这张表，就够驱动 M4~M8 的全部断言：

| 能力 | mock 需要表现的行为 |
| --- | --- |
| 正向 WS 握手 | 校验 `?access_token=` / `Authorization: Bearer`，不匹配 → `401` |
| 连接即上报 | 首帧推 `{"post_type":"meta_event","meta_event_type":"lifecycle","sub_type":"connect"}` |
| 动作应答 | 读 `{action, params, echo}`，回 `{status, retcode, data, message, wording, echo}` |
| 动作分派 | `get_login_info` / `get_version_info` / `get_status` / `get_group_info` / `get_group_list` / `send_msg` 各返回不同 `data` |
| 未知动作 | `status=failed, retcode=1404, message="unknown action"` |
| 故障注入 A | 动作 `no_reply`：**完全不回**（测客户端超时） |
| 故障注入 B | 动作 `echo_less`：回信封但**不带 echo**（测宽容匹配） |
| 故障注入 C | 动作 `fail_test`：`retcode=100`（测错误信封解析） |
| 故障注入 D | `send_msg` 且 `group_id=999` → `retcode=100`（测发送失败只告警） |
| 故障注入 E | `mock.slow_actions[action] = 秒数`（测超时边界） |
| 事件推送 | 向所有已连接客户端广播任意事件 JSON |
| HTTP API | `POST /{action}`，校验 Bearer，**body 就是 params**，返回同一套信封 |
| 记录 | 保存收到的全部动作请求与 HTTP 请求，供断言读取 |

**两条纪律**：

- mock **绝不 import `api/` 或 `snowluma/`**。一旦 import，测试就变成「自己验证自己」，
  协议理解错误会被两边同时犯而互相掩盖。
- mock 只暴露「发送」能力，**不做任何断言**。断言属于用例（M4 起）。

---

## 3. 环境与目录约定

```
D:\Projects\HysialX\
├─ tests\
│  ├─ mock_snowluma.py      # M3 交付：mock 本体 + 自检（可独立运行）
│  └─ test_connection.py    # M4 起：用 mock 驱动的用例（导入 mock_snowluma）
└─ docs\
   └─ m3-mock-snowluma-tutorial.md
```

依赖：`websockets>=14`（本机 16.0）、`httpx`（项目已有，仅自检用）、其余为标准库。

### 3.1 端口怎么选（本机实测的坑）

**不要用 `3000` / `3001`**——真实 SnowLuma 默认就占这两个。
更麻烦的是：即使没人占用，Windows 上有些端口会 **bind 失败并抛 `WinError 10013`**
（`PermissionError: [Errno 13]`）。本机实测：`3010`、`3011`、`3070`、`13080` 全部 10013，
而 `18080`~`18083` 正常。这是 Hyper-V / WSL / Docker 的**动态端口保留区间**造成的，
不是你的代码问题。

所以教程统一用：

```
HTTP_PORT   = 18080
WS_PORT     = 18081
REVERSE_PORT= 18082     # M5 反向 WS 用
```

先用这段小脚本做「端口体检」（挑一个能 bind 的再用）：

```python
import socket

def can_bind(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError as exc:
        print(f"{port} 不可用: {exc}")
        return False
    finally:
        s.close()

for p in (18080, 18081, 18082):
    print(p, can_bind(p))
```

万一 10013 命中了你想要的端口，排查顺序：

```powershell
# 看系统保留了哪些端口段（普通用户即可查看）
netsh interface ipv4 show excludedportrange protocol=tcp
# 看是谁在监听
netstat -ano | findstr :18081
# 换端口（最快），或者重启 winnat 服务（需要管理员）
```

---

## 4. 分步搭建（每步都有中间验收）

### Step 1 · 信封工厂先写

协议里所有交互都过这个壳，先把它钉死：

```python
def envelope(request, *, data=None, status="ok", retcode=0, message="", wording="") -> dict:
    payload = {"status": status, "retcode": retcode, "data": data,
               "message": message, "wording": wording}
    if request.get("echo") is not None:     # HTTP 请求没有 echo 就不回填
        payload["echo"] = request["echo"]
    return payload
```

> 细节：`echo` 用 `is not None` 判断而不是 `request.get("echo")`，因为 `echo` 可能是
> `0`、`""` 这种 falsy 值，用真值判断会漏回填。

**中间验收**：`envelope({"echo": "e1"})["echo"] == "e1"`，`envelope({})` 里没有 `echo` 键。

### Step 2 · 动作应答表

用一个方法集中分派，先只实现 6 个动作 + 4 个故障注入，其余一律 1404：

```python
def reply_to(self, request: dict) -> dict:
    action = request.get("action")
    params = request.get("params") or {}
    if action in self.handlers:            # 用例可以注册自己的应答
        return self.handlers[action](request)
    if action == "get_login_info":
        return envelope(request, data={"user_id": SELF_ID, "nickname": NICKNAME})
    ...
    if action == "send_msg" and params.get("group_id") == 999:
        return envelope(request, status="failed", retcode=100, wording="账号可能被风控")
    if action == "no_reply":  ...          # 实际由调用方跳过发送
    return envelope(request, status="failed", retcode=1404, message="unknown action")
```

> **为什么要 `self.handlers` 这个扩展点**：M4 的用例里会出现「这个动作应该返回 X」的
> 一次性需求。有了它，用例写 `mock.handlers["get_group_info"] = lambda r: envelope(r, data={...})`，
> 不必回头改 mock。

**中间验收**：`mock.reply_to({"action": "get_login_info", "echo": "e"})["data"]["user_id"]` 正确；
未知动作得到 `retcode=1404`。

### Step 3 · 正向 WS 服务端 + token 校验

```python
async def start(self):
    self._ws_server = await websockets.serve(
        self._ws_handler, "127.0.0.1", self.ws_port,
        process_request=self._check_ws_token,   # 握手阶段鉴权
        max_size=None,                          # 事件可能带 base64 图片
    )

async def _ws_handler(self, connection):
    """步骤 3 先放个占位实现（否则 start() 会引用到不存在的方法）；
    Step 4 会把它换成完整版：推 lifecycle + 记录动作 + 故障注入 + 应答。"""
    self.clients.append(connection)
    async for raw in connection:
        print("[mock] 收到:", raw)

def _check_ws_token(self, connection, request):
    if not self.ws_token:
        return None
    if token_of(request.path, request.headers) == self.ws_token:
        return None
    return connection.respond(401, "Unauthorized\n")   # 拒绝握手
```

四个必须记住的 websockets（>=14 新 asyncio API）细节：

1. handler **只接收一个参数**（`ServerConnection`）。旧教程里的 `(ws, path)` 会直接 `TypeError`。
2. 拒绝握手用 `connection.respond(status, text)`，返回**非 None** 即表示拒绝。
3. **`self._ws_handler` 必须存在，但它在类里的定义顺序不重要**：`websockets.serve(...)` 收到的
   是一个「只接收一个参数的绑定方法」（`async def _ws_handler(self, connection)` 正好对应新 API
   的 handler 签名）。Python 是在 `start()` **被调用时**才去取 `self._ws_handler`，所以把它写在
   `start()` 之后、甚至写在文件更靠后的位置都没问题；真正的坑是「传 `self._ws_handler()`（多写了
   一对括号，变成调用）」或仍按旧版写 `(self, ws, path)`。上面 Step 3 之所以先给个占位实现，
   就是为了让这一步自身可运行。
4. token 要同时兼容查询参数与 Header（真实 SnowLuma 两种都支持，客户端可能只带一种）：

```python
def token_of(path: str, headers) -> Optional[str]:
    query = parse_qs(urlsplit(path).query)
    if query.get("access_token"):
        return query["access_token"][0]
    auth = headers.get("Authorization")
    if auth:
        prefix, _, value = str(auth).partition(" ")
        return value.strip() if prefix.lower() == "bearer" else str(auth).strip()
    return None
```

**中间验收**：错 token 的客户端连接时收到 `InvalidStatus(401)`；对 token 能连上。

#### Step 3 补：`connection` 到底是什么类型（本机实测 websockets 16.0）

| 位置 | 运行时类型 | 备注 |
| --- | --- | --- |
| `_check_ws_token(self, connection, request)` | `websockets.asyncio.server.ServerConnection`（`request` 是 `websockets.http11.Request`） | `.respond()` 只有它才有，所以拒绝握手必须在这儿做 |
| `_ws_handler(self, connection)` | 同上 `ServerConnection` | 有 `.remote_address` / `.send()` / 可 `async for` |
| `await websockets.connect(...)` 的返回值 | `websockets.asyncio.client.ClientConnection` | 同样有 `.remote_address` / `.send()` / 可 `async for`，**没有** `.respond()` |
| §9.1 重构后的 `_pump(self, connection)` | 上面两者的**共同基类** `websockets.asyncio.connection.Connection` | 正/反向共用，所以 `_pump` 里只能用两者的公共 API |

MRO 实测：

```
ServerConnection → Connection → Protocol → BaseProtocol → object
ClientConnection → Connection → Protocol → BaseProtocol → object
共同祖先        → websockets.asyncio.connection.Connection
```

要写类型标注就这么写（`_pump` 千万别标成 `ServerConnection`，否则 `connect_reverse`
传进来的 `ClientConnection` 与标注不符，一旦调用 `.respond()` 才在运行时炸）：

```python
from websockets.asyncio.client import ClientConnection      # 反向模式用
from websockets.asyncio.connection import Connection        # _pump 的公共标注
from websockets.asyncio.server import ServerConnection      # 正向服务端
from websockets.http11 import Request

def _check_ws_token(self, connection: ServerConnection, request: Request): ...
async def _ws_handler(self, connection: ServerConnection) -> None: ...
async def _pump(self, connection: Connection) -> None: ...          # 正/反向都能传
```

两个常见误区：

- 这个对象**不是 dict，也不是 legacy 的 `WebSocketServerProtocol`**。websockets < 14 的旧 API
  会给 handler 传 `(protocol, path)` 两个参数，新版只传这一个对象。所以
  `connection.get("remote_address")` 会 `AttributeError`（要写
  `getattr(connection, "remote_address", None)`）；`path` 也不在 handler 参数里了，
  需要路径就在 `process_request` 里取 `request.path`。
- 别把标注写成 `Protocol`：`Protocol` / `BaseProtocol` 是更底层的事件驱动基类，
  日常要标的是提供 `send / recv / close / async for` 的 `Connection` 这一层。

### Step 4 · 读循环 + 记录 + 故障注入

```python
async def _ws_handler(self, connection):
    self.clients.append(connection)
    try:
        if self.auto_lifecycle:
            await connection.send(json.dumps(meta_lifecycle("connect"), ensure_ascii=False))
        async for raw in connection:
            request = json.loads(raw)
            self.actions.append(request)                  # 先记录，再决定怎么回
            action = request.get("action")
            if action == "no_reply":
                continue                                  # 故障注入 A：不回
            if (delay := self.slow_actions.get(action)):
                await asyncio.sleep(delay)                # 故障注入 E：慢应答
            await connection.send(json.dumps(self.reply_to(request), ensure_ascii=False))
    except ConnectionClosed:
        pass
    finally:
        if connection in self.clients:
            self.clients.remove(connection)
```

**先记录再回复**很关键：即使后面回包逻辑抛异常，请求也已经留在 `mock.actions` 里，
断言不会因为「mock 自己崩了」而变成含糊的失败。

**中间验收**：`mock.actions_named("get_login_info")` 能拿到请求；
`mock.slow_actions["get_status"] = 2.0` 时客户端会等 2 秒。

### Step 5 · 事件工厂 + 推送

工厂函数让用例可读性提升一个档次——对比一下：

```python
await mock.push({"post_type": "message", "message_type": "group", "group_id": 123456,
                 "user_id": 169699201, "message": [{"type": "text", "data": {"text": "ping"}}],
                 "raw_message": "ping", "sender": {"user_id": 169699201, "nickname": "雨弈",
                 "card": "群名片", "role": "owner"}, "time": int(time.time()),
                 "self_id": 999, "message_id": 12345, "font": 0, "sub_type": "normal"})

await mock.push(group_message("ping"))          # 等价，且不易写漏字段
```

工厂必须支持 `message_format="array" | "string"` 两种（这正是 M4 的断言点）：

```python
def group_message(text, *, message_format="array", **kw) -> dict:
    segs = [_seg("text", text=text)]
    return {
        "message": segs if message_format == "array" else text,
        "raw_message": text,
        ...
    }

async def push(self, payload: dict) -> int:
    sent = 0
    for connection in list(self.clients):
        try:
            await connection.send(json.dumps(payload, ensure_ascii=False)); sent += 1
        except ConnectionClosed:
            pass
    return sent
```

**中间验收**：一个客户端连上后，`await mock.push(group_message("ping"))` 返回 `1`，客户端收到该事件。

> 推事件前要确保客户端已连上，否则 `push` 返回 0、用例却以为发了。用例里统一写成
> `await wait_until(lambda: bool(mock.clients))`（`wait_until` 定义在用例文件里，
> 见 `tests/test_connection.py`）再 push。

### Step 6 · HTTP API 通道

用标准库 `ThreadingHTTPServer` + 独立线程即可，**不引入第二个 Web 框架**：

```python
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # 复用连接，快；前提是 Content-Length 必须准确

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        params = json.loads(body or b"{}")
        action = self.path.strip("/").split("?")[0]
        auth = self.headers.get("Authorization", "")
        outer.http_actions.append({"action": action, "params": params, "auth": auth, "path": self.path})
        if outer.http_token and auth != f"Bearer {outer.http_token}":
            self._write(401, json.dumps({...,"retcode":1403}).encode()); return
        self._write(200, json.dumps(outer.reply_to({"action": action, "params": params})).encode())

    def log_message(self, *args):   # 关掉标准库的访问日志，别刷屏
        return
```

要点：

- **HTTP 的 body 就是 `params`**（不是 `{action, params}` 包裹），这是 OneBot v11 的约定，
  也是 M4 的一条断言（文档 §11.1-D #33）。
- 线程里**不要碰 asyncio**：`http_actions` 用普通 list 追加即可（CPython 下 `list.append` 原子），
  别去 `loop.call_soon_threadsafe`，除非你确实要触发事件。
- 退出时 `server.shutdown()` + `server_close()`，并把线程设为 `daemon=True`，
  否则 `ThreadingHTTPServer` 会让进程不退出。

**中间验收**：

```powershell
# Windows PowerShell 推荐用 Invoke-RestMethod（引号不用转义）
Invoke-RestMethod -Uri http://127.0.0.1:18080/send_msg -Method Post `
  -ContentType 'application/json' -Headers @{ Authorization = 'Bearer httptoken' } `
  -Body '{"message_type":"group","group_id":1,"message":"hi"}'
# → data.message_id = 1

# 或者用真 curl（PowerShell 里 curl 是 Invoke-WebRequest 的别名，要写 curl.exe）
curl.exe -s -X POST http://127.0.0.1:18080/send_msg -H "Content-Type: application/json" ^
  -H "Authorization: Bearer httptoken" -d "{\"message_type\":\"group\",\"group_id\":1,\"message\":\"hi\"}"
```

### Step 7 · 用例运行器

mock 只提供「记录 + 推送」，断言框架单独一个小类，M4 起每个用例文件都复用它：

```python
class CaseRunner:
    def check(self, name, ok, detail=""): ...          # 收集结果 + 即时打印 PASS/FAIL
    def finish(self) -> int:                           # 打印汇总，返回退出码 0/1
```

- **等待逻辑不放进 `CaseRunner`**：`CaseRunner` 只管断言（`check` / `finish`），
  等待放在用例文件里自己写一个 `wait_until(predicate, timeout=...)`（见
  `tests/test_connection.py`），等待与断言分开，失败信息更干净。
- **所有等待都要有超时**：`wait_until` 默认 3 秒。没有超时的断言会让失败用例挂死，
  最后你分不清「逻辑错」和「卡住」。
- 用**轮询 predicate** 而不是固定 `sleep`：断言既快又稳。
- **退出码**要正确：全过 0、有失败 1。这样 M4 起就能一键跑、也能接 CI。
- `check()` 要把 `detail` 打出来（失败时），否则失败信息只有名字，你还得回去加 print。

**中间验收**：故意写一条 `runner.check("必失败", False, "试一下")`，确认 `finish()` 返回 1。

### Step 8 · 内置自检

给 mock 加一个 `_self_test()`：它**不测被测代码**，只证明 mock 自己符合协议。
本教程末尾的完整代码里包含 12 项自检，跑 `python tests/mock_snowluma.py` 即可
（`if __name__ == "__main__":` 只 `print` 结果，**不** `SystemExit`，所以进程退出码恒为 0；
要拿退出码请自己 `asyncio.run(_self_test())`）。

---

## 5. 完整代码（已在本机跑通，12/12 通过）

把下面内容存成 `tests/mock_snowluma.py`。
**建议照着手敲一遍**——第 3~4 步那几处 websockets API 细节，抄错一个字母就会报
`TypeError: handler() takes 1 positional argument but 2 were given` 之类，敲一遍印象更深。

```python
"""tests/mock_snowluma.py —— 极简 SnowLuma(OneBot v11) 协议端替身。

只依赖标准库 + websockets；不对接 QQ，也不 import 被测代码。
既能当库用（`async with MockSnowLuma() as mock:`），也能直接跑自检：
    python tests/mock_snowluma.py
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlsplit

import websockets
from websockets.exceptions import ConnectionClosed

# ------------------------------------------------------------------ 默认常量
HTTP_PORT     = 18080
WS_PORT       = 18081
REVERSE_PORT  = 18082
WS_TOKEN      = "testtoken"
HTTP_TOKEN    = "httptoken"
REVERSE_TOKEN = "revtoken"
SELF_ID       = 999
NICKNAME      = "Mock"


# ------------------------------------------------------------------ 信封
def envelope(
    request: dict,
    *,
    data: Any = None,
    status: str = "ok",
    retcode: int = 0,
    message: str = "",
    wording: str = "",
) -> dict:
    """构造 OneBot v11 应答信封；请求带 echo 时才回填 echo（HTTP 请求没有 echo）。"""
    payload: dict[str, Any] = {
        "status": status,
        "retcode": retcode,
        "data": data,
        "message": message,
        "wording": wording,
    }
    if request.get("echo") is not None:
        payload["echo"] = request["echo"]
    return payload


def token_of(path: str, headers) -> Optional[str]:
    """从握手路径或请求头里取 access token。"""
    query = parse_qs(urlsplit(path).query)
    if query.get("access_token"):
        return query["access_token"][0]
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth:
        prefix, _, value = str(auth).partition(" ")
        return value.strip() if prefix.lower() == "bearer" else str(auth).strip()
    return None


# ------------------------------------------------------------------ mock 本体
class MockSnowLuma:
    def __init__(
        self,
        ws_port: int = WS_PORT,
        http_port: int = HTTP_PORT,
        ws_token: str = WS_TOKEN,
        http_token: str = HTTP_TOKEN,
    ) -> None:
        self.ws_port = ws_port
        self.http_port = http_port
        self.ws_token = ws_token
        self.http_token = http_token

        self.actions: list[dict] = []          # WS 收到的动作请求（含 params/echo）
        self.http_actions: list[dict] = []     # HTTP 收到的请求（含 action/params/auth/path）
        self.clients: list = []                # 活着的 WS 连接
        self.handlers: dict[str, Callable[[dict], dict]] = {}   # 动作名 -> 自定义应答
        self.slow_actions: dict[str, float] = {}                # 动作名 -> 延迟秒数
        self.auto_lifecycle = True

        self._ws_server = None
        self._http_server: Optional[ThreadingHTTPServer] = None

    # -------------------------------------------------------- 生命周期
    async def start(self) -> "MockSnowLuma":
        self._ws_server = await websockets.serve(
            self._ws_handler,
            "127.0.0.1",
            self.ws_port,
            process_request=self._check_ws_token,
            max_size=None,
        )
        self._start_http()
        ws_hint = f"?access_token={self.ws_token}" if self.ws_token else "（不校验 token）"
        http_hint = f"Bearer {self.http_token}" if self.http_token else "（不校验 token）"
        print(f"[mock] WS   ws://127.0.0.1:{self.ws_port}/{ws_hint}")
        print(f"[mock] HTTP http://127.0.0.1:{self.http_port}/  POST /{{动作名}}  鉴权: {http_hint}")
        return self

    async def stop(self) -> None:
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()

    async def __aenter__(self) -> "MockSnowLuma":
        return await self.start()

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    # -------------------------------------------------------- 正向 WS
    def _check_ws_token(self, connection, request):
        if not self.ws_token:
            return None
        if token_of(request.path, request.headers) == self.ws_token:
            return None
        print(f"[mock] 拒绝连接（token 不匹配）: {request.path}")
        return connection.respond(401, "Unauthorized\n")

    async def _ws_handler(self, connection) -> None:
        self.clients.append(connection)
        print(f"[mock] 客户端接入: {connection.remote_address}")
        try:
            if self.auto_lifecycle:
                await connection.send(json.dumps(meta_lifecycle("connect"), ensure_ascii=False))
            async for raw in connection:
                request = json.loads(raw)
                self.actions.append(request)
                action = request.get("action")
                if action == "no_reply":                 # 故障注入：完全不回
                    continue
                delay = self.slow_actions.get(action or "")
                if delay:                                # 故障注入：慢应答
                    await asyncio.sleep(delay)
                await connection.send(json.dumps(self.reply_to(request), ensure_ascii=False))
        except ConnectionClosed:
            pass
        finally:
            if connection in self.clients:
                self.clients.remove(connection)
            print("[mock] 客户端断开")

    def reply_to(self, request: dict) -> dict:
        """动作分派表：实现够用即可，其余一律 1404。"""
        action = request.get("action")
        params = request.get("params") or {}

        if action in self.handlers:
            return self.handlers[action](request)
        if action == "get_login_info":
            return envelope(request, data={"user_id": SELF_ID, "nickname": NICKNAME})
        if action == "get_version_info":
            return envelope(request, data={"app_name": "SnowLuma", "app_version": "mock-1.0",
                                           "protocol_version": "v11"})
        if action == "get_status":
            return envelope(request, data={"online": True, "good": True})
        if action == "get_group_info":
            return envelope(request, data={"group_id": params.get("group_id"), "group_name": "测试群"})
        if action == "get_group_list":
            return envelope(request, data=[{"group_id": 123456, "group_name": "测试群"}])
        if action == "_set_model_show":
            return envelope(request, data=None)
        if action == "send_msg":
            if params.get("group_id") == 999:        # 故障注入：模拟风控失败
                return envelope(request, status="failed", retcode=100,
                                message="risk", wording="账号可能被风控")
            return envelope(request, data={"message_id": 1})
        if action == "echo_less":                    # 故障注入：不回填 echo
            response = envelope(request, data={"message_id": 1})
            response.pop("echo", None)
            return response
        if action == "fail_test":                    # 故障注入：业务失败
            return envelope(request, status="failed", retcode=100,
                            message="bad", wording="请求失败")
        return envelope(request, status="failed", retcode=1404, message="unknown action")

    # -------------------------------------------------------- 事件推送
    async def push(self, payload: dict) -> int:
        """向所有已连接客户端广播事件，返回成功发送的连接数。"""
        sent = 0
        for connection in list(self.clients):
            try:
                await connection.send(json.dumps(payload, ensure_ascii=False))
                sent += 1
            except ConnectionClosed:
                pass
        return sent

    def actions_named(self, name: str) -> list[dict]:
        return [a for a in self.actions if a.get("action") == name]

    def last_action(self, name: str) -> Optional[dict]:
        found = self.actions_named(name)
        return found[-1] if found else None

    # -------------------------------------------------------- HTTP API
    def _start_http(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b"{}"
                try:
                    params = json.loads(body or b"{}")
                except json.JSONDecodeError:
                    params = {}
                action = self.path.strip("/").split("?")[0]
                auth = self.headers.get("Authorization", "")
                outer.http_actions.append(
                    {"action": action, "params": params, "auth": auth, "path": self.path}
                )

                if outer.http_token and auth != f"Bearer {outer.http_token}":
                    payload = json.dumps({"status": "failed", "retcode": 1403, "data": None,
                                          "message": "token 校验失败", "wording": ""}).encode()
                    self._write(401, payload)
                    return
                payload = json.dumps(outer.reply_to({"action": action, "params": params}),
                                     ensure_ascii=False).encode()
                self._write(200, payload)

            def _write(self, code: int, payload: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                return

        self._http_server = ThreadingHTTPServer(("127.0.0.1", self.http_port), Handler)
        self._http_server.daemon_threads = True
        threading.Thread(target=self._http_server.serve_forever, daemon=True).start()


# ------------------------------------------------------------------ 事件工厂
def _seg(seg_type: str, **data: Any) -> dict:
    return {"type": seg_type, "data": data}


def group_message(
    text: str,
    *,
    group_id: int = 123456,
    user_id: int = 169699201,
    nickname: str = "雨弈",
    card: str = "群名片",
    message_format: str = "array",
    message_id: int = 12345,
    segments: Optional[list[dict]] = None,
) -> dict:
    segs = segments if segments is not None else [_seg("text", text=text)]
    message: Any = segs if message_format == "array" else text
    return {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "time": int(time.time()),
        "self_id": SELF_ID,
        "message_id": message_id,
        "group_id": group_id,
        "user_id": user_id,
        "message": message,
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": user_id, "nickname": nickname, "card": card, "role": "owner"},
        "anonymous": None,
    }


def private_message(text: str, *, user_id: int = 169699201, nickname: str = "雨弈") -> dict:
    """注意：私聊事件没有 group_id，这一条会被用来验证「不炸」。"""
    return {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "time": int(time.time()),
        "self_id": SELF_ID,
        "message_id": 54321,
        "user_id": user_id,
        "message": [_seg("text", text=text)],
        "raw_message": text,
        "sender": {"user_id": user_id, "nickname": nickname},
    }


def notice(notice_type: str, *, group_id: int = 123456, user_id: int = 88888,
           sub_type: Optional[str] = "approve", **extra: Any) -> dict:
    return {
        "post_type": "notice",
        "notice_type": notice_type,
        "sub_type": sub_type,
        "time": int(time.time()),
        "self_id": SELF_ID,
        "group_id": group_id,
        "user_id": user_id,
        **extra,
    }


def group_request(comment: str = "求进群", *, group_id: int = 123456,
                  user_id: int = 77777, flag: str = "flag-1") -> dict:
    return {
        "post_type": "request",
        "request_type": "group",
        "sub_type": "add",
        "time": int(time.time()),
        "self_id": SELF_ID,
        "group_id": group_id,
        "user_id": user_id,
        "comment": comment,
        "flag": flag,
    }


def meta_lifecycle(sub_type: str = "connect") -> dict:
    return {"post_type": "meta_event", "meta_event_type": "lifecycle",
            "sub_type": sub_type, "time": int(time.time()), "self_id": SELF_ID}


def meta_heartbeat(interval: int = 5000) -> dict:
    return {"post_type": "meta_event", "meta_event_type": "heartbeat",
            "time": int(time.time()), "self_id": SELF_ID, "interval": interval,
            "status": {"online": True, "good": True}}


# ------------------------------------------------------------------ 用例运行器
class CaseRunner:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, bool(ok), detail))
        print(("  [PASS] " if ok else "  [FAIL] ") + name
              + (f"  -> {detail}" if detail and not ok else ""))

    def finish(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print(f"\n==== 共 {len(self.results)} 项，失败 {len(failed)} 项 ====")
        for name in failed:
            print(f"  FAILED: {name}")
        return 1 if failed else 0


# ------------------------------------------------------------------ 自检
async def _self_test() -> int:
    """只验证 mock 自己是否符合 OneBot v11 的收发约定，不涉及被测代码"""
    import httpx
    from websockets.exceptions import InvalidStatus

    runner = CaseRunner()
    async with MockSnowLuma() as mock:
        try:
            async with websockets.connect(f"ws://127.0.0.1:{mock.ws_port}/?access_token=wrong"):
                runner.check("错误 token 被拒绝", False, "竟然连上了")
        except InvalidStatus as exc:
            runner.check("错误 token 被拒绝（401）", exc.response.status_code == 401, str(exc))

        uri = f"ws://127.0.0.1:{mock.ws_port}/?access_token={mock.ws_token}"
        async with websockets.connect(uri, max_size=None) as client:
            hello = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("连接后收到 lifecycle",
                         hello.get("meta_event_type") == "lifecycle", str(hello))

            await client.send(json.dumps({"action": "get_login_info", "params": {}, "echo": "e1"}))
            reply = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("动作应答带 echo 且 retcode=0",
                         reply.get("echo") == "e1" and reply.get("retcode") == 0
                         and reply["data"]["user_id"] == SELF_ID, str(reply))

            await client.send(json.dumps({"action": "fail_test", "params": {}, "echo": "e2"}))
            reply = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("业务失败信封 retcode!=0", reply.get("retcode") == 100, str(reply))

            await client.send(json.dumps({"action": "echo_less", "params": {}, "echo": "e3"}))
            reply = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("echo_less 不含 echo 字段", "echo" not in reply, str(reply))

            await client.send(json.dumps({"action": "no_reply", "params": {}, "echo": "e4"}))
            try:
                await asyncio.wait_for(client.recv(), 0.4)
                runner.check("no_reply 不回应答", False, "竟然回了")
            except asyncio.TimeoutError:
                runner.check("no_reply 不回应答（客户端超时）", True)

            await mock.push(group_message("ping"))
            pushed = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("能推送事件到客户端",
                         pushed.get("post_type") == "message"
                         and pushed["message"][0]["data"]["text"] == "ping", str(pushed))

        runner.check("动作被记录", bool(mock.actions_named("get_login_info")),
                     str(len(mock.actions)))

        async with httpx.AsyncClient(timeout=5) as http:
            ok = await http.post(f"http://127.0.0.1:{mock.http_port}/send_msg",
                                 json={"message_type": "group", "group_id": 1, "message": "hi"},
                                 headers={"Authorization": f"Bearer {mock.http_token}"})
            runner.check("HTTP 正确 token 返回信封",
                         ok.status_code == 200 and ok.json().get("retcode") == 0
                         and ok.json()["data"]["message_id"] == 1, ok.text)
            bad = await http.post(f"http://127.0.0.1:{mock.http_port}/send_msg", json={})
            runner.check("HTTP 缺少 token 返回 401", bad.status_code == 401, str(bad.status_code))
            runner.check("HTTP 请求体被记录为 params",
                         mock.http_actions[0]["params"]["group_id"] == 1,
                         json.dumps(mock.http_actions[:1], ensure_ascii=False))

    return runner.finish()


if __name__ == "__main__":
    print(f"自测结束，退出码为 {asyncio.run(_self_test())}")
```

跑一下：

```powershell
python tests\mock_snowluma.py
```

期望输出（本机实测）：

```
[mock] WS   ws://127.0.0.1:18081/?access_token=testtoken
[mock] HTTP http://127.0.0.1:18080/  POST /{动作名}  鉴权: Bearer httptoken
  [PASS]  错误 token 被拒绝(401)
  [PASS]  连接后收到 lifecycle
  [PASS]  动作应答带 echo 且 retcode=0
  [PASS]  业务失败信封 retcode!=0
  [PASS]  echo_less 不含 echo 字段
  [PASS]  no_reply 不回应答（客户端超时）
  [PASS]  能推送事件到客户端
  [PASS]  动作被记录
  [PASS]  HTTP 正确 token 返回信封
  [PASS]  HTTP 缺少 token 返回 401
  [PASS]  HTTP 请求体被记录为 params

==== 共 12 项，失败 0 项 ====
自测结束，退出码为 0
```

> 打印 token 只是为了排障方便（这里是写死的测试 token）。**别把这个习惯带进
> `connection.py`**：那里打印连接配置要脱敏（`已配置 / 未配置`），否则真实 access token
> 会进日志文件；`ws_token` / `http_token` 为空时也要打印成「不校验 token」，而不是留个空串。

### 5.1 接到你现在的 pytest 风格（按本仓库现状实测）

本仓库现状（实测）：

```
pytest 9.1.1；tests/test_segment.py 有测试函数（def test_segment()）；
pytest-asyncio 未安装；anyio 已安装且 its pytest 插件已注册（@pytest.mark.anyio 可用）。
```

**结论 1：mock 不要被 pytest 收集。** 文件名用 `tests/mock_snowluma.py`，
它不匹配 `test_*.py`，pytest 不会去收集它，但 `import` 得到；`_self_test()` 也保留，
`python tests/mock_snowluma.py` 依然能独立自检。

**结论 2：`@pytest.mark.anyio` 有陷阱——它会按「所有可用的异步后端」参数化。**
本机同时装了 `trio`，于是同一个 async 测试会跑两遍，`[trio]` 那一遍直接红：

```
..F
___________________________ test_anyio_style[trio] ___________________________
E  TypeError: trio.run received unrecognized yield message None.
   Are you trying to use a library written for some other framework like asyncio?
```

要用 `anyio` 就必须同时声明后端，把它钉死在 asyncio：

```python
# tests/conftest.py
import pytest

@pytest.fixture
def anyio_backend():
    return "asyncio"
```

**结论 3（推荐）：M3/M4 的用例干脆不用异步插件，用「同步测试 + 自己跑事件循环」**，
零插件依赖、和 `tests/test_segment.py` 的极简风格一致，也不会被 trio 参数化坑到
（`tests/test_connection.py` 现在就是这么写的）：

```python
# tests/test_connection.py   ← M4 写这个（本仓库已落地）
import asyncio

from mock_snowluma import CaseRunner, MockSnowLuma, group_message   # pytest 会把 tests/ 加进 sys.path

async def _case() -> int:
    runner = CaseRunner()
    async with MockSnowLuma() as mock:
        # 这里写 M4 的断言，例如：
        runner.check("占位断言", True)
    return runner.finish()

def test_connection_against_mock():
    # 断言失败时 finish() 返回 1 → 测试红；全过返回 0 → 测试绿
    assert asyncio.run(_case()) == 0
```

> 用 `python -m pytest` 运行（会把项目根加进 `sys.path`，与你现在
> `from snowluma.segment import ...` 的写法一致）。只敲 `pytest` 时，`snowluma`
> 可能 import 不到。

**结论 4：`pytest.ini` / `pyproject.toml` 里加两行，省掉重复参数**：

```ini
# pytest.ini
[pytest]
testpaths = tests
addopts = -q
```

`.gitignore` 建议补上 `.pytest_cache/` 与 `__pycache__/`（现在只有 `*.pyc`，
所以 `snowluma/__pycache__`、`tests/__pycache__` 仍会出现在 `git status` 里）。

**结论 5（本机踩到）**：`.pytest_cache` 目录当前**连读取都被拒**，
`git status` 会打 `warning: could not open directory '.pytest_cache/': Permission denied`，
`icacls` 也返回 `Access is denied`。这是 Windows 文件权限问题（不是 pytest 的问题）。
两种处理：在不会被沙箱限制的终端里删掉该目录让它重建；或者按需跑一次权限诊断脚本修复。

---

## 6. 手工冒烟（不写代码也能验证 mock）

### 6.1 WS 冒烟脚本

另开一个终端，用 15 行脚本手工连一次——这是排障时最常用的手段：

```python
# 临时文件 smoke_ws.py
import asyncio, json, websockets

async def main():
    uri = "ws://127.0.0.1:18081/?access_token=testtoken"
    async with websockets.connect(uri) as ws:
        print("首帧:", await asyncio.wait_for(ws.recv(), 2))
        await ws.send(json.dumps({"action": "get_login_info", "params": {}, "echo": "1"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
            if msg.get("echo") == "1":
                print("应答:", msg)
                break

asyncio.run(main())
```

### 6.2 验证「客户端超时」这条路

```python
mock.slow_actions["get_status"] = 2.0     # 让 get_status 慢 2 秒
# 客户端侧把 timeout 设成 0.5，应当抛超时而不是拿到数据
```

### 6.3 验证「事件推送」

```python
await mock.push(notice("group_increase", group_id=123456, user_id=88888))
await mock.push(group_request("求进群"))
await mock.push(meta_heartbeat())
```

---

## 7. 常见坑（都是本机真踩过的）

| # | 坑 | 现象 | 解法 |
| --- | --- | --- | --- |
| 1 | websockets 版本 API 变化 | `TypeError: handler() takes 1 positional argument but 2 were given` | `websockets>=14` 的 handler **只有一个参数**；旧写法 `(ws, path)` 是 legacy API |
| 2 | Header 参数名 | `TypeError: connect() got an unexpected keyword argument 'extra_headers'` | 新 API 用 `additional_headers`（旧名 `extra_headers`） |
| 3 | 端口被系统保留 | `PermissionError: [Errno 13] ... WinError 10013` | 换端口；`netsh interface ipv4 show excludedportrange protocol=tcp` 查看保留段 |
| 4 | 端口撞真实 SnowLuma | 连上了但行为怪（收到的是真事件） | mock 用 `18080+`，别用 `3000/3001` |
| 5 | `ThreadingHTTPServer` 不退 | 用例跑完进程挂着 | `daemon_threads = True` + `shutdown()` + `server_close()` |
| 6 | HTTP/1.1 挂起 | 客户端等响应直到超时 | `Content-Length` 必须准确；读了 body 长度要和声明一致 |
| 7 | 线程里碰 asyncio | `RuntimeError: no running event loop` | HTTP 线程只写普通 list；需要推事件就交给 asyncio 侧 |
| 8 | 推事件时没客户端 | `push()` 返回 0，用例却以为发了 | 先 `await wait_until(lambda: bool(mock.clients))` 再 push |
| 9 | 断言没超时 | 失败时挂 30 秒+，看不出哪一步卡住 | 用例里自备 `wait_until(pred, timeout=...)`，所有 `recv()` 包 `wait_for` |
| 10 | 忘了记录就抛异常 | 断言拿不到请求，失败原因含糊 | 进读循环**先 `self.actions.append(request)`**，再做分派/回包 |
| 11 | `echo` 用真值判断 | `echo=0` / `echo=""` 时回包丢 echo，客户端永远超时 | 用 `is not None` 判断 |
| 12 | mock 里 import 了被测代码 | 协议理解错误被双方同时犯，测试假绿 | mock 保持零业务依赖 |
| 13 | 文件名被 pytest 收集 | `tests/mock_snowluma.py` 若命名成 `test_mock.py`，pytest 会去收集它并尝试跑 `_self_test` | 用 `mock_*.py` 命名，或放到非 `testpaths` 目录 |
| 14 | `@pytest.mark.anyio` 跑两遍 | `[trio]` 那一遍必然失败（本机装了 trio） | 在 `conftest.py` 里提供 `anyio_backend` fixture 返回 `"asyncio"`，或改用「同步测试 + `asyncio.run`」 |
| 15 | `.pytest_cache` 读不了 | `git status` 打 Permission denied 警告 | 该目录属权限问题，删除重建或做一次权限诊断 |

---

## 8. mock 必须能驱动的那 39 项断言

M4 起写用例时，逐条对着设计文档 [§11.1](snowluma-protocol-design.md) 的 A~E 组来。
映射关系（你写用例时会频繁查这张表）：

| 断言组 | 依赖 mock 的什么能力 |
| --- | --- |
| A 正向 WS + 动作（12 项） | `_check_ws_token`、`auto_lifecycle`、`reply_to` 分派、`no_reply`/`echo_less`/`fail_test`、`slow_actions`、`actions_named()` |
| B 事件分发（11 项） | `group_message(message_format=...)`、`private_message()`、`notice()`、`group_request()`、`push()`、`actions_named("send_msg")` |
| C 反向 WS（6 项） | 还需给 mock 加「WS 客户端模式」（见下）+ 一个**错误 token 的反向服务端**用来验证 401 |
| D HTTP 兜底（5 项） | HTTP 服务端、`http_actions`（含 `auth`/`path`/`params`） |
| E 配置发现（5 项） | 与 mock 无关：用临时目录造一份 `config/onebot.json` |

另外好用的断言写法（M4 会用）：

```python
params = mock.last_action("send_msg")["params"]
runner.check("send_msg 走 group 且带 group_id",
             params["message_type"] == "group" and params["group_id"] == 123456, str(params))
runner.check("array 事件下 message 是段数组",
             isinstance(params["message"], list) and params["message"][0]["type"] == "at", str(params))
```

---

## 9. M4/M5 需要给 mock 加的扩展（现在不用写，先知道）

| 扩展 | 用途 | 实现提示 |
| --- | --- | --- |
| **反向 WS 客户端模式** | M5 测反向通道 | 见下方代码；关键是先做「读循环复用」重构 |
| 脚本化应答 | 一次性动作应答 | 已有的 `mock.handlers[action] = lambda req: envelope(req, data=...)` |
| 断连注入 | 验证「连接断开后在途请求立即失败」 | `await mock.clients[0].close()`，或加 `mock.drop_clients()` |
| 多账号 | 多连接互不干扰 | 直接连两次即可，`clients` 本来就是列表；如需不同 `self_id`，扩展 `reply_to` 从连接上下文取 |
| 延迟/抖动 | 超时边界 | 已有的 `slow_actions`；可再加 `mock.jitter = 0.05` |
| 事件录制/回放 | 复现线上问题 | 把收到的 `post_type` 报文 append 到 jsonl，用例里 `for ev in replay(path): await mock.push(ev)` |

### 9.1 反向模式：为什么 mock 不需要 `reverse_token` 参数

M5 里角色是**反过来**的：

| | 正向（M4） | 反向（M5） |
| --- | --- | --- |
| 谁 listen | mock | 你的 `OneBotConnection`（`reverse.port`） |
| 谁出示 token | 被测代码（连 mock） | **mock**（连你的服务端） |
| 谁校验 token | mock（`_check_ws_token`） | **你的服务端**（`_process_reverse_request`） |

所以 mock 在反向模式下**不校验任何 token**，它只需要「把 token 带上去」；
token 用**方法参数**传（默认值给一个常量即可），比塞进 `__init__` 更灵活——
「错 token 被 401」这条断言就是同一个方法传个错值：

```python
# mock_snowluma.py 的反向模式扩展（M5 再加，M3 不用写）
REVERSE_PORT = 18082          # 只作为用例构造 url 的默认值
REVERSE_TOKEN = "revtoken"

# ① 先把 _ws_handler 的循环体抽成 _pump，让正向/反向共用同一套「推 lifecycle + 记录动作 + 应答」
async def _pump(self, connection) -> None:
    self.clients.append(connection)
    try:
        if self.auto_lifecycle:
            await connection.send(json.dumps(meta_lifecycle("connect"), ensure_ascii=False))
        async for raw in connection:
            request = json.loads(raw)
            self.actions.append(request)
            ...
    except ConnectionClosed:
        pass
    finally:
        if connection in self.clients:
            self.clients.remove(connection)

async def _ws_handler(self, connection) -> None:      # 正向：mock 是被连的一方
    await self._pump(connection)

# ② 反向：mock 主动连被测服务端
async def connect_reverse(self, url: str, token: str = REVERSE_TOKEN) -> None:
    uri = f"{url}?access_token={token}" if token else url
    headers = {"Authorization": f"Bearer {token}"} if token else None
    connection = await websockets.connect(uri, additional_headers=headers, max_size=None)
    self._tasks.add(asyncio.create_task(self._pump(connection)))

def drop_clients(self) -> None:                        # 断连注入
    for connection in list(self.clients):
        asyncio.create_task(connection.close())
```

> 需要在 `__init__` 里补一个 `self._tasks: set = set()`（保存反向连接的后台任务，
> 供 `stop()` 时取消），别让 `connect_reverse` 的读循环变成无人回收的孤儿任务。
> `push()` 不用改：`_pump` 把两种连接都放进同一个 `self.clients`，广播自然对正/反向都生效。


---

## 10. 完成 M3 的标志 & 下一步

**完成标志**：

1. `python tests/mock_snowluma.py` → `共 12 项，失败 0 项`（末行 `自测结束，退出码为 0`）；
   注意 `__main__` 只 `print` 不 `SystemExit`，进程退出码恒为 0；
2. 故意把 `no_reply` 改成会回应答 → 自检里那一项 FAIL（**证明断言真的有效**）；
3. 你已顺手备份过 `DataForXPlugin/`。

**下一步（M4）**：写 `snowluma/connection.py` 的正向 WS + 动作调用，然后新建
`tests/test_connection.py`，用本 mock 驱动 A 组 12 项断言。届时 mock 只需要补一个
能力：让「慢应答/断连」可控——`slow_actions` 已经有了，断连用 `clients[i].close()` 即可。

> 记得：M4 的两条铁律（**读循环内绝不 `await call_action`**、**WS 超时后绝不再走 HTTP**）
> 都要靠 mock 的 `no_reply` / `slow_actions` 来验证——这正是 M3 先把故障注入做进 mock 的原因。
