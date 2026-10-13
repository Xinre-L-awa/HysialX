# M8 教程：运行层（`main.py` + `script.py` + `debug.py`）

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。
>
> 配套：[设计文档](snowluma-protocol-design.md) §9「运行层设计」、
> [M6 教程](m6-event-layer-tutorial.md) §11、[M7 教程](m7-bot-layer-tutorial.md) §11。
> 阅读方式：§0 三项前置（不做后面全崩）→ §2 六条约束 → §3–§8 任务 → §9 验收 → §10 排查表。
>
> ✅ **核对现状（重要）**：本文 §0~§8 的任务**全部已落地**。§0 的"三项前置"（`await_run_func`
> 吃同步函数、`MessageEvent.from_payload`、`LocalEchoConnection` / `require_connection` 导出）
> 都已完成；§1.2 表里列的那一堆旧 `main.py` bug 也都修掉了。
> **下面凡写"现在/现状/旧 `main.py`"的地方，说的都是 M8 动工前的代码**，留着是为了讲清修法。
> 核对时请以现行的 `main.py` / `script.py` / `debug.py` 的符号名为准。

---

## TL;DR 动手顺序

| # | 任务 | 产出 | 时长 |
| --- | --- | --- | --- |
| A | 前置三项：`await_run_func` 支持 sync 函数、`MessageEvent.from_payload`、导出 `LocalEchoConnection`/`require_connection` → **已完成** | `api/utils.py`、`api/event.py`、`api/__init__.py`、`snowluma/__init__.py` | 40 min |
| B | 启动序列 `main_async()`（配置 → 插件 → 连接 → 信号 → 等待） | `main.py` 的 `main_async` | 1 h |
| C | 事件分发：`handle_event()` + `event_loop()`（队列 + 并发 worker） | `main.py` 的 `event_loop` / `handle_event` | 1 h |
| D | 三个 preprocessor 改 `async` + 匹配切 `get_plain_text` + 等待任务收尾 | `main.py` 的 `message_preprocessor` / `notice_preprocessor` / `request_preprocessor` | 1.5 h |
| E | 信号 / 优雅退出 / 计划任务修正 | `main.py` 的 `scheduled_loop` / `_due` / `shutdown_watcher` | 1 h |
| F | `script.py`：配置加载 + `load_plugins` 收尾（去 go-cqhttp、恢复 cwd） | `script.py` 全文件 | 30 min |
| G | `debug.py`：离线控制台（`LocalEchoConnection` + `build`/`send`/`array`/`conn`） | `debug.py` 全文件 | 1 h |
| — | 验收：`tests/test_main_startup.py` + `tests/test_debug.py` + `tests/test_responders.py` + 真机联调 | `tests/` | 1 h |

**验收门禁**：`pytest tests/ -q` 全绿（现有 18 条 + 新增）+ `python main.py` 能连真机收事件并回复
+ Ctrl+C 干净退出 + 断开 SnowLuma 后能自愈重连 + 5 个现有插件一行不改。

---

## 0. 前置：三项 M6/M7 遗留（**都已完成**）

> 本节描述的是 M8 动工前的状态。三项前置现在都已落地，下面保留作理由复盘；
> 现行实现见 `api/utils.py` 的 `await_run_func` / `run_func`、`api/event.py` 的
> `MessageEvent.from_payload`、`api/__init__.py` 与 `snowluma/connection.py` 的导出。

M8 是第一个"把所有东西串起来"的里程碑，前面偷的懒会在这里集中爆掉。三项已实测确认：

### 0.1 `await_run_func` / `run_func` 还不能同时吃同步与异步插件函数（**已修**）

动工前的 `api/utils.py` 还是原版：

```python
async def await_run_func(func: "FuncMeta", *args, isDebug=False) -> int:
    res = await func(*args)          # ← 同步插件函数返回的是普通值 / None，await 它会 TypeError
```

实测结论（`python -W error::RuntimeWarning` 跑过，用非 None 的 bot/event）：

| 调用方式 | 插件函数类型 | 函数体执行？ | 结果 |
| --- | --- | --- | --- |
| `await await_run_func(...)` | **同步** | ✅ 执行 | `await "返回值"` → `TypeError` 被 `except Exception` 吞成一条 **ERROR 日志**，返回值丢失 |
| `run_func(...)`（同步入口） | **异步** | ❌ **不执行** | 返回协程对象；调用方一丢弃 → `RuntimeWarning: coroutine ... was never awaited` |
| 直接 `func(bot, event)`（旧 `main.py`） | **异步** | ❌ **不执行** | 同上 → **所有异步 `@RunInLoop` 处理器静默失效 |

所以两种错配的症状完全不同，排查时别混：

- **同步函数走 `await_run_func`**：功能其实**正常**，但每条消息都会刷一条莫明的
  `TypeError: object str can't be used in 'await' expression`，并且**返回值丢失**
  （计划任务/调试台拿不到结果）。
- **异步函数走 `run_func` / 裸调用**：**函数体根本不执行**，就是"插件没反应"的真正来源
  （动工前的 `main.py` 里 `[run_func(func) for func in onstartupFuncs]` 与
  `for func in loopFuncs: func(bot, event)` 都命中这一类）。

你现在的插件里两种都有：`plugins/XHuaLao/main.py` 的 `@RunInLoop def GroupMessageStatistics`
（同步，属第一类）、`plugins/XHuaLao/app.py` 的 `@on_startup def startHuaWeb`（同步，第一类）；
其余插件处理器基本都是 `async def`（第二类）。

顺带两个同源问题：

- 动工前的 `run_func` 在异常路径下 `res` 未赋值，`return res` 会再抛
  `UnboundLocalError`（被 `@logger.catch` 吞掉）；且 `except Exception` 抓不到 `FinishException`
  （它是 `BaseException`），必须显式捕获。

### 0.2 `MessageEvent.from_payload` 不存在（**已加**）

动工前 `api/event.py` 里只有三个具体类（`MessageEvent` / `GroupMessageEvent` /
`PrivateMessageEvent`），没有按 `message_type` 分派的工厂。M8 的分发器需要它
（否则每条消息都要自己 `if/elif` 判类型）。现行实现见 `MessageEvent.from_payload`。

### 0.3 `LocalEchoConnection` 与 `require_connection` 没导出（**已导出**）

- 动工前 `snowluma/connection.py` 已经写好了 `LocalEchoConnection`，但
  `__all__ = ["Channel", "OneBotConnection", "LocalEchoConnection"]` 与
  `snowluma/__init__.py` 都没带它 → `from snowluma import LocalEchoConnection` 会 `ImportError`。
- 动工前 `api/__init__.py` 导出了 `set_connection` / `get_connection`，但**没有** `require_connection`。

两者现在都在 `__all__` / `api/__init__.py` 里。

### 0.4 顺手：`Text()` / `Message()` 的返回标注是错的（**已改成 `-> str`**）

动工前：

```python
def Text(content) -> MessageSegment:      return escape_cq(str(content))     # 实际返回 str
def Message(value) -> MessageSegment:     return normalize_cq(value)         # 实际返回 str
```

运行时没问题，但按 [ADR-0001](adr/0001-message-representation.md) D5，`Text()` 是"CQ 串路径"的
转义出口，标成 `MessageSegment` 会让人误以为它是段对象。改成 `-> str` 即可。

---

## 1. 本阶段目标与边界

### 1.1 目标对照表

