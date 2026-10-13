# M7 教程：发送层（`api/bot.py` + 连接 holder 收尾 + 导出）

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。
>
> 配套：[设计文档](snowluma-protocol-design.md) §8「发送与动作层设计」、
> [M6 教程](m6-event-layer-tutorial.md) §11「与 M7/M8 的交接清单」、
> [ADR-0001](adr/0001-message-representation.md)（`bot.send` 是"字符串 = CQ 码"的入口）。
> 阅读方式：§0 先看你现在的红状态 → §2 四条约束 → §3–§8 任务 → §9 验收 → §10 排查表。
>
> ⚠️ **核对现状（重要）**：本文 §3~§8 的任务**全部已落地**，`api/bot.py` 现在是 133 行。
> §0 与各任务的"现状/红状态"描述的是 **M7 动工前**的那一版 `api/bot.py`（71 行的空壳版），
> 留着是为了讲清每条修法的理由。核对时请以现行的 `Bot.send` / `Bot.send_group` /
> `Bot.reply` / `Bot.finish` / `Bot.call_api` / `Bot.input_value` 为准。

---

## TL;DR 动手顺序

| # | 任务 | 产出 | 时长 |
| --- | --- | --- | --- |
| A | 连接 holder 收尾（三个空壳）→ **已完成** | `api/utils.py` 的 `set_connection` / `get_connection` / `require_connection` | 10 min |
| B | `Bot` 骨架 + `send()` → **已完成** | `api/bot.py` 的 `Bot.send` | 50 min |
| C | `send_group` / `send_user` / `send_private` / `reply` → **已完成** | `api/bot.py` 的 `Bot.reply` 等 | 30 min |
| D | `finish` + `call_api`（`call_action` 别名）+ 便捷动作 → **已完成** | `api/bot.py` 的 `Bot.finish` / `Bot.call_api` | 40 min |
| E | `input_value`（等待任务）→ **已完成** | `api/bot.py` 的 `Bot.input_value` | 20 min |
| F | 收尾：`api/__init__.py` 导出 + 离线假连接 → **已完成** | `api/__init__.py`、`snowluma/connection.py` 的 `LocalEchoConnection` | 30 min |
| — | 验收：`tests/test_bot.py` + 回归 | `tests/` | 40 min |

**验收门禁**：`pytest tests/ -q` 全绿（≥14 条 + 新增 ~14 条）+ 5 个现有插件一行不改仍可用
+ `tests/test_connection.py` 不退化 + 真机只读 9 项仍过（§9）。

---

## 0. 先看清一件事：M7 动工前那版 `api/bot.py` 会**静默失败**

> **现状**：下面三条**都已经修好了**。现行 `api/bot.py` 是 133 行，
> `Bot.send` 已经委托给 `connection.send_message()`（见 [api/bot.py](../api/bot.py)）。
> 这一节保留作"为什么当初发不出消息"的复盘。

M7 动工前你已经写了一版（[api/bot.py](../api/bot.py) 71 行），但它**发不出任何消息，而且原因被吞掉了**。
三个原因叠在一起：

1. **`get_connection()` 恒返回 `None`** —— M6 当时只留了空壳
   （`def set_connection(connection) -> None: ...` 什么都不做），所以 `send()` 里拿到的 `conn` 是 `None`，
   下一行 `conn.call_action(...)` 直接 `AttributeError`。
2. **`self._outgoing_format()` 在 `Bot` 上不存在** —— 它是
   [`OneBotConnection._outgoing_format`](../snowluma/connection.py) 的**私有**方法，
   `Bot.send` 里调它会 `AttributeError`。
3. **`except Exception` 把上面两个"编程错误"一起吞了** —— 只留下"账号可能被风控"这种误导性日志，
   真正的 `AttributeError` 藏在 `logger.exception` 里，很容易看漏。

### 0.1 M7 动工前那版的 10 个问题清单（**均已修复**）

| # | 旧位置 | 问题 | 正确做法（现行代码） |
| --- | --- | --- | --- |
| 1 | 旧 `bot.py` | `"message_type": mode if mode == "group" else "user"` —— OneBot 只认 `private`，`user` 是非法值 | ✅ 非 group 一律映射成 `"private"` |
| 2 | 旧 `bot.py` | `self._outgoing_format()` 不存在（且格式转换本就该由连接层做） | ✅ 委托 `connection.send_message()` |
| 3 | 旧 `bot.py` | 自己拼 `params` 调 `call_action`，绕过了连接层的 4 件事（§4.3） | ✅ 同上 |
| 4 | 旧 `bot.py` | `except Exception` 吞掉编程错误，故障现场失真 | ✅ 只吞**预期的通信异常**，其余 `logger.exception` 后返回 None（§2.1） |
| 5 | 旧 `bot.py` | `send_user` 调 `self.send(user_id, message)`，`mode` 默认 `"group"` → **私聊发成群聊** | ✅ `mode="private"` |
| 6 | 旧 `bot.py` | `reply` 往 `event.get_user_id` 发 → 群里变成给那个人发私聊；且**没加 `[CQ:reply,id=...]` 前缀** | ✅ 群里发群、私聊发人；用 `event.reply()` 拼前缀（§5.2） |
| 7 | 旧 `bot.py` | `finish` 参数顺序错（`self.send(uid, "group", message)` → message="group"），且缺 `finally` | ✅ `try: await self.send(uid, message, mode) finally: raise FinishException` |
| 8 | 旧 `bot.py` | `call_action` **没有 `return`** → 插件永远拿不到 `data`（`get_group_info` 之类全废） | ✅ `return await ...call_action(...)` |
| 9 | 旧 `bot.py` | `input_value` 用 `self.func.child_func`（可能是 `None`）且丢了 `type_`；`self.func` 也可能没设 | ✅ §7.2 |
| 10 | `api/utils.py` 的 holder | 三个函数是空壳；`require_connection()` 不 raise；`get_connection()` 的返回标注漏了 `| None` | ✅ §3，已实现 |