| 维度 | 现状（旧 `main.py`） | M8 目标 |
| --- | --- | --- |
| 连接 | `websocket-client` 的 `WebSocketApp` 跑在子线程，`GOCQWSURL` 硬编码 | `OneBotConnection`（M4/M5 已写好）+ 配置驱动 |
| 事件循环 | 每个事件 `asyncio.run(...)` 起独立循环 | **一个** asyncio 事件循环，队列分发 |
| 并发 | 顺序执行，一个插件卡住全阻塞 | `event_workers` 个 worker（信号量限流） |
| 匹配 | `startswith` CQ 串 → `@机器人 命令` 匹配不上 | `get_plain_text` 匹配（ADR-0001 D6） |
| 类型判断 | `func._func.__annotations__["event"]` 裸取（`KeyError`/`TypeError` 风险） | `func_accepts_event`（M6 已写） |
| 退出 | `while is_InLoop: pass` 忙等 + `sys.exit(0)` | `await stop_event.wait()` + 有序取消 |
| 计划任务 | `timedelta.seconds` 判定（基本失效） | `_due()`：固定时刻 / 频率 + 不重复执行 |
| 配置 | `init(False)` 跳过一切检查 | `init()` 读配置、建默认文件、打印脱敏摘要 |
| 调试 | monkeypatch `Bot.send` | `LocalEchoConnection`（走真实 M7 逻辑） |

### 1.2 动工前的现状清单（旧 `main.py` 267 行，逐条对照；**均已处理**）

> 表中"位置"是**旧 `main.py`** 的行号，只对那一版有效；现行 `main.py` 已重写，
> 请按符号名定位。

| 旧位置 | 旧现状 | M8 处理（现行结果） |
| --- | --- | --- |
| `:13-14` | `import websocket` + `Thread` | ✅ 已删（连接层接管） |
| `:42-43` | `@logger.catch def message_preprocessor(...)`（同步） | ✅ 已改 `async def`，去掉 `asyncio.run` |
| `:50-52` | `for func in loopFuncs: if ...: func(bot, event)` —— **协程被丢弃** | ✅ 已改 `await await_run_func(func, bot, event)` |
| `:57` | `func._func.__annotations__["event"]` | ✅ 已改 `func_accepts_event(func, event)` |
| `:60` 等 8 处 | `asyncio.run(await_run_func(...))` | ✅ 已改 `await await_run_func(...)` |
| `:66-67` | `except: ...` 静默吞掉一切 | ✅ 已 `logger.exception`，不吞 `CancelledError` |
| `:75` | `if "input" in task.response_method` | ✅ 已先判 `task.response_method`（M7 §7.3 的坑） |
| `:69-84` | `for ... else: pop_tasks(...)`（`else` 恒执行，靠巧合工作） | ✅ 已改成命中后显式 `pop_tasks` |
| `:88` | 又一处裸注解取值 | ✅ 已改 `func_accepts_event` |
| `:100-102` | `on_at` 用 CQ 串判断 + `func.at` 为 None 时替换串是 `qq=None` | ✅ 已修：粗筛用 `command_text`，`on_at` 用 `func.at or event.get_self_id` 补进候选 |
| `:110-112` | `re.search(...).group(1)`（无捕获组时 `IndexError`） | ✅ 已判 `match.groups()` |
| `:129` | `func.custom_response_method(...)` 可能为 `None` → `TypeError` | ✅ 已判空 |
| `:166-170` | `switch_type` 小映射 | ✅ 已换成 `handle_event` 里的 `match` |
| `:173-200` | `BOT_ID` 全局 + `handle()` + `set_device("114514 大粪手机")` | ✅ 已改用 `connection.self_id`；机型走配置 `device_name` |
| `:203-208` | `start()` 用 `WebSocketApp` | ✅ 已删（`OneBotConnection.start()`） |
| `:210-225` | `isAlive` + 子线程计划任务 + `timedelta.seconds` | ✅ 已改 `scheduled_loop()` + `_due()` |
| `:228-232` | 信号处理里 `sys.exit(0)` | ✅ 已改 `loop.call_soon_threadsafe(stop_event.set)` |
| `:236` | `init(False)` | ✅ 已改 `config = init()` |
| `:238-239` | `is_InLoop` + 硬编码 URL | ✅ 已删；URL 来自配置 |
| `:244` | `[run_func(func) for func in onstartupFuncs]`（协程丢弃） | ✅ 已改 `await await_run_func(func)` |
| `:262-263` | `while is_InLoop: pass`（忙等，烧 CPU） | ✅ 已改 `await stop_event.wait()` |
| `:264-267` | `else:` 分支在 import 时算池子 | ✅ 已保留但改成 `refresh_funcs()` 函数 |

### 1.3 改哪些文件

| 文件 | 动作 |
| --- | --- |
| `api/utils.py` | **只改** `run_func` / `await_run_func` + `Text`/`Message` 标注（§3.1） |
| `api/event.py` | **只加** `MessageEvent.from_payload`（§3.2） |
| `api/__init__.py`、`snowluma/__init__.py` | 补两个导出（§3.3） |
| `main.py` | 按 §4–§7 重写（可整文件重写） |
| `script.py` | 按 §8.1 重写 `init` / `load_plugins` |
| `debug.py` | 按 §8.2 重写（离线控制台） |

不动：`snowluma/**` 的收发实现、`api/event.py` 的事件类本身、5 个插件、
`config/snowluma.json` 的字段（M2 已定）。

---

## 2. 动手前必须想清楚的 6 条约束

### 2.1 单循环：不允许再出现 `asyncio.run` / 线程 / 忙等

`OneBotConnection` 的所有状态（`event_queue`、`_pending` future、`_channels`）都绑定在
**创建它的那个事件循环**上。一旦再出现第二个循环（`asyncio.run(...)`）或子线程，
轻则 `RuntimeWarning`，重则 `Future attached to a different loop`。

自查命令（M8 结束必须为空）：

```bash
grep -rn "asyncio.run\|Thread(\|while is_InLoop\|import websocket" main.py script.py debug.py api/ snowluma/
```

> 唯一例外：`debug.py` 的控制台是同步交互，每条命令用一次 `asyncio.run(...)` 是可以的
> （它不持有长连接）。见 §8.2。

### 2.2 队列 + 并发：为什么要 worker，而不是顺序处理

连接层的读循环已经在把事件塞进 `connection.event_queue`（meta 事件不入队）。
分发侧有三种选择：

| 方案 | 问题 |
| --- | --- |
| 顺序 `await handle_event(payload)` | 一个插件 `await` 网络请求（chatgpt 那种）就阻塞住所有后续事件 |
| 无限制 `create_task` | 一条刷屏消息能瞬间起几百个任务，插件里的数据文件/API 会被打爆 |
| **信号量限流（推荐）** | 并发度 = `config.event_workers`（默认 4），既不打爆也不互相阻塞 |

注意任务集合要留着引用（`set` + `add_done_callback(discard)`），否则任务可能被 GC，
且退出时无法 `gather` 等它们跑完。

### 2.3 三个 preprocessor 必须变成 `async`

旧版是同步函数 + 内部 `asyncio.run`。M8 里它们被 `await` 调用，所以：

- `def message_preprocessor(...)` → `async def message_preprocessor(...)`
- 所有 `asyncio.run(await_run_func(...))` → `await await_run_func(...)`
- `@logger.catch` 可以留（loguru 支持协程），但退出时的 `CancelledError` 会被它记成异常，
  建议改成显式 `try/except`，见 §6.4。

### 2.4 退出顺序：先停收 → 等在途 → 关连接 → 停循环

```
SIGINT / api.shutdown()
      ↓ stop_event.set()
① 取消 event_loop 任务（不再从队列取新事件）
      ↓ 但 queue 里剩下的、正在跑的 handler 要等
② await asyncio.gather(*running_handlers, return_exceptions=True)
③ await connection.stop()        # 关通道、失败所有在途动作、关 HTTP 客户端
④ set_connection(None)           # 防止插件在退出后继续拿旧连接
      ↓
日志 "Closed"
```

顺序反了会出现：正在发消息的插件拿到已关闭的连接（`ConnectionUnavailable` 刷屏），
或者连接关了但 handler 还在往里塞消息。

### 2.5 匹配语义：粗筛用纯文本、`on_at` 由 CQ 串补进候选

旧版拿 `event.get_message`（CQ 串）匹配，于是 `@机器人 菜单` 永远命中不了 `on_command("菜单")`
（串是 `[CQ:at,qq=...] 菜单`，`startswith("菜单")` 为假）。

现行 `message_preprocessor` 的做法（**已落地**）：

```python
plain_text = event.get_plain_text           # 纯文本：custom 匹配用（保留原始前导空格语义）
command_text = plain_text.lstrip()          # 命令/关键字匹配用：@机器人 后面通常跟一个空格

# 粗筛只看纯文本（script.check_whether_func），所以 on_at 不在候选里——它的判据是 CQ 串。
# 消息带了 @机器人 时把 on_at 响应器补进来，否则它们永远不会被触发。
possible = check_whether_func(command_text, get_func_pool())
if f"[CQ:at,qq={event.get_self_id}]" in sender_message:
    already = {id(func) for func in possible}
    possible = sorted(
        list(possible) + [func for func in get_func_pool()
                          if func.match_pattern == "on_at" and id(func) not in already],
        key=lambda func: func.priority,
    )
```

要点（**这张表是现行行为的准绳**）：

| 消费方 | 拿到的字符串 |
| --- | --- |
| 粗筛 `script.check_whether_func` | `command_text = get_plain_text.lstrip()`（去掉 @机器人 前缀的纯文本） |
| `on_at` | `get_message`（CQ 串）里的 `[CQ:at,qq=<func.at or event.get_self_id>]` |
| `custom` 匹配器 | `plain_text`（**原始、不去空白**，保留前导空格语义） |
| `on_command` / `on_keyword` / `on_regex` | `command_text` |

- **`on_at` 不再参与粗筛**：`script.check_whether_func` 里那段"顺带判 CQ 串"的分支**已删除**，
  改由 `main.py` 在检测到 `[CQ:at,qq=self_id]` 时把 `match_pattern == "on_at"` 的响应器
  按 `priority` 合并进候选（去重靠 `id(func)`）。所以 `on_at` 是"要求必须 @"的**额外条件**。
- `on_command("菜单")` 对 `菜单` 和 `@机器人 菜单` **都能命中**（靠 `lstrip()`）。
- **`custom` 响应器的判断函数**：继续传 `get_plain_text`（它本质是匹配）。
  影响面已核对：5 个插件里只有 `plugins/Defalut/main.py` 的 `custom`，
  它只看 `x[0] == ' '`，两种输入行为一致 → 安全。
- **回显仍用 `event.get_message`**（CQ 串、已转义）或 `Text(...)`/`auto_escape=True`，
  绝不回显 `get_plain_text`（未转义 → CQ 注入，见 ADR-0001 D5）。

### 2.6 计划任务的正确判定

旧实现（旧 `main.py`）：

```python
sub_time = lambda t1, t2: (strptime(t1) - strptime(t2)).seconds   # t1=上次执行 t2=现在
if task.last_execution_time == "" or sub_time(task.last_execution_time, now()) or now() == task.fixed_execute_time:
```

`last_execution_time - now` 是**负** timedelta，而 `.seconds` 对负值返回的是
`86395` 这种巨大的正数（不是 0）→ 条件恒真 → 任务每秒狂跑。`frequency` 参数完全没用上。

M8 的 `_due()`：

```python
def _due(task, now: datetime.datetime, stamp: str) -> bool:
    fixed = (task.fixed_execute_time or "").strip()
    if fixed:
        # 支持 "YYYY-MM-DD HH:MM:SS" / "HH:MM:SS" / "HH:MM"；同一秒不重复
        return (stamp == fixed or stamp.endswith(fixed)) and task.last_execution_time != stamp
    frequency = float(task.frequency or 0) or 1.0     # 0 当 1 秒，避免"每秒狂跑"的旧行为
    if not task.last_execution_time:
        return True
    try:
        last = datetime.datetime.strptime(task.last_execution_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (now - last).total_seconds() >= frequency
```

### 2.7 Windows 信号限制

`loop.add_signal_handler()` 在 Windows 上**不可用**（`NotImplementedError`）。要用：

```python
loop = asyncio.get_running_loop()

def _on_signal(signum, frame):
    loop.call_soon_threadsafe(stop_event.set)      # 信号回调不在事件循环里，必须线程安全地转交

signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)          # 包在 try/except 里（非主线程会 ValueError）
```

---

## 3. 任务 A：前置三项（**均已完成**）

### 3.1 `run_func` / `await_run_func` 支持同步 + 异步（现行实现见 `api/utils.py`）

```python
import asyncio
import inspect

def _name_of(func) -> str:
    return getattr(func, "name", None) or getattr(func, "__name__", str(func))

def _run_awaitable(awaitable):
    """没有事件循环时把协程跑完；已经在循环里则转成 task（不能 asyncio.run 嵌套）"""
    async def _runner():
        return await awaitable
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_runner())

    task: "asyncio.Task" = asyncio.ensure_future(awaitable)
    task.add_done_callback(_log_task_exception)     # fire-and-forget 的异常要被记下来
    return task


def _log_task_exception(task: "asyncio.Task") -> None:
    """兜住 fire-and-forget 任务的异常，否则会被静默吞掉（或只在 GC 时警告）"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception(exc)

@logger.catch
def run_func(func, *args, isDebug: bool = False):
    """同步入口（on_startup / 计划任务 / 调试台）"""
    try:
        res = func(*args)
    except FinishException:
        return None
    except Exception as exc:
        logger.exception(exc); return -1
    if inspect.isawaitable(res):
        try:
            res = _run_awaitable(res)
        except FinishException:
            return None
        except Exception as exc:
            logger.exception(exc); return -1
    if isDebug:
        logger.debug(f"{_name_of(func)} 执行完毕")
    return res


@logger.catch
async def await_run_func(func, *args, isDebug: bool = False):
    """事件循环里的唯一入口：同步/异步插件函数都能跑"""
    try:
        res = func(*args)                          # FuncMeta.__call__ → 插件函数的返回值/协程
    except FinishException:
        return None
    except Exception as exc:
        logger.exception(exc); return -1

    if inspect.isawaitable(res):                   # ← 关键：同步函数返回 None 时不会 await None
        try:
            res = await res
        except FinishException:
            return None
        except asyncio.CancelledError:
            raise                                  # 退出时要原样抛，否则 gather 卡住
        except Exception as exc:
            logger.exception(exc); return -1

    if isDebug:
        logger.debug(f"{_name_of(func)} 执行完毕")

    return res
```

**自测点**（三条，覆盖这次踩的坑）：