> 这 10 条里有 6 条是"参数/命名/契约"层面的，修起来是 1–2 行；真正需要想清楚的是
> **失败语义**（§2.1）与 **reply 的会话选择**（§5.2）。

---

## 1. 本阶段目标与边界

### 1.1 目标

让插件里这一行**真正生效、且失败时不炸插件**：

```python
await bot.send(event.get_group_id, f"{At(event.get_user_id)} 你好")
```

### 1.2 改哪些文件

| 文件 | 动作 |
| --- | --- |
| `api/utils.py` | **只补末尾 3 个函数**（`set_connection` / `get_connection` / `require_connection`）；其余 M6 已定稿，不动 —— **已完成** |
| `api/bot.py` | 按 §3–§7 重写 `Bot`（可整文件重写，旧版 71 行 → 现行 133 行）—— **已完成** |
| `api/__init__.py` | 补导出（§8.1） |
| `snowluma/connection.py` | 可选：加离线假连接 `LocalEchoConnection`（§8.2，M8 的 `debug.py` 要用） |

### 1.3 不要碰

- `main.py`、`debug.py` —— M8 才改（现在它们还是旧版，能 import 就行）。
- `api/event.py` —— M6 已定稿（`get_message_id` / `reply()` / 三个视图都在）。
- `snowluma/connection.py` 的动作实现 —— M4/M5 已定稿，M7 只**调用**它。
- **5 个现有插件** —— M7 的验收标准之一就是它们一行不用改。

### 1.4 依赖方向（别搞反）

```
api/bot.py  ──调用──▶  snowluma.connection.OneBotConnection   （发消息/调动作）
api/bot.py  ──调用──▶  api/utils.py 的 holder                 （拿"当前连接"）
api/bot.py  ──调用──▶  api/utils.py 的 CreateOnWaitingTask    （等待任务）
api/bot.py  ──引用──▶  api/event.py 的 MessageEvent           （只做类型标注，运行时不需要）
```

`snowluma/**` **绝不** import `api/**`（否则循环）。`api/bot.py` 里对 `MessageEvent` 的引用
必须放在 `TYPE_CHECKING` 下（现行 `api/bot.py` 顶部已经这么做了，保持）。

---

## 2. 动手前必须想清楚的 4 个约束

### 2.1 失败的语义：`send` 吞、`call_api` 抛

这是整个 M7 唯一需要"设计"的地方。两种 API 的调用者预期不同：

| API | 无连接 | 动作失败（`retcode != 0`） | 超时 | 参数非法 |
| --- | --- | --- | --- | --- |
| `bot.send(...)` | 记 warning，返回 `None` | 记 warning，返回 `None` | 记 warning，返回 `None` | 记 warning，返回 `None` |
| `bot.call_api(...)` | **抛 `ConnectionUnavailable`** | **抛 `ActionFailed`** | **抛 `ConnectionUnavailable`** | **抛 `ValueError`** |

理由：

- `send` 是插件最常用的"顺手发一句"，一个群被风控不该让整个处理器崩（旧行为也是吞）。
- `call_api` 是插件**主动要数据**（`get_group_info` 拿群名），拿不到就必须让插件知道，
  否则插件会拿着 `None` 继续跑出更难查的错。

```python
# send：只吞"预期的通信异常"，编程错误要暴露
try:
    data = await connection.send_message(...)
except (ActionFailed, ConnectionUnavailable, ValueError) as exc:
    logger.opt(colors=True).warning(f'发送到{where} {uid} 失败: {exc}')
    return None
except Exception as exc:            # 兜底：真实的 bug 要留全栈
    logger.exception(exc)
    return None
```

> ⚠️ 注意 `except (ActionFailed, ConnectionUnavailable)` 必须写在 `except Exception` **前面**，
> 否则永远进不去（宽异常在后）。

### 2.2 `bot.send` 是"字符串 = CQ 码"的入口（ADR-0001 D5）

`send()` 收到的字符串**一律按 CQ 码解析**（M1 的 `message_to_payload` 就是这么做的）。
所以：

- 插件自己写的 CQ 码（`At()` / `ImageSegment()` 的返回值）→ 直接用 ✅
- **用户内容**要插进去 → 必须先 `Text()` 转义，或整条 `auto_escape=True`，或改传段对象 ✅
- `event.get_plain_text` **未转义**，直接回发会被当代码执行 ❌

这条不是 M7 发明的，是 ADR-0001 的决定；M7 的职责是**把 `auto_escape` 原样透传到协议端**，
并且**不要**在框架内部偷偷二次转义或反转义。

### 2.3 连接解析顺序：实例注入 > 全局 holder

```python
def _connection(self):                    # 名字随便，别和属性同名
    return self.connection or get_connection()
```

- `Bot(connection=conn)`：给测试/多账号用（不用碰全局状态）。
- `Bot()`：走 `set_connection()` 登记的全局连接（M8 的 `main.py` 会登记一次）。
- 明确要"必须能拿到连接"的地方（`call_api`）用 `require_connection()`，它在没有连接时 raise。