```python
# 1) 同步函数不再炸
def sync_fn(bot, event): return "ok"
await await_run_func(FuncMeta(sync_fn, "on"), None, None)      # 不能抛 TypeError

# 2) 异步函数的异常被记录但不外抛
async def boom(bot, event): raise ValueError("x")
await await_run_func(FuncMeta(boom, "on"), None, None)         # 有日志、不 raise

# 3) FinishException 被吞掉（现行实现是"静默返回 None"，不记日志）
async def fin(bot, event): raise FinishException
assert await await_run_func(FuncMeta(fin, "on"), None, None) is None
```

> `FinishException` 的语义：**吞掉、返回 `None`**（现行实现不再额外记一条日志），
> 这样插件里 `bot.finish()` 之后分发继续走。关键是 `except Exception` 抓不到它，
> 必须显式处理，别让它穿透到 `event_loop` 顶层。
> `@logger.catch` 仍留在两个函数上（只兜住真正漏网的异常，属无害的风格取舍）。

### 3.2 `MessageEvent.from_payload`（**已加**，见 `api/event.py`）

```python
    @classmethod
    def from_payload(cls, payload: dict) -> "MessageEvent":
        """按 message_type 分派到具体子类（M8 分发器唯一入口）"""
        message_type = (payload or {}).get("message_type")
        if message_type == "group":
            return GroupMessageEvent(payload.get("self_id"), payload)
        if message_type == "private":
            return PrivateMessageEvent(payload.get("self_id"), payload)
        return MessageEvent(payload.get("self_id"), payload)
```

> 放在 `MessageEvent` 类体内（`GroupMessageEvent` 定义在它后面，但方法体在调用时才解析名字，
> 不会 `NameError`）。

### 3.3 两个导出（**已加**）

```python
# snowluma/__init__.py
from .connection import LocalEchoConnection as LocalEchoConnection
# 并把 "LocalEchoConnection" 加进 connection.py 的 __all__
# （现行 __all__ = ["Channel", "OneBotConnection", "LocalEchoConnection"]）

# api/__init__.py
from .utils import require_connection as require_connection
```

**自测**：`python -c "from snowluma import LocalEchoConnection; from api import require_connection; print('ok')"`

---

## 4. 任务 B：启动序列

### 4.1 `main_async()` 骨架（**已落地**，见 `main.py` 的 `main_async`）

```python
async def main_async() -> None:
    config = init()                              # script.init：建/读 config/snowluma.json 并返回配置
    load_plugins()
    refresh_funcs()

    for func in onstartupFuncs:                  # on_startup 支持同步/异步
        await await_run_func(func)

    connection = OneBotConnection(config)
    set_connection(connection)
    await connection.start()                     # 起正向/反向通道，非阻塞

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal(signum, frame):
        logger.opt(colors=True).info(f"收到信号 <y>{signum}</y>，正在关闭 HysialX...")
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass                                 # 非主线程等场景

    tasks = [
        asyncio.create_task(event_loop(connection), name="event-loop"),
        asyncio.create_task(scheduled_loop(stop_event), name="scheduled-loop"),
        asyncio.create_task(shutdown_watcher(stop_event), name="shutdown-watcher"),  # name 必须用关键字传
    ]

    if connection.connected:
        logger.opt(colors=True).success("已连接到 SnowLuma")
    else:
        # connection.start() 只是"把连接任务起起来"，这里通常还没连上，别急着下结论
        logger.info("HysialX 已启动，正在与 SnowLuma 建立连接（连上后会自动开始收事件）...")

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await connection.stop()
        set_connection(None)
        logger.opt(colors=True).info("Closed")


def main() -> int:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.opt(colors=True).info("Closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
else:
    refresh_funcs()                              # 被当模块导入（调试台/测试）时也要有池子
```

要点：

1. **`init()` 有返回值**：M8 的 `script.init()` 返回 `SnowLumaConfig`（§8.1），
   `main.py` 不再自己读配置。
2. **`refresh_funcs()` 抽成函数**：旧版在 `if/else` 两处各写三行，容易漏；
   抽出来后 `debug.py` 也能复用（`main.refresh_funcs()`）。
3. **`connection.connected` 只是瞬时状态**：连上之前是 `False`，所以别在这里 `return`；
   真正的收发由连接层自己的任务完成。
4. **`on_startup` 里的同步函数**（XHuaLao 起 Flask）走 `await_run_func` → §3.1 已能处理。

---

## 5. 任务 C：事件分发

### 5.1 `handle_event(payload)`：唯一的事件入口

```python
async def handle_event(payload: dict) -> None:
    """解析一条 OneBot 事件并分发（连接层与调试台共用）"""
    if not isinstance(payload, dict):
        return

    post_type = payload.get("post_type")
    if post_type == "meta_event":                # 连接层已消化，理论上不会进来
        return

    bot = Bot()
    try:
        match post_type:
            case "message" | "message_sent":
                await message_preprocessor(bot, MessageEvent.from_payload(payload))
            case "notice":
                await notice_preprocessor(bot, NoticeEvent.model_validate(payload))
            case "request":
                await request_preprocessor(bot, RequestEvent.model_validate(payload))
            case _:
                logger.debug(f"忽略未知事件类型: {post_type}")
    except ValidationError as exc:                # pydantic v2：字段不合规只警告，别炸分发
        logger.warning(f"事件字段不符合 OneBot 协议（post_type={post_type}）: {exc}")
```

### 5.2 `event_loop(connection)`：队列 + 限流并发

```python
async def event_loop(connection: OneBotConnection) -> None:
    semaphore = asyncio.Semaphore(max(1, connection.config.event_workers))
    running: set[asyncio.Task] = set()

    async def worker(payload: dict) -> None:
        async with semaphore:
            try:
                await handle_event(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:              # 兜底：单个事件失败不能拖垮循环
                logger.exception(exc)

    try:
        while True:
            payload = await connection.event_queue.get()
            task = asyncio.create_task(worker(payload), name=f"event-{payload.get('post_type')}")
            running.add(task)
            task.add_done_callback(running.discard)      # 必须留引用，否则可能被 GC
    except asyncio.CancelledError:
        raise
    finally:                                             # 退出时等在途 handler 跑完
        if running:
            await asyncio.gather(*running, return_exceptions=True)
```

**自测点**：起 mock + 真连接，推 3 条事件，断言三条都进了 `handle_event`；
再把 `event_workers` 设为 1，推一条会 `sleep(0.5)` 的事件 + 一条普通事件，观察第二条要等——这说明限流生效。

---

## 6. 任务 D：三个 preprocessor

### 6.1 `message_preprocessor`（触发顺序不要变）

旧版的顺序是：`RunInLoop` → `custom` → 等待任务 → 响应器。这个顺序**被插件依赖**
（`XHuaLao` 的统计是 `RunInLoop`，必须在响应器之前跑，否则 `菜单` 之类的消息统计不到），
M8 保持原序，只把每步改成 `await`：

```python
async def message_preprocessor(bot: Bot, event: MessageEvent) -> None:
    sender_message = event.get_message          # CQ 串：用于日志与"回显"
    plain_text = event.get_plain_text           # 纯文本：用于匹配（ADR-0001 D6）

    if event.is_group:
        name = event.get_user_group_name or event.get_user_name
        logger.info(f"收到群 {event.get_group_id} 中来自 {name}({event.get_user_id}) 的消息: {sender_message}")
    else:
        logger.info(f"收到来自好友 {event.get_user_name} 的消息：{sender_message}")

    # ① RunInLoop（收消息钩子）
    for func in loopFuncs:
        if func_accepts_event(func, event):
            await await_run_func(func, bot, event)

    # ② custom（自定义判断函数）
    for func in customFuncs:
        try:
            matcher = func.custom_response_method
            if matcher and matcher(plain_text) and func_accepts_event(func, event):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(sender_message)
                await await_run_func(func, bot, event)
        except Exception as exc:
            logger.debug(f"custom 响应器 {func.name} 判断失败: {exc}")

    # ③ 等待任务（同会话同一个人）
    to_be_removed = []
    for task in list(get_waiting_task_pool()):
        if event.get_group_id == task.group_id and event.get_user_id == task.user_id:
            to_be_removed.append(task)
            waiting_event = WaitingEvent(event)
            if task.response_method and "input" in task.response_method:   # ← 判空，别炸
                waiting_event.input_value = event.get_message
            await await_run_func(task.func, bot, waiting_event)
    if to_be_removed:
        get_waiting_task_pool().pop_tasks(to_be_removed)

    # ④ 响应器
    for func in check_whether_func(plain_text, get_func_pool()):
        if not func_accepts_event(func, event):
            continue
        bot.func = func
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")

        if func.match_pattern == "on_keyword":
            logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
            await await_run_func(func, bot, event)
            if func.block:
                break

        elif func.match_pattern == "on_at":
            target = func.at or event.get_self_id
            if f"[CQ:at,qq={target}]" in sender_message:            # 用 CQ 串判断"有没有 @"
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(event.get_message.replace(f"[CQ:at,qq={target}]", "", 1).strip())
                await await_run_func(func, bot, event)
                if func.block:
                    break

        elif func.match_pattern == "on_regex":
            match = re.search(func.regex, plain_text) if func.regex else None
            if match:
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                if match.groups():
                    event.set_message(match.group(1))
                await await_run_func(func, bot, event)
                if func.block:
                    break

        elif func.match_pattern == "on_command":
            if plain_text in func.cmd:
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                await await_run_func(func, bot, event)
                if func.block:
                    break

        elif func.match_pattern == "on_waiting":
            if (func.cmd == "JUSTCHILD"):
                continue
            matcher = func.custom_response_method
            if plain_text == func.cmd or (matcher and matcher(plain_text)):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                get_waiting_task_pool().add_task(WaitingTask(
                    func.child_func, user_id=event.get_user_id, group_id=event.get_group_id))
                bot.func = func
                await await_run_func(func, bot, event)
                if func.block:
                    break
```

四个容易写错的地方（都已体现在上面）：

1. **`on_command` 现在比对 `plain_text`**：`@机器人 菜单` 与 `菜单` 都能命中。
2. **`func.at or event.get_self_id`**：旧版替换串用的是 `func.at`（可能是 `None`）→
   `[CQ:at,qq=None]`，永远替换不到。`on_at()` 不传 qq 表示"@ 机器人自己"。
3. **`match.groups()` 判空**：旧版 `re.search(...).group(1)` 在正则没有捕获组时 `IndexError`。
4. **等待任务的 `response_method` 判空**：M7 §7.3 那个坑（`CreateOnWaitingTask` 会把默认值
   覆盖成 `None`），这里 `if task.response_method and "input" in ...` 双保险。

### 6.2 `notice_preprocessor` / `request_preprocessor`

```python
async def notice_preprocessor(bot: Bot, event: NoticeEvent) -> None:
    logger.info(f"收到通知 {event.notice_type}"
                + (f"/{event.sub_type}" if event.sub_type else "")
                + f"，来自 {event.group_id or event.user_id}")
    for func in get_notice_func_pool():
        if func.notice_type is not None and func.notice_type != event.get_notice_int_type:
            continue
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")
        logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
        await await_run_func(func, bot, event)
        if func.block:
            break


async def request_preprocessor(bot: Bot, event: RequestEvent) -> None:
    logger.info(f"收到请求 {event.request_type}"
                + (f"/{event.sub_type}" if event.sub_type else "")
                + f"，来自 {event.user_id}，备注: {event.get_comment}")
    for func in get_request_func_pool():
        if func.request_type is not None and func.request_type != event.get_request_int_type:
            continue
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")
        logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
        await await_run_func(func, bot, event)
        if func.block:
            break
```

> M6 的 `NoticeEvent.get_notice_int_type` 未知类型返回 `None`；`func.notice_type` 为 `None`
> 时表示"不限类型"，所以判据是 `is not None and !=`。

### 6.3 别忘了 `refresh_funcs()`

```python
loopFuncs = None
customFuncs = None
onstartupFuncs = None

def refresh_funcs() -> None:
    """插件加载/重载后刷新常用函数池"""
    global loopFuncs, customFuncs, onstartupFuncs
    loopFuncs = getExpectedFuncs(get_func_pool(), "RunInLoop")
    customFuncs = getExpectedFuncs(get_func_pool(), "custom")
    onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")
```

### 6.4 `@logger.catch` 的去留

`@logger.catch` 会把 `CancelledError` 记成异常（退出时刷一屏红）。给 preprocessor 用可以，
但 `event_loop` / `scheduled_loop` 这类**会被取消**的协程不要用，
用 §5.2 的 `except asyncio.CancelledError: raise` 写法。

---

## 7. 任务 E：信号、优雅退出、计划任务

### 7.1 优雅退出（承接 §2.4 的顺序）

```python
async def shutdown_watcher(stop_event: asyncio.Event) -> None:
    """让插件能通过 api.shutdown() 请求退出"""
    while not stop_event.is_set():
        if api_utils.to_shutdown:
            logger.opt(colors=True).info("插件请求关闭 HysialX...")
            stop_event.set()
            return
        await asyncio.sleep(0.5)
```

⚠️ `api/utils.py` 的 `to_shutdown` 是模块级 `bool`。`from api import to_shutdown` 拿到的是
**副本**，`shutdown()` 改的是模块里的那个 → 一定要 `import api.utils as api_utils` 后读
`api_utils.to_shutdown`（或 `import api.utils; api.utils.to_shutdown`）。

### 7.2 计划任务循环

```python
async def scheduled_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        now = datetime.datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        to_be_removed = []
        for task in list(get_scheduled_task_pool()):
            try:
                if not _due(task, now, stamp):
                    continue
                task.last_execution_time = stamp
                result = task.execute()                 # "shell" 类型会 popen，函数类型会调用
                if inspect.isawaitable(result):         # 计划任务也可以是 async def
                    await result
                if task.disposable:
                    to_be_removed.append(task)
            except Exception as exc:
                logger.exception(exc)
        if to_be_removed:
            get_scheduled_task_pool().pop_tasks(to_be_removed)
        await asyncio.sleep(1)
```

> `on_scheduled` 目前没有示例插件在用（`plugins/Defalut/main.py` 里是注释掉的），
> 所以这一块**没有现成验收用例**——建议顺手写一条：`@on_scheduled(frequency=1, disposable=True)`
> 的函数在 3 秒内只跑 1 次。

---

## 8. 任务 F/G：`script.py` 与 `debug.py`

### 8.1 `script.py`：去掉 go-cqhttp，换成 SnowLuma 配置