**测试里的全局污染要小心**：`set_connection()` 改的是模块级变量，用例结束必须还原
（§9.1 的 `finally`）。

### 2.4 `FinishException` 是 `BaseException`

```python
class FinishException(BaseException):     # api/exception.py
```

含义有两层：

1. `except Exception` **抓不到**它 → 插件里 `bot.finish()` 的提前终止语义不会被谁误吞。
2. `finish()` 必须用 `try/finally` 保证"先发消息，再无论如何都抛"：

```python
async def finish(self, uid, message, mode="group", **kwargs):
    try:
        await self.send(uid, message, mode, **kwargs)
    finally:
        raise FinishException
```

写在 `send()` 之后而非 `finally` 里，效果一样；但**不能**写成"send 抛异常就不抛 FinishException"，
否则插件的提前终止会失效。

### 2.5 空消息由 `bot.send` 负责

你 M1 已经把这个决定写进注释了（[segment.py:237](../snowluma/segment.py#L237)）：
`message_to_payload("") == []`，且注释写着"空消息不兜底（交给 bot.send 打 warning 决定跳不跳）"。

所以 M7 里：

```python
if not normalize_cq(message):           # "" / [] / 全空 text 段
    logger.warning(f"消息为空，跳过发送（目标 {uid}）")
    return None
```

好处：SnowLuma 对空消息会回 `retcode != 0`，跳过能少一条误导性的"发送失败：账号可能被风控"。

---

## 3. 任务 A：连接 holder 收尾（**已完成**，见 `api/utils.py` 的 `set_connection` / `get_connection` / `require_connection`）

**这是 M7 第 0 步**，否则后面每条断言都过不了。

动工前的现状（三个空壳）：

```python
_connection: "OneBotConnection | None" = None
def set_connection(connection) -> None: ...        # ← 什么都没做
def get_connection() -> "OneBotConnection": return _connection   # ← 标注漏了 | None
def require_connection(): return _connection                     # ← 不 raise
```

现行实现（目标形态）：

```python
_connection: "OneBotConnection | None" = None


def set_connection(connection: "OneBotConnection | None") -> None:
    """登记当前连接（main.py 启动时 / debug.py 用假连接 / 测试用例注入）"""
    global _connection
    _connection = connection


def get_connection() -> "OneBotConnection | None":
    """当前连接，可能为 None（离线调试、还没连上、刚断开）"""
    return _connection


def require_connection() -> "OneBotConnection":
    """拿连接，没有就抛——给"必须能调用动作"的路径用"""
    if _connection is None:
        raise ConnectionUnavailable("当前没有可用的 SnowLuma 连接")
    return _connection
```

**为什么放 `api/utils.py` 而不是 `api/bot.py`**：`bot.py` 已经 import `utils`，
holder 放 utils 就不会有 `bot ↔ utils` 循环；M6 教程 §2.3 也是这么定的。

**自测点**

```python
# 绿：现行实现下这三条都能过
set_connection(object())
assert get_connection() is not None
set_connection(None)
try:
    require_connection(); assert False, "应该抛"
except ConnectionUnavailable:
    pass
```

---

## 4. 任务 B：`Bot` 骨架 + `send()`

### 4.1 骨架

```python
class Bot:
    func: WaitingFuncMeta | None = None       # 当前触发的响应器（M8 分发时设置；等待任务要用）

    def __init__(self, connection: "OneBotConnection | None" = None) -> None:
        self.connection = connection          # 显式注入（测试 / 多账号）；None 时回落到全局 holder
        self.func = None                      # 实例属性，别用类属性（否则并发事件会互相串）

    def _connection(self) -> "OneBotConnection | None":
        return self.connection or get_connection()

    @property
    def self_id(self) -> int | None:
        return getattr(self._connection(), "self_id", None)

    @property
    def is_connected(self) -> bool:
        return bool(getattr(self._connection(), "connected", False))
```

> `func` 必须**实例级**：`Bot` 是每个事件 new 一个（M8 就这么用），但如果你写成
> `Bot.func = ...` 的类属性赋值，多个并发事件会互相覆盖，等待任务就会挂到别人身上。

### 4.2 `send()` 完整实现

```python
from typing import Any, Dict, NoReturn, Optional, Union

from snowluma.exception import ActionFailed, ConnectionUnavailable
from snowluma.segment import MessageLike, normalize_cq

    async def send(
        self,
        uid: Union[int, str],
        message: MessageLike,
        mode: str = "group",
        *,
        auto_escape: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """发消息：`mode` 不是 "group" 就按私聊处理（兼容旧的 "user"/"private" 传法）。

        返回 `send_msg` 应答里的 `data`（含 message_id）；任何失败都只记日志并返回 None。
        """
        connection = self._connection()
        message_type = "group" if str(mode).lower() == "group" else "private"
        where = "群" if message_type == "group" else "好友"

        if connection is None:
            logger.warning(f'发送消息到{where} {uid} 失败：尚未建立 SnowLuma 连接')
            return None
        if not normalize_cq(message):
            logger.warning(f"消息为空，跳过发送（目标 {uid}）")
            return None

        try:
            data = await connection.send_message(
                message,
                message_type=message_type,
                group_id=uid if message_type == "group" else None,
                user_id=None if message_type == "group" else uid,
                auto_escape=auto_escape,
            )
        except (ActionFailed, ConnectionUnavailable, ValueError) as exc:
            logger.opt(colors=True).warning(f'发送消息到{where} {uid} 失败: {exc}')
            return None
        except Exception as exc:              # 兜底：编程错误要留全栈，不要伪装成"风控"
            logger.exception(exc)
            return None

        logger.opt(colors=True).success(f'发送消息到{where} <y>{uid}</y> 成功')
        return data
```

### 4.3 为什么必须委托给 `connection.send_message()`（而不是自己拼 params）

动工前的实现自己拼了 params，于是漏掉了连接层已经做好的 4 件事
（见 [snowluma/connection.py](../snowluma/connection.py) 的 `OneBotConnection.send_message`）：

| 连接层已经做的 | 你现在自己拼会怎样 |
| --- | --- |
| 按 `_outgoing_format()`（配置 > 对端探测 > array）转 `message` | 直接 `AttributeError`（§0 问题 2） |
| `_coerce_id(group_id/user_id)` 把 str 转 int | 字符串 id 传下去，协议端可能不认 |
| `message_type` 缺省时按 `group_id/user_id` 自动路由 + 缺 id 抛 `ValueError` | 非法参数要自己造 |
| 把 `auto_escape` 同时写进 params 与载荷转换 | 容易只写一处 |

**一句话**：`Bot.send` 只做"语义映射 + 日志 + 异常语义"，协议细节全部交给连接层。

### 4.4 三个高频细节

1. **`mode` 的兼容**：旧代码的约定是"不是 `group` 就是私聊"，插件里出现过 `"private"`、
   `"user"` 等写法。所以判据用 `str(mode).lower() == "group"`，其余一律 private。
   （**不要**把 `mode` 直接当 `message_type` 传给协议端 —— 这是问题 1 的根因。）
2. **uid 不做手工转换**：`connection.send_message` 里 `_coerce_id` 会处理 `str/int`；
   `Bot` 里再转一次反而会在 `"123456"` 之外的场景出错。
3. **成功日志要分清群/好友**：你现在的日志两种情况都写"到群"，排障时会误判。

### 4.5 自测点

```python
# 绿（现行实现）：mock 能收到 send_msg
await bot.send(123456, "hi")
assert mock.last_action("send_msg") is not None
assert mock.last_action("send_msg")["params"]["message_type"] == "group"
```

---

## 5. 任务 C：`send_group` / `send_user` / `send_private` / `reply`

### 5.1 三个别名（把"哪个 id 是哪个"写进函数名）

```python
    async def send_group(self, group_id, message, **kwargs):
        return await self.send(group_id, message, "group", **kwargs)

    async def send_user(self, user_id, message, **kwargs):
        """旧名，插件里可能已经在用——保留，行为等于私聊"""
        return await self.send(user_id, message, "private", **kwargs)

    async def send_private(self, user_id, message, **kwargs):
        """新名（与 OneBot 的 message_type=private 对齐）"""
        return await self.send(user_id, message, "private", **kwargs)
```

⚠️ 动工前的 `send_user` 少了 `"private"`（问题 5），**这是最容易被忽略的静默错误**：
私聊的目标 QQ 号被当成群号发出去，SnowLuma 会返回 `retcode != 0`，而日志只说"可能被风控"。

### 5.2 `reply`：两个必须想清楚的点

```python
    async def reply(self, event: "MessageEvent", message, **kwargs):
        """引用回复：群里回群、私聊回人，并带上 [CQ:reply,id=...] 前缀"""
        content = normalize_cq(message)
        if event.get_message_id is not None:
            content = event.reply(content)        # MessageEvent.reply 生成前缀（M6 已提供）
        if event.is_group and event.get_group_id is not None:
            return await self.send(event.get_group_id, content, "group", **kwargs)
        return await self.send(event.get_user_id, content, "private", **kwargs)
```

1. **会话选择**：群里必须发到 `group_id`（动工前的实现发到 `user_id` → 变成给人发私聊，
   问题 6）。判据用 `event.is_group and event.get_group_id is not None`，
   这样"临时会话私聊"（`message_type=private` 但带 `group_id`）也会正确地走私聊。
2. **没有 `message_id` 时不加前缀**：自己造的 payload、或某些通知转换来的事件没有
   `message_id`，此时 `[CQ:reply,id=None]` 会让协议端报错。加一层判断即可。

### 5.3 自测点

```python
# C1 私聊别名不能再发成群
await bot.send_user(169699201, "hi")
assert mock.last_action("send_msg")["params"]["message_type"] == "private"

# C2 群里 reply 发到群，且带 reply 前缀
ev = GroupMessageEvent(999, group_message("hi"))
await bot.reply(ev, "收到")
p = mock.last_action("send_msg")["params"]
assert p["group_id"] == 123456 and "CQ:reply" in json.dumps(p["message"], ensure_ascii=False)
```

---

## 6. 任务 D：`finish` + `call_api` + 便捷动作

### 6.1 `finish`

```python
    async def finish(self, uid, message, mode: str = "group", **kwargs) -> NoReturn:
        """发完消息就终止当前插件函数（抛 FinishException）"""
        try:
            await self.send(uid, message, mode, **kwargs)
        finally:
            raise FinishException
```

- 参数顺序跟 `send` 一致（`uid, message, mode`）—— 动工前写成了 `send(uid, "group", message)`，
  等于把字符串 `"group"` 当消息发出去了（问题 7）。
- `finally` 保证"即使发送失败也终止函数"（插件里 `await bot.finish(...)` 后面不写 `return` 也安全）。

### 6.2 `call_api`（旧名）+ `call_action`（你现在的名字）

```python
    async def call_api(self, action: str, *, transport=None, timeout=None, **kwargs) -> Any:
        """调任意 OneBot 动作，返回应答信封里的 data。

        与 send 相反：拿不到数据就抛（插件主动要数据，静默返回 None 会更难查）。
        """
        return await require_connection().call_action(
            action, transport=transport, timeout=timeout, **kwargs
        )

    call_action = call_api        # 别名：你现在写的名字，保留以免教程/代码漂移
```

- **必须 `return`**（问题 8）：否则 `data = await bot.call_api("get_group_info", ...)` 拿到 `None`。
- 用 `require_connection()`：没有连接时 `ConnectionUnavailable`，比 `AttributeError: NoneType` 清楚。
- 想用实例注入的连接就换成 `(self.connection or require_connection())`。

### 6.3 便捷动作（只包高频的，别包 115 个）

SnowLuma 有 115+ 个动作，靠 `call_api` 兜底即可。建议只包这几个：

| 方法 | 对应动作 |
| --- | --- |
| `get_login_info()` / `get_status()` | 信息类 |
| `get_group_list()` / `get_friend_list()` | 列表类 |
| `get_group_member_info(group_id, user_id, no_cache=False)` | 查成员（插件常用） |
| `delete_msg(message_id)` | 撤回（配合 `event.get_message_id`） |

实现一律 `return await self.call_api("xxx", **kwargs) or {}`（列表类 `or []`），
**不要**在便捷方法里再写一遍异常处理 —— 语义已经由 `call_api` 定死。

---

## 7. 任务 E：`input_value`（等待任务）

### 7.1 动工前的三个问题

M7 动工前 `Bot.input_value` 长这样：

```python
async def input_value(self, user_id: int=None, group_id: int=None):
    logger.info("A OnWaiting Task has been successfully created.")
    CreateOnWaitingTask(self.func.child_func, user_id, group_id)   # ← 三个坑
```

1. `self.func` 可能没设（不是由响应器触发时）→ `AttributeError`；
2. `self.func.child_func` 可能为 `None`（`on_waiting` 没配子函数）→
   `WaitingFuncMeta(None)` 后面 `.name` 会炸；
3. 丢了 `type_`（响应方式），而 `CreateOnWaitingTask` 的第 4 个参数就是它（见 §7.3）。

### 7.2 现行实现（三个坑都已修）

```python
    async def input_value(self, user_id=None, group_id=None, type_=None) -> None:
        """注册等待任务：同一会话里这个人的下一条消息会触发等待事件的子函数"""
        if self.func is None:
            logger.warning("Bot.func 未设置，无法创建等待任务")
            return
        callback = getattr(self.func, "child_func", None) or getattr(self.func, "_func", None)
        if callback is None:
            logger.warning("当前等待事件没有子函数，等待任务不会被创建")
            return
        CreateOnWaitingTask(callback, user_id, group_id, type_)
        logger.info("A OnWaiting Task has been successfully created.")
```

### 7.3 ⚠️ `CreateOnWaitingTask` 的 `response_method` 坑（**已修**）

动工前的写法：

```python
def CreateOnWaitingTask(func, user_id, group_id, type_=None):
    get_waiting_task_pool().add_task(WaitingTask(WaitingFuncMeta(func), user_id, group_id, type_))
```

而 [`WaitingTask.__init__`](../pool/pool.py) 的签名是
`(func, user_id=None, group_id=None, response_method=None)`，**第 4 个位置参数是 `response_method`**。
所以 `type_=None` 时会把默认值覆盖成 `None`，M8 里那句 `if "input" in task.response_method`
就会 `TypeError: argument of type 'NoneType' is not iterable`。

现行实现两处都做了（见 `api/utils.py` 的 `CreateOnWaitingTask` 与 `pool/pool.py` 的
`WaitingTask.__init__`）：

```python
# api/utils.py：只有显式传入时才覆盖默认响应方式；另外把 WaitingFuncMeta 的重复包裹挡掉
def CreateOnWaitingTask(func, user_id, group_id, type_=None):
    meta = func if isinstance(func, WaitingFuncMeta) else WaitingFuncMeta(func)
    if user_id is None and group_id is None:
        logger.warning("创建等待任务时既没给 user_id 也没给 group_id，这个任务永远不会被触发")
    task = WaitingTask(meta, user_id, group_id,
                       type_ if type_ is not None else ["input"])
    get_waiting_task_pool().add_task(task)
```

```python
# pool/pool.py：WaitingTask 自己也不再吃可变默认值 ["input"]
self.response_method = ["input"] if response_method is None else response_method
```

```python
# main.py：读之前先兜一下（现行 message_preprocessor 就是这么写的）
if task.response_method and "input" in task.response_method:
```

### 7.4 自测点（注意清理全局池）

```python
from api import get_waiting_task_pool
from plugins.manager import FuncMeta

pool = get_waiting_task_pool()
bot = Bot()
try:
    bot.func = FuncMeta(lambda bot, event: None, "on_waiting")
    await bot.input_value(group_id=123456, user_id=169699201)
    tasks = list(pool)
    assert len(tasks) == 1
    assert tasks[0].group_id == 123456 and tasks[0].user_id == 169699201
    assert "input" in tasks[0].response_method        # ← §7.3 的坑，这里就能测出来
finally:
    pool.pop_tasks(list(pool))                        # ⚠️ 等待池是全局的，必须清
```

---

## 8. 任务 F（收尾）：导出 + 离线假连接

### 8.1 `api/__init__.py` 要补的导出（**已完成**）

M6 的 F 任务还剩一半没做（`api/__init__.py` 里还没有这些），M7 一起收掉。
**注意 `set_connection` / `get_connection` 定义在 `api/utils.py`，要从 `.utils` 导出**：

```python
from .utils import set_connection as set_connection      # ← 不是 from .bot
from .utils import get_connection as get_connection
from .utils import require_connection as require_connection
from .event import RequestEvent as RequestEvent
from .event import SenderInfo as SenderInfo
from .on import on_request as on_request
from .on import get_request_func_pool as get_request_func_pool
from .utils import AtAll as AtAll
from .utils import Text as Text
from .utils import Reply as Reply
from .utils import Message as Message
from .utils import FaceSegment as FaceSegment
from .utils import FileSegment as FileSegment
from .utils import VideoSegment as VideoSegment
from .utils import RecordSegment as RecordSegment
from snowluma.segment import MessageSegment as MessageSegment      # 段数组路径也是官方 API
```

> ⚠️ **不要写成 `from .bot import set_connection`**：holder 的实现和唯一的 `_connection`
> 全局量都在 `api/utils.py`，`bot.py` 里只是 import 了它、并没有 re-export。
> 从 `.bot` 导入会 `ImportError`。

**自测**：`python -c "import api; print(api.get_connection, api.RequestEvent, api.on_request, api.Text)"`
且不能出现循环导入报错。

### 8.2 离线假连接（`LocalEchoConnection`，**已实现**，见 `snowluma/connection.py` 的 `LocalEchoConnection`）

M8 的 `debug.py` 需要在**不联网**的情况下跑插件（旧实现是 monkeypatch `Bot.send`，
那会绕过整个 M7 逻辑，测不出问题）。所以给一个"假协议端"：

```python
class LocalEchoConnection:
    """离线调试用：所有动作只打印日志，不产生网络请求"""

    def __init__(self, self_id: int = 10000, nickname: str = "DebugBot",
                 message_format: str = "array") -> None:
        self.self_id = self_id
        self.nickname = nickname
        self.message_format_detected = message_format
        self.login_info = {"user_id": self_id, "nickname": nickname}
        self.connected = True
        self.calls: list[tuple[str, dict]] = []

    async def call_action(self, action, *, transport=None, timeout=None, **params):
        self.calls.append((action, params))
        logger.opt(colors=True).info(f"[调试] 动作 <y>{action}</y> 参数 {params}")
        return {"get_login_info": {"user_id": self.self_id, "nickname": self.nickname},
                "get_version_info": {"app_name": "SnowLuma(Debug)", "protocol_version": "v11"},
                "get_status": {"online": True, "good": True}}.get(action, {})

    async def send_message(self, message, *, message_type=None, user_id=None,
                           group_id=None, auto_escape=False):
        target = group_id if message_type == "group" else user_id
        logger.opt(colors=True).success(f"[调试] 发送到 {target}: {normalize_cq(message)}")
        return {"message_id": 0}
```

放在 `snowluma/connection.py`（加进 `__all__`）或 `api/bot.py` 都行；
**关键点**是它必须实现 `send_message` / `call_action` / `self_id` / `connected`，
这样 M7 的 `Bot` 完全不用为调试改代码。

> 注意 `connected` 在真连接上是 **property**，这里写成普通属性即可（鸭子类型，别继承
> `OneBotConnection`——继承会连 `start()`/`stop()` 的副作用一起带进来）。

---

## 9. M7 验收清单（建议放 `tests/test_bot.py`）

### 9.1 脚手架（复用你 `test_connection.py` 的写法 + 清理全局状态）

```python
# tests/test_bot.py（现行实现）
import asyncio

from mock_snowluma import CaseRunner, MockSnowLuma, group_message
from api.bot import Bot
from api.event import GroupMessageEvent
from api.exception import FinishException
from api import get_waiting_task_pool, set_connection
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection
from snowluma.exception import ActionFailed


def config_for(mock: MockSnowLuma, **overrides) -> SnowLumaConfig:
    """与 test_connection.py 里同名助手保持一致"""
    cfg = SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/", forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}", http_token=mock.http_token,
        api_transport="ws", message_format="auto",
        request_timeout=1.0, reconnect_interval=1.0, ping_interval=0, ping_timeout=0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


async def _case() -> int:
    runner = CaseRunner()
    mock = None
    conn = None
    try:
        # ⚠️ 端口传 0：让系统分配，避免固定端口被占用（test_connection.py 用的是 mock 默认端口）
        mock = await MockSnowLuma(ws_port=0, http_port=0).start()
        conn = OneBotConnection(config_for(mock))
        await conn.start()
        runner.check("C0 连上 mock", await conn.wait_until_connected(3))
        set_connection(conn)                   # 全局状态：finally 里必须还原
        bot = Bot()
        ...
    finally:
        set_connection(None)
        left = list(get_waiting_task_pool())   # 等待池是全局的，必须清
        if left:
            get_waiting_task_pool().pop_tasks(left)
        if conn is not None:
            await conn.stop()
        if mock is not None:
            await mock.stop()
    return runner.finish()


def test_bot_against_mock():
    assert asyncio.run(_case()) == 0
```

> **现状**：现行 `tests/test_bot.py` 覆盖的是 C0（连上 mock）、C1（`send_user` 走 private）、
> C2（`reply` 发到群且带引用）、C3（`finish` 抛 `FinishException`）、C4（空消息被跳过）、
> C5（`call_api` 返回 data / 业务失败抛 `ActionFailed`）、C6（`delete_msg`）。
> §9.2 里第 2、5、7、9、10、11、13、15、16 条**目前还没有用例**（待补）。

### 9.2 断语清单（~14 条）

| # | 用例 | 期望 |
| --- | --- | --- |
| 1 | `await bot.send(123456, "hi[CQ:at,qq=1]")` | mock 收到 `send_msg`，`message_type=group`、`group_id=123456`、`message` 是**段数组**（array 模式）、`auto_escape is False` |
| 2 | 同上但 `message_format="string"` 的连接 | `message` 是 CQ 字符串 |
| 3 | `await bot.send(169699201, "hi", "private")` | `message_type=private`、带 `user_id`、**不含 `group_id`** |
| 4 | `await bot.send_user(169699201, "hi")` | 同 3（别名不能发成群） |
| 5 | `await bot.send_group(123456, "hi")` | 同 1 |
| 6 | `await bot.send(123456, "")` / `[]` | 返回 `None`，mock **没有**收到 `send_msg` |
| 7 | `await bot.send(999, "hi")`（mock 注入的风控失败组号） | 返回 `None`，不抛异常 |
| 8 | `set_connection(None)` 后 `await bot.send(1, "hi")` | 返回 `None`（只记 warning，不抛） |
| 9 | `set_connection(None)` 后 `await bot.call_api("get_status")` | 抛 `ConnectionUnavailable` |
| 10 | `await bot.call_api("get_group_info", group_id=123456)` | 返回 dict 且 `group_name == "测试群"`（验证**有 return**） |
| 11 | `await bot.call_api("fail_test")` | 抛 `ActionFailed`（透传连接层语义） |
| 12 | `await bot.reply(GroupMessageEvent(999, group_message("hi")), "收到")` | 发到 `group_id`，`message` 里含 `CQ:reply` |
| 13 | `await bot.reply(PrivateMessageEvent(999, private_message("hi")), "收到")` | 发到 `user_id`，`message_type=private` |
| 14 | `await bot.finish(123456, "bye")` | 抛 `FinishException`，且 mock 确实收到了 "bye" |
| 15 | `bot.func = FuncMeta(f, "on_waiting"); await bot.input_value(group_id=1, user_id=2)` | 等待池多 1 条，`group_id/user_id` 正确，`response_method` 含 `"input"` |
| 16 | `await bot.send(123456, "[CQ:at,qq=1]", auto_escape=True)` | `params["auto_escape"] is True` 且 `message` 原样 |

### 9.3 三条关键断言的写法

```python
# 1：参数形状（array 模式）
await bot.send(123456, "hi[CQ:at,qq=1]")
params = (mock.last_action("send_msg") or {}).get("params", {})
runner.check("1 send_msg 参数形状",
             params.get("message_type") == "group"
             and params.get("group_id") == 123456
             and params.get("message") == [{"type": "text", "data": {"text": "hi"}},
                                           {"type": "at", "data": {"qq": "1"}}],
             json.dumps(params, ensure_ascii=False))

# 14：finish 必须抛 + 消息必须真的发出去
try:
    await bot.finish(123456, "bye")
    runner.check("14 finish 抛 FinishException", False, "没有抛")
except FinishException:
    runner.check("14 finish 抛 FinishException",
                 mock.last_action("send_msg") is not None)

# 8/9：无连接时两种 API 的语义差异（一个吞、一个抛）
set_connection(None)
runner.check("8 无连接 send 返回 None", await bot.send(1, "hi") is None)
try:
    await bot.call_api("get_status")
    runner.check("9 无连接 call_api 抛 ConnectionUnavailable", False, "没有抛")
except ConnectionUnavailable:
    runner.check("9 无连接 call_api 抛 ConnectionUnavailable", True)
```

> mock 的 `send_msg` 已经内置了故障注入：**`group_id == 999` → `retcode=100` 风控失败**
> （见 `tests/mock_snowluma.py` 的 `MockSnowLuma.reply_to`），第 7 条直接用它，不用自己造。

---

## 10. 常见错误排查表

| 现象 | 根因 | 看哪节 |
| --- | --- | --- |
| 日志说"发送失败，账号可能被风控"，但 mock 一个动作都没收到 | `get_connection()` 是空壳 → `None.call_action` 被 `except Exception` 吞掉 | §3 / §0 |
| `AttributeError: 'Bot' object has no attribute '_outgoing_format'` | 抄了连接层的私有方法 | §4.3 |
| 私聊消息发到群 / 群里 @ 变成私聊 | `send_user` 没传 `"private"`；`reply` 用了 `user_id` | §5.1 / §5.2 |
| 协议端报 message_type 非法 | 传了 `"user"`（OneBot 只认 `group`/`private`） | §4.4-1 |
| 插件 `data = await bot.call_api(...)` 拿到 `None` | `call_api` 少了 `return` | §6.2 |
| `bot.finish()` 之后函数还在跑 | 没用 `finally: raise`，或参数顺序写错导致提前返回 | §6.1 |
| 等待任务永远不触发 | `CreateOnWaitingTask` 把 `response_method` 覆盖成了 `None` | §7.3 |
| 发送成功但没有 message_id | `send` 没把 `data` 返回出去 | §4.2 |
| 空消息让日志出现"风控失败" | 没做空消息短路 | §2.5 |
| 多个事件互相污染等待任务 | `Bot.func` 写成了类属性 | §4.1 |

---

## 11. 与 M8 的交接清单

M8（`main.py` + `script.py` + `debug.py`）会依赖 M7 提供的东西：

**M8 会调用**：

- `Bot()`（每事件一个实例）+ `bot.func = func` + `await_run_func(func, bot, event)`
- `Bot.send_group` / `send` / `reply` / `finish`（插件侧仍然是这些）
- `set_connection(connection)`：`main.py` 启动时登记一次，退出时 `set_connection(None)`
- `require_connection()`：`main.py` 里给"必须发消息"的启动逻辑用
- `LocalEchoConnection`：`debug.py` 里 `set_connection(DebugConnection(...))`（§8.2；`debug.py` 的
  `DebugConnection` 继承它）
- `api.is_shutdown_requested()`：退出监听（**不要**读 `utils.to_shutdown` 这个模块级 `bool`，
  那样拿到的是导入时的副本、永远 `False`；详见 M8 教程的 `shutdown_watcher`）

**M7 不做、留给 M8**：

- `main.py` 的事件循环、并发分发、信号与优雅退出、计划任务
- `debug.py` 的控制台命令（`build` / `send` / `array` / `conn` …）
- `check_whether_func` 改用 `get_plain_text`（匹配修 @机器人 命令的那个点）
- `script.py` 的配置加载（去掉 go-cqhttp 检查）

**别在这阶段动 `main.py`**：M7 时它还是旧版，`import main` 能过就够；
M8 会一次性把收发的调度全换掉。

> **下一步**：[M8 教程：运行层](m8-runtime-layer-tutorial.md)（`main.py` + `script.py` + `debug.py`）。
> 它开头列的**三项前置**（`await_run_func` 同时吃同步/异步、`LocalEchoConnection` /
> `require_connection` 导出、`MessageEvent.from_payload`）**现在都已经完成**。

---

## 附录 A：`send_msg` 参数形状速查（写 mock 断言时对照）

```jsonc
// array 模式（对端 messageFormat=array，或 auto 且最近收到的是 array）
{
  "message_type": "group",
  "message": [{"type": "text", "data": {"text": "hi"}},
              {"type": "at", "data": {"qq": "1"}}],
  "auto_escape": false,
  "group_id": 123456
}

// string 模式
{
  "message_type": "private",
  "message": "hi&#91;CQ:at&#44;qq=1&#93;",   // 用户内容已被转义（ADR-0001 D5）
  "auto_escape": false,
  "user_id": 169699201
}

// auto_escape=True 时：message 原样透传，协议端不解析
{"message_type": "group", "message": "[CQ:at,qq=1]", "auto_escape": true, "group_id": 123456}

// 应答（成功）
{"status": "ok", "retcode": 0, "data": {"message_id": 1}, "message": "", "wording": "", "echo": "..."}
// 应答（失败，mock 用 group_id=999 注入）
{"status": "failed", "retcode": 100, "data": null, "message": "risk", "wording": "账号可能被风控", "echo": "..."}
```

---

## 附录 B：`api/bot.py` 改动索引（**M7 动工前**那版 71 行的行号）

> 现行 `api/bot.py` 是 133 行，已按本表改完。这张表保留作"为什么这么改"的对照，
> 行号只对旧的 71 行版本有效。

| 旧位置 | 旧的内容 | 怎么改（现行结果） |
| --- | --- | --- |
| `:1-3` | `import json` / `httpx` / `websockets` | ✅ 已删（M7 不再直接用它们） |
| `:4-7` | `TYPE_CHECKING` 下 import `MessageEvent` | ✅ 保留（类型标注用） |
| `:10-14` | `from .utils import CreateOnWaitingTask, get_connection, Reply` | ✅ 已改成 `CreateOnWaitingTask, get_connection, require_connection`；`Reply` 已删 |
| `:16` | `from plugins.manager import WaitingFuncMeta` | ✅ 保留（`func` 的标注） |
| `:18` | `from snowluma.segment import message_to_payload` | ✅ 已改成 `MessageLike, normalize_cq`（`Bot` 不该自己转格式） |
| `:20-23` | `class Bot` + `func` 类属性 + 空 `__init__` | ✅ §4.1（`func` 移进实例、加连接注入） |
| `:25-44` | `send` | ✅ §4.2 整体替换 |
| `:46-47` | `send_group` | ✅ §5.1 |
| `:49-50` | `send_user`（**漏了 private**） | ✅ §5.1 + 补 `send_private` |
| `:52-53` | `reply`（发错会话、没前缀） | ✅ §5.2 |
| `:55-57` | `finish`（参数顺序错、缺 finally） | ✅ §6.1 |
| `:59-67` | `call_action`（没有 return） | ✅ §6.2（改名 `call_api` + 别名） |
| `:69-71` | `input_value` | ✅ §7.2 |
| — | 便捷动作 | ✅ 只加了 `delete_msg`（其余走 `call_api`，§6.3） |

**改完自查**：`grep -n "call_action(" api/bot.py` 应只剩别名与 `self.call_api` 内部；
`grep -n "_outgoing_format" api/bot.py` 应为空。