现状（[:17-34](../script.py#L17)）还在检查 `./go-cqhttp` 目录并读 `go-cqhttp/config.yml`，
而 `main.py` 调的是 `init(False)`（跳过全部检查）→ 等于什么都没校验。

```python
def init(check_files: bool = True) -> SnowLumaConfig:
    """打印启动横幅、准备配置文件，返回 SnowLuma 连接配置"""
    logger.opt(colors=True).info("Hysial Bot is starting...")

    if check_files:
        logger.opt(colors=True).info("Checking config files...")
        if write_default_config(DEFAULT_CONFIG_PATH):
            logger.opt(colors=True).success(
                f"已生成默认配置文件 <y>{DEFAULT_CONFIG_PATH}</y>（留空字段表示跟随 SnowLuma）")
        data_dir = Path(DEFAULT_PLUGINS_DATA_PATH)
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            logger.opt(colors=True).info(f"已创建插件数据目录 <y>{DEFAULT_PLUGINS_DATA_PATH}</y>")

    config = load_config(DEFAULT_CONFIG_PATH, create=check_files)
    logger.opt(colors=True).info("SnowLuma 连接配置:\n" + config.describe())
    return config
```

`check_whether_func` 也要跟着 §2.5 改（入参变成纯文本），并把 `str.startswith(list)` 修掉
（`startswith` 不接 `list`，会 `TypeError`）：

```python
def check_whether_func(message: str, func_pool: "FuncPool") -> List["FuncMeta"]:
    matched = []
    for func in func_pool:
        cmds = func.cmd
        if isinstance(cmds, str):
            cmds = [cmds]
        hit = False
        if cmds:
            try:
                hit = message.startswith(tuple(str(c) for c in cmds))
            except TypeError:
                hit = False
        if not hit and func.regex:
            hit = re.search(func.regex, message) is not None
        if not hit and func.match_pattern == "on_at" and "[CQ:at" in message:
            hit = True          # 注意：on_at 的可用性依赖 event.get_message（CQ 串），见 §6.1
        if hit:
            matched.append(func)
    return sorted(matched, key=lambda x: x.priority)
```

> ⚠️ 这里的入参在 §6.1 传的是 `plain_text`，而 `on_at` 需要看 CQ 串里的 `[CQ:at,...]`。
> 两种做法任选：
> ① `on_at` 不走粗筛（`check_whether_func` 里不要那个分支），直接在 §6.1 的循环里按
> `"[CQ:at" in sender_message` 过滤——本教程推荐这种；
> ② 把 `check_whether_func` 的入参改成 `(plain_text, cq_message)` 两个。

`load_plugins` 的收尾：用 `try/finally` 保证 cwd 一定还原（否则 `log.py` 的相对文件 sink
会在 `plugins/` 下建一个 `logs/` 目录，我上次实测就是这样多出来的 `plugins/logs/`）：

```python
def load_plugins():
    plugins_dir = Path("plugins").resolve()
    if not plugins_dir.is_dir():
        logger.error(f"未找到插件目录: {plugins_dir}")
        return
    names = [p.name for p in plugins_dir.iterdir()
             if p.is_dir() and not (p.name.startswith("__") or p.name.endswith(".py"))]
    cwd = os.getcwd()
    if str(plugins_dir) not in sys.path:
        sys.path.append(str(plugins_dir))
    try:
        os.chdir(plugins_dir)
        for name in names:
            module = import_module(name)
            if module is None:
                continue
            get_plugin_pool().add_plugin(getattr(module, "__plugin_meta__", PluginMeta(module.__name__)))
            logger.opt(colors=True).success(f'Succeeded to import plugin <y>"{module.__name__}"</y>')
    finally:
        os.chdir(cwd)
```

### 8.2 `debug.py`：离线控制台

旧版靠 `Bot.send = new_send` 直接换掉方法——那会**绕过整个 M7 逻辑**（格式转换、日志、异常语义
全都测不到）。M8 改用 `LocalEchoConnection`：

```python
import asyncio, json, re, signal
from pathlib import Path
from termcolor import colored

import main as main_module
from api import get_func_pool, get_plugin_pool, get_waiting_task_pool, getExpectedFuncs, run_func, set_connection
from api.event import GroupMessageEvent, PrivateMessageEvent
from log import logger
from snowluma import LocalEchoConnection

DEBUG_SELF_ID = 3592797817
DEBUG_GROUP_ID = 859874709
DEBUG_USER_ID = 169699201
DEBUG_USER_NAME = "雨弈"


def build_payload(content: str, *, msg_type: str = "group", to_what_id: int = DEBUG_GROUP_ID,
                  message_format: str = "array", self_id: int = DEBUG_SELF_ID) -> dict:
    """构造一条 OneBot v11 消息事件（与 mock_snowluma 的工厂保持同形）"""
    from snowluma.segment import parse_cq_to_segments, segments_to_dicts
    message = segments_to_dicts(parse_cq_to_segments(content)) if message_format == "array" else content
    payload = {
        "post_type": "message", "message_type": msg_type, "sub_type": "normal",
        "time": int(time.time()), "self_id": self_id, "message_id": 12345,
        "message": message, "raw_message": content, "font": 0,
        "sender": {"user_id": DEBUG_USER_ID, "nickname": DEBUG_USER_NAME, "card": "群名片", "role": "owner"},
    }
    payload[f"{msg_type}_id"] = to_what_id
    return payload


def feed(payload: dict) -> None:
    """把事件喂给真实分发链（同步控制台里用 asyncio.run 是安全的：不持有长连接）"""
    asyncio.run(main_module.handle_event(payload))
```

命令表（**已落地的形态**，`get_waiting_pool` 简化为 `pool`）：

| 命令 | 作用 |
| --- | --- |
| `help` | 列出命令与说明 |
| `build <$var> <内容> [-type=group\|private] [-to=ID] [-format=array\|string]` | 构造消息事件存进变量（内容 = 变量名之后、第一个 `-param` 之前） |
| `send <$var\|JSON> [次数]` | 投递给 `handle_event`（不是事件 JSON 时给友好提示，不抛栈） |
| `array <内容>` | 用 array 格式直接构造并投递一条群消息 |
| `notice [notice_type] [-sub_type=..] [-user=..]` | 造并投递通知事件（默认 `group_increase`） |
| `request [friend\|group]` | 造并投递请求事件 |
| `sent <内容>` | 造并投递 `message_sent`（机器人自己发的消息） |
| `set <name> <value>` | 设置变量（发送时可用 `$name`） |
| `conn` | 打印调试连接：`self_id` / `nickname` / `message_format` / `fail` / 已记录动作数 |
| `fail on\|off` | 发送失败注入（验证 `send` 吞异常、`call_api` 抛异常） |
| `pool` / `clear` | 查看 / 清空等待任务池 |
| `plugins` | 列出已加载插件 |
| `reload` | 真正重载插件模块 + 重建函数池（细节见下） |
| `exit` | 退出 |

**假连接要用子类而不是直接改 `LocalEchoConnection`**：父类只打印日志、不写 `calls`，
也没法注入失败。加一个 12 行的子类即可（父类 `send_message` 记录后再委托）：

```python
class DebugConnection(LocalEchoConnection):
    def __init__(self, *, fail: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.fail = fail

    async def send_message(self, message, *, message_type=None, user_id=None,
                           group_id=None, auto_escape=False):
        self.calls.append(("send_msg", {...}))                # 便于测试/`conn` 断言
        if self.fail:
            raise ActionFailed("send_msg", status="failed", retcode=100,
                               wording="调试注入的失败（fail on）")
        return await super().send_message(...)
```

**`reload` 有两个坑（都已实测踩过）**：

1. `load_plugins()` 会命中 `sys.modules` 缓存，**插件不会重新执行** → 必须 `importlib.reload`；
   且要先清空 `func_pool` / `notic_func_pool` / `request_func_pool`，否则重载后一个命令触发两次。
2. reload 前**必须 `os.chdir("plugins")`**，结束后 `finally` 还回去：
   `plugins/t/main.py` 开头就是 `chdir("..")` → 读根目录数据 → `chdir("plugins")`，
   它假设自己在 plugins 目录里。从项目根直接 reload 会让它逃到父目录（实测 cwd 变成
   `D:\Projects`，之后 `DataForXPlugin/*.json` 全部找不到）。

`start()`：

```python
def start(run_startup: bool = True):
    set_connection(DebugConnection(self_id=DEBUG_SELF_ID, nickname="HysialX-Debug"))
    main_module.load_plugins()
    main_module.refresh_funcs()
    if run_startup:                            # python debug.py --no-startup 可跳过
        for func in getExpectedFuncs(get_func_pool(), "on_startup"):
            run_func(func, isDebug=True)       # 同步入口；XHuaLao 会在 1145 起 Flask
    loop()
```

**自测**：`python debug.py` → `build $msg echo 你好 -format=array` → `send $msg`，
应看到真实插件的回显日志（`[调试] 发送到 ...`），并且**没有** `RuntimeWarning`。

---

## 9. M8 验收清单

### 9.1 自动化：已落地为这三个用例文件

- `tests/test_main_startup.py`：在 mock 上真跑一次 `main_async()`（启动 → 收事件 → `api.shutdown()` → 干净退出）
- `tests/test_responders.py`：分发矩阵（`on_at` / `@机器人 命令` / 正则 / custom / 等待任务链 / 池游标）
- `tests/test_debug.py`：调试台链路（造事件 → `handle_event` → 真实插件 → 假连接）

下面是"队列 → 分发 → 插件 → 发送"这条链的最小参考实现（D1 的形态，已落地在 `tests/test_responders.py`）：

```python
import asyncio
from mock_snowluma import CaseRunner, MockSnowLuma, group_message
from api import get_waiting_task_pool, on_command, set_connection
from api.bot import Bot
from snowluma.connection import OneBotConnection
from snowluma.config import SnowLumaConfig
import main as main_module


def config_for(mock, **overrides):
    cfg = SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/", forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}", http_token=mock.http_token,
        api_transport="ws", message_format="auto", request_timeout=1.0,
        reconnect_interval=1.0, ping_interval=0, ping_timeout=0, event_workers=2,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


async def _case() -> int:
    runner = CaseRunner()
    mock = await MockSnowLuma().start()
    conn = OneBotConnection(config_for(mock))
    await conn.start()
    await conn.wait_until_connected(3)
    set_connection(conn)

    @on_command("菜单")
    async def menu(bot: Bot, event):
        await bot.send(event.get_group_id, "菜单内容")

    main_module.refresh_funcs()                     # 关键：注册后必须刷新
    loop_task = asyncio.create_task(main_module.event_loop(conn))
    try:
        # D1：@机器人 也能命中 on_command（plain_text 匹配）
        payload = group_message("菜单")
        payload["message"] = [{"type": "at", "data": {"qq": "999"}},
                              {"type": "text", "data": {"text": " 菜单"}}]
        payload["raw_message"] = "[CQ:at,qq=999] 菜单"
        await mock.push(payload)
        got = await wait_until(lambda: mock.last_action("send_msg") is not None, 3)
        runner.check("D1 @机器人 命中 on_command 并回复", got)
    finally:
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)
        get_waiting_task_pool().pop_tasks(list(get_waiting_task_pool()))
        set_connection(None)
        await conn.stop()
        await mock.stop()
    return runner.finish()


def test_startup_smoke():
    assert asyncio.run(_case()) == 0
```

建议覆盖（8 条，均已有对应用例）：

| # | 检查 | 现在落在哪 |
| --- | --- | --- |
| D1 | `@机器人 菜单` 命中 `on_command("菜单")`（ADR-0001 D6 的收益） | `test_responders.py::test_at_prefixed_command_hits` |
| D2 | `RunInLoop` 在响应器之前执行（用一个往 list 里 append 的 `@RunInLoop` 断言顺序） | `test_responders.py::test_runinloop_before_responders` |
| D3 | 同步插件函数不报错（`def sync_handler(bot, event)` 能跑完） | `test_responders.py::test_sync_handler_does_not_break` |
| D4 | `on_waiting` + `bot.input_value()`：下一条同人同会话消息触发子函数 | `test_responders.py::test_on_waiting_child_chain` |
| D5 | 等待任务里 `response_method` 为 `None` 时不炸 | `test_responders.py::test_waiting_task_with_none_response_method` |
| D6 | 未知 `notice_type` 不炸，`get_notice_int_type is None` 时按"不限类型"匹配 | `test_responders.py::test_unknown_notice_type_is_tolerated` |
| D7 | `event_workers=1` 时并发被限流（第二条事件等到第一条结束） | `test_event_loop.py::test_event_workers_serialize_handlers` |
| D8 | `stop_event`/取消后 `event_loop` 在途 handler 不被丢掉 | `test_event_loop.py::test_event_loop_waits_for_inflight_handler` |

### 9.2 人工/发布前：完整 `main.py` 端到端

用一个把 `main_async()` 跑起来的脚本（my 上次的做法）：mock 起在随机端口，用**环境变量**
把配置指过去（这样不用改 `config/snowluma.json`）：

```bash
SNOWLUMA_FORWARD_WS=ws://127.0.0.1:3031/ SNOWLUMA_FORWARD_TOKEN=mainrun \
SNOWLUMA_MODE=forward SNOWLUMA_MESSAGE_FORMAT=array python main.py
```

检查点：

1. 日志出现"已连接 SnowLuma 正向 WebSocket"→"生命周期事件 connect/enable"→"Connected successfully! 当前机器人账号 …"→"协议端: SnowLuma x.y.z / OneBot v11"；
2. 群里发 `echo hi` → 机器人回 `hi`（Defalut 插件）；
3. `Ctrl+C` → 打印"收到信号…"→"Closed"，进程退出码 0，没有 traceback；
4. 运行中关掉 SnowLuma → 日志出现断线告警 + 退避重连；重开 → 自动恢复收发；
5. `python debug.py` 能离线跑通（§8.2）。

> ⚠️ **跑真机前先备份 `DataForXPlugin/`**：`plugins/XHuaLao` 的 `@RunInLoop` 统计会在**每条消息**
> 上写 `GroupStatistics.json` / `GroupRecordingTime.json`；`plugins/t` 的"签到/个人信息"还会写
> `qian_dao_.json` / `wealth.json`。你已经建了 `DataForXPlugin.bak/`，继续保持。

---

## 10. 常见错误排查表

| 现象 | 根因 | 看哪节 |
| --- | --- | --- |
| 同步插件函数每条消息刷一条 `TypeError: object str can't be used in 'await' expression`，返回值丢失 | `await_run_func` 对同步函数也做了 `await` | §0.1、§3.1 |
| 插件"没反应" + `RuntimeWarning: coroutine ... was never awaited` | 异步函数走了 `run_func` / 裸 `func(bot,event)`，**函数体从未执行** | §0.1、§3.1 |
| `Future attached to a different loop` | 还有 `asyncio.run` 或子线程在碰连接对象 | §2.1 |
| `@机器人 命令` 没反应 | 匹配还在用 CQ 串 | §2.5、§6.1 |
| `KeyError: 'event'` / `TypeError: isinstance() arg 2` | 裸取 `__annotations__["event"]` | §6.1（`func_accepts_event`） |
| `TypeError: argument of type 'NoneType' is not iterable` | `task.response_method` 是 `None` | §6.1-4、M7 §7.3 |
| `IndexError: no such group` | 正则没有捕获组还 `group(1)` | §6.1-3 |
| 退出时刷一屏 `CancelledError` 异常 | `@logger.catch` 用在会被取消的协程上 | §6.4 |
| 退出后进程不结束 / CPU 100% | 还在 `while is_InLoop: pass` | §1.2、§4.1 |
| Ctrl+C 没反应 | Windows 用了 `loop.add_signal_handler` | §2.7 |
| 计划任务每秒狂跑 | `timedelta.seconds` 对负值返回大正数 | §2.6 |
| `plugins/logs/` 多出来了 | `load_plugins` 没还原 cwd，loguru 相对 sink 落错地方 | §8.1 |
| 启动时 `config/snowluma.json` 没生成 | `init(False)` 或 `create=False` | §8.1 |
| 插件请求退出无效 | `from api import to_shutdown` 拿到的是副本 | §7.1 |
| 调试台 `reload` 之后 `DataForXPlugin/*.json` 全找不到、cwd 变成父目录 | reload 前没 `chdir("plugins")`（`t` 插件 import 时 `chdir("..")`） | §8.2 |
| 调试台 `reload` 后一个命令触发两次 | reload 前没清 `func_pool` / `notic_func_pool` / `request_func_pool` | §8.2 |
| `send $var` 抛 `JSONDecodeError` | 变量里存的不是事件 JSON | §8.2（已给友好提示） |

---

## 11. 收尾：真机联调与下一步

1. **先只读联调**：`python main.py` 连真实 SnowLuma，不触发任何命令，看日志是否正常
   （连接 → 生命周期 → 账号 → 协议端版本）。这一步能验证 90% 的集成问题。
2. **再功能验证**：用小号/测试群发 `echo hi`、`菜单`、@机器人 命令。
3. **反向通道**：在 SnowLuma 配 `wsClients` → `ws://127.0.0.1:6700/`，把 `mode` 设为 `reverse`
   或 `both`，验证反向也能收事件与发消息。
4. **稳定性**：连续运行 1 小时 + 中途重启 SnowLuma，确认无内存增长异常、无重复消息、能自愈。
5. **文档**：更新 README 的启动说明（去掉 go-cqhttp 段落）、把本教程与 M6/M7 一起提交。

**M8 之后可选做的**：

- `on_request` 的 approve 动作封装（`set_group_add_request` / `set_friend_add_request`）；
- 多账号（每个 `onebot_<uin>.json` 起一个 `OneBotConnection` + 独立 Bot 池）；
- 把 `tests/mock_snowluma.py` 的用例接进 CI（`pytest -W error::RuntimeWarning`）。

---

## 附录 A：`main.py` 改动索引（按当前 267 行行号）

| 现在 | 内容 | M8 处理 |
| --- | --- | --- |
| `:1-6` | 文件头注释 | 保留（可加一句"信息收发由 snowluma 包实现"） |
| `:7-14` | `re/sys/json/signal/asyncio/datetime`、`websocket`、`Thread` | 删 `websocket` / `Thread`；补 `inspect`、`from api import ...` 的新名字 |
| `:15-31` | 从 `api` 导入一堆 | 补：`RequestEvent`、`get_request_func_pool`、`require_connection`、`func_accepts_event`（已导）、`set_connection` |
| `:33-38` | 从 `script` 导入 `init/logger/load_plugins/check_whether_func` | `logger` 改成 `from log import logger`（别绕道 script） |
| `:42-141` | `message_preprocessor` | §6.1 整体替换为 `async def` |
| `:144-163` | `notice_preprocessor` | §6.2 |
| `:166-170` | `switch_type` | 删（`handle_event` 的 `match` 取代） |
| `:173` | `BOT_ID` | 删（用 `connection.self_id`） |
| `:176-200` | `handle()` | 换成 §5.1 的 `handle_event()`；需要兼容旧调用就再加一个 6 行 `handle(ws, message)` 壳 |
| `:203-208` | `start()`（WebSocketApp） | 删 |
| `:210-225` | `handle_scheduled_tasks()` + `isAlive` | §7.2 `scheduled_loop()` + `_due()` |
| `:228-232` | `signal_handler` | §4.1 的 `_on_signal` |
| `:235-267` | `__main__` 段 + `else` 段 | §4.1 的 `main_async()` / `main()` / `refresh_funcs()` |

**改完自查**：

```bash
grep -n "asyncio.run\|WebSocketApp\|is_InLoop\|GOCQWSURL\|go-cqhttp" main.py script.py   # 应为空
grep -n "switch_type\|BOT_ID" main.py                                                    # 应为空
python -m pytest tests/ -q -W error::RuntimeWarning                                      # 全绿
```

## 附录 B：`debug.py` 命令表（重写后）

| 命令 | 示例 | 说明 |
| --- | --- | --- |
| `build` | `build $msg echo 你好 -type=group -to=859874709 -format=array` | 存进变量（`$` 可省） |
| `send` | `send $msg` / `send $msg 3` | 投递 1 或 3 次 |
| `array` | `array 菜单` | 直接用 array 格式构造并投递 |
| `conn` | `conn` | 打印 `self_id` / `nickname` / `message_format` |
| `plugins` | `plugins` | 列出已加载插件 |
| `pool` | — | 列出等待任务（旧名 `get_waiting_pool` 已改名） |
| `reload` | — | 重载插件并 `refresh_funcs()` |
| `help` / `exit` | — | 帮助 / 退出 |

## 附录 C：健康启动日志长什么样（验收基线）

以真实 SnowLuma `1.14.19-node` 为例，`python main.py` 应该看到：

```
[INFO]  Hysial Bot is starting...
[INFO]  Checking config files...
[INFO]  SnowLuma 连接配置:
        配置来源: 默认值
        连接模式: both（正向 开 / 反向 开）
        正向 WebSocket: ws://127.0.0.1:3001/（token: 未配置）
        HTTP API: http://127.0.0.1:3000/（token: 未配置）
        反向 WebSocket: ws://0.0.0.0:6700/（token: 未配置）
        事件消息格式: auto，动作通道: auto
[SUCCESS] Succeeded to import plugin "Defalut"
...
[SUCCESS] 反向 WebSocket 已监听 ws://0.0.0.0:6700/（等待 SnowLuma 的 wsClients 接入）
[SUCCESS] 已连接 SnowLuma 正向 WebSocket: ws://127.0.0.1:3001/
[SUCCESS] SnowLuma 上报生命周期事件 connect，当前机器人账号 <uin>
[SUCCESS] SnowLuma 上报生命周期事件 enable，当前机器人账号 <uin>
[SUCCESS] Connected successfully! 当前机器人账号 <uin>（<昵称>）
[INFO]  协议端: SnowLuma 1.14.19-node / OneBot v11
[SUCCESS] 已经开始接收 SnowLuma 事件
```

收消息时：`收到群 <gid> 中来自 <名片/昵称>(<uid>) 的消息: ...` → `Checking priority 1...`
→ `触发 <插件函数名>` → `发送消息到群 <gid> 成功`。
