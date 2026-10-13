# M6 教程：事件层（`api/event.py` + `api/utils.py` + `api/on.py` 配套）

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。
>
> 本教程接你的实际进度写：M1（`snowluma/segment.py`）、M2（`config.py`）、M3（`tests/mock_snowluma.py`）、
> M4/M5（`connection.py`）、`htyping` 枚举映射、`api/event.py` 的 `SenderInfo` 都已完成。
> 下面只讲 **M6 剩下的部分**，并直接引用你现有代码的行号。

---

## TL;DR 动手顺序

| 步骤 | 做什么 | 文件 | 预计 |
| --- | --- | --- | --- |
| 0 | ~~放开注释掉的 import~~（**已完成**：`api/event.py` 顶部的 segment import 现在就是生效的）、修 `SenderInfo` 两处小问题 | `api/event.py:4-7, 53-65` | 10 min |
| 1 | 重写 `MessageEvent` 基类（M6 的核心） | `api/event.py:75-181` | 1~2 h |
| 2 | 三个子类改成继承 + 修 3 个 bug | `api/event.py:183-303` | 40 min |
| 3 | `NoticeEvent` 重写 + 新增 `RequestEvent` | `api/event.py:306-326` | 40 min |
| 4 | `api/utils.py`：连接 holder、执行封装、CQ 工具 | `api/utils.py` 全文件 | 1 h |
| 5 | 事件配套：`on_notice` 枚举兼容 + `on_request` | `api/on.py`、`plugins/manager.py` | 30 min |
| 6 | 写 `tests/test_event.py` / `test_utils.py`（`tests/test_segment.py` 已有 `def test_segment()`，**不用再收**） | `tests/` | 40 min |
| 7 | 回归：旧 `main.py` 仍能 import 运行，`test_connection.py` 不退化 | — | 20 min |

**验收门禁**：`pytest tests/ -q` 全绿 + 旧 `main.py` 还能跑 + 附录 A 的 6 个 payload 全部通过第 9 节清单。

---

## 0. 先修两个小问题 + 放开 import

### 0.1 `api/event.py` 顶部的 segment import（**已经放开**）

```python
# api/event.py 顶部现在就是这样，不要再改成注释；且不再有未使用的导入
from snowluma.segment import (
    MessageSegment,
    parse_cq_to_segments,
    segments_to_cq,
    normalize_segments,
)
```

- **为什么可以放心 import**：`snowluma/` 不反向依赖 `api/`（`connection.py` 只 import 了
  `config` / `segment` / `exception` 和第三方库），所以不存在循环导入。
- 只留用得到的名字：`segments_to_dicts`、`escape_cq` 在事件层用不上（渲染交给 `to_cq()`），
  留着反而会被 lint 挑出来。

### 0.2 `SenderInfo` 的两处小修（`api/event.py:53-65`）

| 位置 | 现在 | 问题 | 建议 |
| --- | --- | --- | --- |
| `display_name`（:53-59） | `return str(self.get("user_id"))` | `sender` 里没有 `user_id` 时返回字符串 `"None"` | `return str(self.get("user_id") or "")` |
| `to_dict`（:64-65） | `return self._raw` | 返回内部字典本体，调用方改一下就把事件改了 | `return dict(self._raw)` |

`display_name` 会在日志里被大量使用（`main.py` 的收消息日志），返回 `"None"` 会很难查。

---

## 1. 本阶段目标与边界

**产出**

1. `api/event.py`：`MessageEvent` 基类 + `GroupMessageEvent` / `PrivateMessageEvent` / `WaitingEvent` +
   `NoticeEvent` / `RequestEvent`，对外统一 **CQ 码字符串**，对内保留 **消息段视图**。
2. `api/utils.py`：连接 holder、`run_func` / `await_run_func`、`func_accepts_event`、CQ 快捷构造、
   `AnalyseCQCode` 重写、`set_device` 改走动作接口。
3. `api/on.py` + `plugins/manager.py`：`on_notice` 兼容 int/枚举、新增 `on_request`。

**明确不做**（留给后续阶段）

- 不改 `main.py`（M8）、不改 `api/bot.py` 的发送逻辑（M7）、不改 `debug.py` 的假连接（M8）。
- **原则：每一步结束时项目仍可运行。** 所以 M6 要保留旧的构造签名与 `To*` shim，
  这样现在这份 `main.py` 不用改就能继续跑（这是你的回归测试基线）。

---

## 2. 动手前必须想清楚的 4 个约束

### 2.1 双格式归一：对外 CQ 串，对内段视图

| 事件来源 | `get_message`（对外） | `get_message_segments`（对内） |
| --- | --- | --- |
| `array` 事件 | `segments_to_cq(段列表)` | `normalize_segments(list)` |
| `string` 事件 | **原样返回服务端字符串** | `parse_cq_to_segments(str)` |

**为什么 `string` 分支要"原样"而不是"解析再渲染"**——这是本阶段最重要的一个决策，理由有二：

1. 你 `segment.py` 的 `parse_cq_to_segments` 已经决定「畸形 CQ（`[CQ:at,qq=123` 未闭合）当纯文本」。如果解析后再渲染，
   这段文本里的 `[` 会被 `escape_cq` 变成 `&#91;`，**插件看到的内容就和服务端发的不一样了**。
2. 对**合规**的服务端，两条分支的结果本来就一致：array 分支渲染 text 段时也会转义
   （`MessageSegment.to_cq()` 里 `escape_cq`），所以 `get_message` 在两种来源下都处于"转义态"。

**由此推出一条匹配规则**（M8 会用到，现在先知道）：

- 要判断 **CQ 结构**（如 `"[CQ:at,qq=..." in msg`）→ 用 `get_message`
- 要匹配 **纯文本关键词**（如 `"菜单"`、`"echo"`）→ 用 `get_plain_text`（反转义后的文字段拼接）

两者对中文/ASCII 字母结果相同，只有文本里含 `& [ ] ,` 时才有差异。

### 2.2 谁拿到什么文本（响应器匹配语义，M8 按这个分发）

**由此再推出一条"谁拿到什么文本"的契约**（写响应器时最容易踩）：

| 消费方 | 拿到的字符串 | 说明 |
| --- | --- | --- |
| 粗筛 `script.check_whether_func` | `command_text = get_plain_text.lstrip()` | **去掉 @机器人 前缀的纯文本**；@ 段不产生 text，所以 @ 后面那个空格会变成前导空格，靠 `lstrip()` 抹掉 |
| `on_at` 响应器 | `get_message`（CQ 串） | **不参与粗筛**——它的判据是 CQ 串里的 `[CQ:at,qq=...]`，由 `main.py` 检测到 `[CQ:at,qq=self_id]` 时单独补进候选 |
| `custom` 匹配器 | `get_plain_text`（**原始，不去空白**） | 保留前导空格语义，匹配器自己决定要不要 strip |
| `on_command` / `on_keyword` | `command_text` | 精确相等 / `startswith` |
| `on_regex` | `command_text` | `re.search(func.regex, command_text)` |
| `on_waiting` | 两者都用 | `command_text == func.cmd` 或 `matcher(plain_text)` |

> 也就是说：**"@机器人 菜单" 能命中 `@on_command("菜单")`**（因为粗筛用的是 lstrip 过的纯文本），
> 而 `@on_at` 是否触发只看 CQ 串——这两件事互不干扰。

### 2.3 兼容性契约（谁在用这些属性）

> 下文的"旧 `main.py`"指 **M8 改写之前**的那一版 `main.py`。现行 `main.py` 已经重写
> （分发逻辑在 `handle_event` / `message_preprocessor`），不要再按"旧 `main.py` 的行号"去找代码。

你的插件（`plugins/Defalut`、`chatgpt`、`t`、`Xpic`、`XHuaLao`）和旧 `main.py` 依赖下面这些：

| 成员 | 必须返回 | 谁在用 |
| --- | --- | --- |
| `get_message` | **CQ 码字符串** | 所有插件、旧 `main.py` 的命令匹配 |
| `get_user_id` | **`str`**（不是 int） | `t`/`Xpic` 拼 `[CQ:at,qq={id}]`、`At(event.get_user_id)` |
| `get_user_name` | `sender.nickname` | `t` 的 `wealth` 记录、日志 |
| `get_user_group_name` | `sender.card`，无名片时 `""` | `Defalut` 日志、`XHuaLao` 统计 |
| `get_group_id` | `str` 或 `None` | 几乎所有发送处 |
| `get_message_type` | `"group"` / `"private"` | `Defalut` 的 echo、`服务器状态` |
| `get_message_id` | 原始值（`reply()` 要用） | `chatgpt` 的 `event.reply(...)` |
| `reply(content)` | `f"[CQ:reply,id={message_id}] {content}"` | `chatgpt`（**注意保留 `] ` 后的空格**） |
| `set_message(value)` | 就地更新，且 `get_message_segments` 同步 | `Defalut` 的 `custom` 响应器、旧 `main.py` 的 `on_regex` |

> `get_user_id` 返回 `str` 是历史包袱，但它让所有插件的 f-string 拼接都能用。**不要在 M6 改成 int**，
> 要改也是在 M7/M8 一次性全改（含插件），否则会静默产生 `qq=169699201` vs `qq=169699201.0` 之类的坑。

### 2.4 依赖方向

```
api/event.py  →  snowluma.segment, htyping        （不 import api.bot / api.utils）
api/utils.py  →  snowluma.exception, log, pool, plugins.manager, api.on, api.exception
api/bot.py    →  api.utils（拿连接 holder）, api.event
```

连接 holder 放 `api/utils.py` 而不是 `api/bot.py`：`api/bot.py` 要 import `api/utils.py` 的
`CreateOnWaitingTask`，如果 holder 放在 `bot.py`，`utils.py` 想用它就得反向 import，形成环。

### 2.5 M6 结束时必须仍然成立的三件事

1. `import main` 不报错；
2. `MessageEvent(BOT_ID, payload)` + `.ToGroupMessageEvent()` / `.ToPrivateMessageEvent()` 仍可用；
3. `NoticeEvent.model_validate(payload)` 仍可用（现行 `main.handle_event` 就是这么调用的）。

---

## 3. 任务 A：重写 `MessageEvent` 基类（核心）

对应区间：`api/event.py:75-181`。

### A.1 构造契约

```python
class MessageEvent:
    def __init__(self, self_id: int | None = None, payload: dict | None = None) -> None: ...
    @classmethod
    def from_payload(cls, payload: dict) -> "MessageEvent": ...
```

- **保持 `(self_id, payload)` 的位置顺序**（旧 `main.py:190` 是 `MessageEvent(BOT_ID, _)`）。
  想要 `payload` 在前的 NoneBot 风格，请放到 M8 和 `main.py` 一起改，别在这一步破坏可运行性。
- `from_payload` 是 M8 的入口：按 `payload["message_type"]` 返回 `GroupMessageEvent` /
  `PrivateMessageEvent`，其它（含 `message_sent` 且无 `message_type` 的极端情况）返回基类。
- `self_id` 传 `None` 时从 `payload.get("self_id")` 兜底。

### A.2 ⚠️ 第一个陷阱：不要提前 `return`

旧 `MessageEvent.__init__` 开头有过这么一段：

```python
if msg["post_type"] != "message": return      # ← 会把对象留在"半初始化"状态
```

一旦提前 return，后面所有 `event.get_xxx` 拿到的都是**类属性默认值**（`MessageEvent` 类体上那些
`_self_id` / `_message_type` …），现象是"日志里事件字段全是 None"，极难排查。
**现行实现已经不判断 `post_type`，只管取字段**；需要区分 `message` / `message_sent`
就看 `_post_type` 字段（`MessageEvent.get_post_type` / `is_self_message`）。

### A.3 逐字段取值表

用 `payload.get(...)` 取，**不要用 `payload[...]`**（私聊没有 `group_id`、通知没有 `sender`，
方括号取值就是 `KeyError` 的来源）：

| 内部字段 | payload 来源 | 默认 | 备注 |
| --- | --- | --- | --- |
| `_self_id` | 参数 `self_id` → `payload.get("self_id")` | `None` | 转 `int`，失败给 `None` |
| `_post_type` | `payload.get("post_type")` | `"message"` | `message_sent` 也走这里 |
| `_time` | `payload.get("time")` | `None` | 转 `int` |
| `_message_type` | `payload.get("message_type")` | `None` | 子类里强制覆盖 |
| `_sub_type` | `payload.get("sub_type")` | `None` | `normal`/`friend`/`group`/`other` |
| `_message_id` | `payload.get("message_id")` | `None` | `reply()` 依赖 |
| `_font` | `payload.get("font")` | `None` | |
| `_group_id` | `payload.get("group_id")` | `None` | **私聊可能没有** |
| `_target_id` | `payload.get("target_id")` | `None` | 部分实现会用 |
| `_anonymous` | `payload.get("anonymous")` | `None` | |
| `_sender` | `SenderInfo(payload.get("sender"))` | 空 `SenderInfo` | |
| `_user_id` | `sender.user_id` → `payload.get("user_id")` | `None` | 最后 `str(...)` |
| `_segments`/`_message`/`_raw_message` | 见 A.4 | — | |

### A.4 消息归一：三分支

```python
raw_message = payload.get("raw_message")
message = payload.get("message")
if message is None:                      # 某些实现只在 raw_message 里给消息
    message = raw_message if raw_message is not None else ""

if isinstance(message, str):             # string 格式
    self._message = message                                  # 原样保留（见 2.1）
    self._segments = parse_cq_to_segments(message)
else:                                    # array 格式（list / 单个 dict / MessageSegment）
    self._segments = normalize_segments(message)
    self._message = segments_to_cq(self._segments)

self._raw_message = raw_message if isinstance(raw_message, str) else segments_to_cq(self._segments)
```

注意你 `segment.py` 里 `parse_cq_to_segments` / `segments_to_cq` 的行为：`parse_cq_to_segments("") == []`，
`segments_to_cq([]) == ""` —— 两条分支对空消息结果一致，不需要额外兜底。

### A.5 属性/方法清单

**只读属性**（保持旧名，语义见 2.2 表格）：

```
get_time, get_self_id, get_post_type, get_sub_type, get_font, get_sender,
get_user_id, get_user_name, get_user_group_name, get_user_role,
get_group_id, get_target_id, get_message_type,
get_message_id, get_message, get_message_segments, get_raw_message,
get_plain_text, get_display_name,
is_group, is_private, is_self_message
```

**方法**：

```
set_message(value)          # str 或段列表，两种都要能存；同步刷新 _segments / _message
set_message_segments(list)  # 可选，语义同 set_message(段列表)
set_raw_message(value)      # 保留旧 API
add? 无
reply(content) -> str       # f"[CQ:reply,id={self._message_id}] {content}"
get_payload() -> dict       # 返回 payload 副本（供 WaitingEvent 复制）
ToGroupMessageEvent() / ToPrivateMessageEvent()   # 兼容 shim，见 A.7
```

`get_plain_text` 实现就是：`"".join(seg.get("text", "") for seg in self._segments if seg.type == "text")`。

`is_self_message` 的判断是 `self._post_type == "message_sent"`。
`get_display_name` 直接委托 `self._sender.display_name`。

### A.6 `set_message` 的回写语义（旧代码这里是残的，**现已同步**）

旧 `set_message` 只改了 `_message`，`_segments` 不跟着变。M8 里 `on_regex` 分支会
`event.set_message(match.group(1))`，如果 `_segments` 不同步，后面任何读 `get_message_segments` /
`get_plain_text` 的插件就会看到旧消息。**现行的 `MessageEvent.set_message` 两条分支都会同步刷新**：

```python
def set_message(self, value):
    if isinstance(value, str):
        self._message = value
        self._segments = parse_cq_to_segments(value)
    else:
        self._segments = normalize_segments(value)
        self._message = segments_to_cq(self._segments)
```

### A.7 兼容 shim（别再用"挑字段复制"的写法）

旧 `ToGroupMessageEvent` 是 `GroupMessageEvent(self_id, {"post_type": None})`
然后手工搬 7 个字段 —— 一旦基类字段增加（`sub_type`/`font`/`sender`…）就会丢。
**现行实现已经改成重包 `_payload`**（见 `api/event.py` 的 `MessageEvent.ToGroupMessageEvent`）：

```python
def ToGroupMessageEvent(self) -> "GroupMessageEvent":
    return GroupMessageEvent(self._self_id, self._payload)
```

这样老 `main.py` 的调用链完全不变，且不再丢字段。同理 `ToPrivateMessageEvent`。

### A.8 自测点（先看红，再改绿）

```python
# 红：旧代码直接构造 PrivateMessageEvent 会 KeyError: 'group_id'
PrivateMessageEvent(999, PRIVATE)          # PRIVATE 见附录 A-3
```

改完应满足：

| # | 断言 |
| --- | --- |
| A-1 | `MessageEvent(999, GROUP_ARRAY).get_message == "echo hi[CQ:at,qq=3592797817]"` |
| A-2 | 同上的 `get_message_segments` 长度为 2，`[0].type == "text"`、`[1].type == "at"` |
| A-3 | `get_plain_text` 只含文字（不含 at 段） |
| A-4 | `get_user_id == "169699201"`（`str`）、`get_user_name == "雨弈"`、`get_user_group_name == "群名片"` |
| A-5 | `set_message("[CQ:face,id=1]")` 后 `get_message_segments[0].type == "face"`，且 `get_message` 同步 |
| A-6 | `reply("x") == "[CQ:reply,id=12345] x"` |
| A-7 | `from_payload(GROUP_ARRAY)` 返回 `GroupMessageEvent`；`from_payload(PRIVATE)` 返回 `PrivateMessageEvent` |

---

## 4. 任务 B：`GroupMessageEvent` / `PrivateMessageEvent` 改为继承（**已完成**）

对应区间：`api/event.py:183-237`（群）、`:239-284`（私聊）。

### B.1 三个必须修的 bug（**均已修复**）

| 位置 | 旧现状 | 后果 | 改法（现行代码已是改后的样子） |
| --- | --- | --- | --- |
| `PrivateMessageEvent` :249 | `self._group_id = str(msg["group_id"])` | 私聊事件**没有** `group_id` → `KeyError`，私聊功能整条链路挂掉 | `payload.get("group_id")`，再 `str(...)` 或 `None` |
| `PrivateMessageEvent` :250 | `self._message_type = "group"` | 复制粘贴 bug，私聊被判成群聊，`Defalut` 的 `event.get_message_type` 分流全错 | `"private"` |
| `GroupMessageEvent` :185 / `PrivateMessageEvent` :241 | `if msg["post_type"] == None: return` | 同 A.2 的半初始化陷阱 | 删掉 |

改成继承后，两个子类只需：

```python
class GroupMessageEvent(MessageEvent):
    def __init__(self, self_id=None, payload=None):
        super().__init__(self_id, payload)
        self._message_type = "group"      # 强制，不信 payload
```

### B.2 私聊的 `group_id` 什么时候有值

OneBot v11 里私聊的 `sub_type` 可能是 `friend` / `group` / `other`。当 `sub_type == "group"`
（群临时会话）时，payload **会带 `group_id`**。所以：

- `PrivateMessageEvent` 要**保留** `group_id`（有则填，无则 `None`），不要硬写成 `None`；
- `get_group_id` 返回 `str` 或 `None`；
- `is_group` 仍然是 `False`（`is_group` 看的是 `message_type`，不是有没有 `group_id`）。

### B.3 自测点

| # | 断言 |
| --- | --- |
| B-1 | `PrivateMessageEvent(999, PRIVATE)` 不抛异常；`get_message_type == "private"`；`get_group_id is None` |
| B-2 | `PrivateMessageEvent(999, PRIVATE_TEMP)`（`sub_type="group"` 且带 `group_id`）→ `get_group_id == "123456"`，`get_message_type == "private"` |
| B-3 | `isinstance(GroupMessageEvent(...), MessageEvent)` 为 `True`（改继承后；旧代码是 `False`） |
| B-4 | 插件式注解匹配：`isinstance(ge, GroupMessageEvent | PrivateMessageEvent)` 为 `True`（Python 3.10+ 支持 UnionType 的 isinstance） |

---

## 5. 任务 C：`WaitingEvent` 修正（**已完成**）

对应区间：`api/event.py` 的 `WaitingEvent`。下面 C.1 贴的是**旧**代码（"红"状态），
现行实现已经按 C.2 落地。

### C.1 必须修：群聊里 `group_id` / `user_id` 错位（旧 `:295`）

```python
if self._message_type == "group":
    self._group_id = event.get_user_id      # ← 旧代码：把发言人当成了群号（已删）
```

旧 `main.py:71` 的等待任务匹配是：

```python
if event.get_group_id == task.group_id and event.get_user_id == task.user_id:
```

而 `task.group_id / task.user_id` 是在注册时用**原事件**的 `get_group_id / get_user_id` 存的
（`main.py:131`）。所以 `WaitingEvent` 里的 `group_id` 一旦错位成用户号，
**群聊里的等待任务会永远匹配不上**（用户会在群里发 `input` 却毫无反应）。

### C.2 推荐实现：整份复制，而不是挑字段

```python
class WaitingEvent(MessageEvent):
    input_value: str | None = None

    def __init__(self, event: MessageEvent) -> None:
        super().__init__(event.get_self_id, event.get_payload())   # 全字段复制（注意：get_payload 是方法，要带括号）
        self._message = event.get_message                          # property，别加括号
        self._segments = event.get_message_segments                # 返回的是副本，正好归本事件所有
        self.input_value = None
```

这样 `get_message_id`（`reply()` 要用）、`get_user_id`、`get_group_id`、`_sender` 全都对。
保留 `add_value(name, value)`（`self.__dict__[name] = value`）不动，插件在用。

### C.3 自测点

```python
# 红（旧代码）：ge = GroupMessageEvent(999, GROUP_ARRAY); we = WaitingEvent(ge)
#   we.get_group_id == "169699201"   ← 错位
#   we.get_user_id  is None          ← 丢了
# 绿（现行实现）：两者都与 ge 一致
```

| # | 断言 |
| --- | --- |
| C-1 | `we.get_group_id == ge.get_group_id == "123456"` |
| C-2 | `we.get_user_id == ge.get_user_id == "169699201"` |
| C-3 | `we.get_message_id == ge.get_message_id`（`reply()` 才可用） |
| C-4 | `we.input_value is None`（未赋值前），`we.add_value("x", 1)` 后 `we.x == 1` |

---

## 6. 任务 D：`NoticeEvent` 重写 + 新增 `RequestEvent`（**已完成**）

对应区间：`api/event.py` 的 `NoticeEvent` / `RequestEvent`。

### D.1 两个必须修的 bug（**均已修复**）

| 位置 | 旧现状 | 后果 | 改法（现行代码已是改后的样子） |
| --- | --- | --- | --- |
| `NoticeEvent` :319-326 | `{"group_upload": 1, ...}[self.notice_type]` | 出现 `group_recall`/`friend_recall`/`notify` 等未列类型就 `KeyError`，直接把分发线程打挂 | 现行用 `htyping/types.py` 的 `NOTICE_TYPE_IDS.get(...)`，未知返回 `None` |
| `NoticeEvent` :307-309 | `time/self_id/post_type` 必填 | 降级或精简版 payload 会 `ValidationError` | 全部改 `Optional`，`post_type` 给默认值 `"notice"` |

> 现行实现里 `notice_type` / `request_type` 也是 `str | None = None`（不是必填）：
> 判别字段缺失时宁可丢掉类型判定，也不要把整条事件炸掉。

`notice_type` 是判别字段，**保留必填**（缺了它就是畸形事件，让它报错更好）。

### D.2 pydantic v2 的写法

```python
from pydantic import BaseModel, ConfigDict

class NoticeEvent(BaseModel):
    model_config = ConfigDict(extra="allow")     # 协议端新增字段不丢、不炸
    ...
```

- `extra="allow"`：SnowLuma 动作很多、字段会随版本增加（如 `honor_type`、`target_id`），
  默认 `ignore` 会**静默丢字段**，`allow` 能保留并在需要时读到。
- 调用侧仍用 `NoticeEvent.model_validate(payload)`（M8 的 `handle_event` 就是这么调用的，pydantic v2 正确用法）。

### D.3 字段清单

```python
class NoticeEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    post_type: str = "notice"
    notice_type: str | None = None        # 判别字段；协议端没给也别把整条事件丢掉
    time: int | None = None
    self_id: int | None = None
    sub_type: str | None = None
    group_id: int | None = None
    user_id: int | None = None
    operator_id: int | None = None
    target_id: int | None = None
    message_id: int | None = None
    duration: int | None = None
    file: dict | None = None
    honor_type: str | None = None
    anonymous: Any = None
```

便捷 getter（对齐消息事件，统一 `str` 返回，方便插件 f-string 拼接）：

```python
@property
def get_notice_int_type(self) -> int | None: return NOTICE_TYPE_IDS.get(self.notice_type)
@property
def get_group_id(self) -> str | None: ...
@property
def get_user_id(self) -> str | None: ...
@property
def get_operator_id(self) -> str | None: ...
```

> `NoticeEvent` 保持 pydantic 模型的好处：`event.group_id` / `event.user_id` 这种**属性直读**
> 继续可用（`Defalut` 的入群欢迎就是这么写的），getter 只是给需要 `str` 的地方补台。

### D.4 `RequestEvent`（新文件内容）

```python
class RequestEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    post_type: str = "request"
    request_type: str | None = None       # "friend" / "group"；缺字段时别丢整条事件
    time: int | None = None
    self_id: int | None = None
    sub_type: str | None = None           # "add" / "invite"
    comment: str | None = None
    flag: str | None = None
    user_id: int | None = None
    group_id: int | None = None

    @property
    def get_request_int_type(self) -> int | None: return REQUEST_TYPE_IDS.get(self.request_type)
    @property
    def get_comment(self) -> str: return self.comment or ""
```

### D.5 自测点

| # | 断言 |
| --- | --- |
| D-1 | `NoticeEvent.model_validate({"notice_type": "group_recall", ...}).get_notice_int_type == 7`（**旧代码这里是 KeyError**） |
| D-2 | `NoticeEvent.model_validate({"notice_type": "not_implemented_yet"}).get_notice_int_type is None` |
| D-3 | 带额外字段（`honor_type="performer"`）能 validate，且 `event.honor_type == "performer"` |
| D-4 | 最小 payload `{"notice_type": "friend_add"}`（没有 time/self_id）能 validate |
| D-5 | `RequestEvent.model_validate({"request_type": "group", "comment": "求进群", ...}).get_request_int_type == 2` |
| D-6 | `RequestEvent.model_validate({"request_type": "group"}).get_comment == ""` |

---

## 7. 任务 E：`api/utils.py`

> 本节讲的 E.1~E.6 **都已落地**；下面凡写"现状/旧实现"的地方，都是在指改动前的代码
> （放这里是为了说清楚"为什么要这么写"），核对时请以 `api/utils.py` 的现行实现为准。

### E.1 连接 holder（放这里的理由见 2.3）

```python
_connection: "OneBotConnection | None" = None

def set_connection(connection) -> None: ...       # main.py 启动时登记（M8）
def get_connection(): ...                          # 返回当前连接或 None（debug 假连接也走这里）
def require_connection(): ...                      # 没有连接时 raise ConnectionUnavailable
```

`require_connection` 里 `from snowluma.exception import ConnectionUnavailable` 可以放模块顶层
（`snowluma` 不依赖 `api`）。加它是因为 M7 的 `Bot.call_api` 需要在"没连接"时报错而不是静默成功。

### E.2 `run_func` / `await_run_func` 重写（现行实现见 `api/utils.py` 的 `run_func` / `await_run_func`）

旧实现有 5 个问题，逐个说清（**都已在现行代码里修掉**）：

| 问题 | 旧位置 | 说明 | 现行状态 |
| --- | --- | --- | --- |
| `res` 未绑定就 `return res` | `:36` | `func(*args)` 抛异常时 `res` 从未赋值 → `UnboundLocalError` 盖掉真实异常 | 已不在 `try` 外裸用 `res`；异常路径直接 `return -1` |
| `await func(*args)` | `:47` | `FuncMeta.__call__` 对**同步**插件函数返回 `None` → `await None` 抛 `TypeError`。修法：**先调用，再判断是不是 awaitable** | 已修：`res = func(*args)` 之后才 `inspect.isawaitable(res)` |
| 只 `except Exception` | `:52` | `FinishException` 继承自 `BaseException`（见 `api/exception.py` 的 `FinishException`），`except Exception` **抓不到它**，必须单独放在最前面 | 已修：`except FinishException` 排在最前 |
| `@logger.catch` 装饰 | `:14, :39` | 内部已经显式处理异常，再套一层会把 traceback 藏起来 | **仍保留**（无害，属风格取舍；想去掉随时可以） |
| `print(...)` | `:49` | 调试残留，走 `logger` | 已修：全部走 `logger` |

推荐骨架（**先调用后判 awaitable** 是关键）：

```python
async def await_run_func(func, *args, isDebug=False):
    try:
        result = func(*args)                 # FuncMeta 或普通函数都可以
    except FinishException:
        ...日志...
        return None
    except Exception as exc:
        logger.exception(exc)
        return -1
    if inspect.isawaitable(result):          # 只有异步插件才 await
        try:
            result = await result
        except FinishException:
            ...日志...
            return None
        except asyncio.CancelledError:
            raise                            # 优雅退出（M8）必须能穿透
        except Exception as exc:
            logger.exception(exc)
            return -1
    return result
```

`run_func`（同步上下文：`on_startup` 的同步函数、计划任务的同步函数）同理，区别是：
若结果是 awaitable 且**当前没有事件循环** → `asyncio.run(协程)`；若**已经在循环里** →
`asyncio.ensure_future(...)` 并挂一个 done callback 记异常（不要阻塞循环）。

返回值语义建议统一为「返回函数结果，异常返回 `-1`，`FinishException` 返回 `None`」——
旧签名写的是 `-> int` 但实际 `return res`，M8 的分发层不依赖返回值，统一一下更省心。

### E.3 `func_accepts_event`（新函数，替代旧 `main.py` 里裸取注解的写法）

旧写法 `func._func.__annotations__["event"]` 有三个坑：参数名不叫 `event` → `KeyError`；
插件写了 `from __future__ import annotations` → 注解是**字符串**，`isinstance` 抛 `TypeError`；
注解写成 `list[int]` 之类的下标泛型 → 同样 `TypeError`。

```python
def func_accepts_event(func, event) -> bool:
    target = getattr(func, "_func", func)
    annotation = getattr(target, "__annotations__", {}).get("event")
    if annotation is None:
        return True                      # 没标注解 = 都能收
    try:
        return isinstance(event, annotation)
    except TypeError:                    # 字符串注解 / 不可用于 isinstance 的注解
        return True                      # 保守放行，交给函数自己处理
```

⚠️ 注意 `FuncMeta` 是**可调用对象**，注解挂在 `func._func` 上而不是 `FuncMeta` 上。

### E.4 CQ 快捷构造（现行实现见 `api/utils.py` 的 `At` / `AtAll` / `Reply` / `ImageSegment` 等）

**已修**：`ImageSegment` 早期生成 `[CQ:img,...]`，而 OneBot 的段名是 **`image`** ——
那时任何用到 `ImageSegment()` 的插件都会静默发不出图（协议端只当普通文本）。
现行实现已经统一走 `MessageSegment(...).to_cq()`：

```python
def At(qq):          return MessageSegment("at", {"qq": str(qq)}).to_cq()
def AtAll():         return "[CQ:at,qq=all]"
def Reply(mid):      return MessageSegment("reply", {"id": str(mid)}).to_cq()
def ImageSegment(f): return MessageSegment("image", {"file": f}).to_cq()     # ← 修掉 [CQ:img]
def FaceSegment(i):  return MessageSegment("face", {"id": str(i)}).to_cq()
def RecordSegment(f):return MessageSegment("record", {"file": f}).to_cq()
def VideoSegment(f): return MessageSegment("video", {"file": f}).to_cq()
def FileSegment(f):  return MessageSegment("file", {"file": f}).to_cq()
def Text(content):   return escape_cq(str(content))
def Message(value):  return normalize_cq(value)
```

手拼 `f"[CQ:image,file={url}]"` 在 URL 含 `,` 或 `&` 时会解析错位；`to_cq()` 会正确处理
（`tests/test_segment.py` 的 `test_segment()` 已经覆盖了 `cache=false` 这类布尔渲染）。

`snowluma/segment.py` 的 `MessageSegment` 目前只有 `from_cq()` / `from_dict()` / `text()` / `at()`
四个构造入口，**没有** `image()` / `reply()` / `face()` 之类的类方法。要用就先写
`MessageSegment("image", {"file": f})`（这就是 `api/utils.py` 里 `ImageSegment` 的写法）。

### E.5 `AnalyseCQCode` 重写（现行实现见 `api/utils.py` 的 `AnalyseCQCode`）

旧的 `AnalyseCQCode` 手写状态机有已知问题：`[CQ:at,qq=123]` 后面**紧跟文本**时不会产出 text 项、
`prop_v` 用 `"".join(stack[:-1])` 会在多参数时错位、`type_` 初值是 `list` 却按字符串用。
**现行实现已经不复用那套状态机**，直接复用写对的解析器，并**保持旧的返回形状**（老插件可能依赖）：

```python
def AnalyseCQCode(cq: str) -> list[dict]:
    result = []
    for seg in parse_cq_to_segments(cq):
        if seg.type == "text":
            result.append({"type": "text", "content": seg.get("text", "")})
        else:
            result.append({"type": seg.type, **{k: str(v) for k, v in seg.data.items()}})
    return result
```

即 `"hi[CQ:at,qq=123]"` → `[{"type":"text","content":"hi"}, {"type":"at","qq":"123"}]`（与旧输出兼容）。

### E.6 `set_device` 改走动作接口（现行实现见 `api/utils.py` 的 `set_device`）

旧实现是 `httpx.post("http://127.0.0.1:9920/send_msg", ...)` —— 端口是 go-cqhttp 时代的，
端点是 `send_msg`，参数是 `model/model_show`，**三样都不对**。**现行实现已经改走动作接口**：

```python
async def set_device(name: str) -> bool:
    try:
        await require_connection().call_action("_set_model_show", model=name, model_show=name)
    except Exception as exc:
        logger.warning(f"设置机型 {name} 失败: {exc}")
        return False
    logger.success(f"设置机型 {name} 成功!")
    return True
```

签名保持 `async def set_device(name) -> bool`，所以旧调用点不用改。`httpx` 这个 import 在
`api/utils.py` 里已经不需要了（连接层自己持有 `httpx.AsyncClient`）。

### E.7 保持不动的部分

`getExpectedFuncs`、`CreateOnWaitingTask`、`shutdown` / `to_shutdown` 都还有用
（M7 的 `Bot.input_value` 会调 `CreateOnWaitingTask`，M8 的退出监听读 `is_shutdown_requested()`），
**不要顺手删**。

> `to_shutdown` 这个模块级 `bool` 现在只作为**内部状态**保留：插件侧请用
> `api.is_shutdown_requested()` 判断是否有人请求退出，别 `from api import to_shutdown`
> （bool 不可变，那样拿到的永远是导入那一刻的副本，恒为 `False`）。详见 M8 教程。

### E.8 自测点

| # | 断言 |
| --- | --- |
| E-1 | `await_run_func(同步插件函数, bot, event)` 不抛 `TypeError` |
| E-2 | 插件里 `await bot.finish(...)` 抛出的 `FinishException` 被吞掉，不冒泡到调用方 |
| E-3 | 插件抛 `ValueError` 时不冒泡，且日志里有 traceback（返回 `-1`） |
| E-4 | `func_accepts_event(注解缺失的函数, event) is True` |
| E-5 | 注解为 `GroupMessageEvent \| PrivateMessageEvent` 时，群事件 → `True` |
| E-6 | 插件用字符串注解（`from __future__ import annotations`）时不抛 `TypeError` |
| E-7 | `ImageSegment("a,b.png") == "[CQ:image,file=a&#44;b.png]"` |
| E-8 | `AnalyseCQCode("hi[CQ:at,qq=123]")` 输出形状与旧实现一致（text 用 `content` 键） |
| E-9 | `get_connection() is None` 时 `await set_device("x") is False`（不抛异常） |

---

## 8. 任务 F（收尾）：`api/on.py` + `plugins/manager.py` 事件配套

### F.1 为什么现在做

M8 的 `main.py` 要分发 `request` 事件，而分发靠 `FuncMeta.notice_type / request_type` 与
事件上的 `get_notice_int_type / get_request_int_type` 比较。M6 把事件侧改好了，
响应器注册侧（`api/on.py`）如果不跟上，就会"事件能解析、但没有函数能注册进来"。

> 任务 F 是**可选的收尾**：它在 [m4 教程](m4-forward-ws-tutorial.md) 说的"M6 = 事件模型"范围之外。
> 如果你想严格按里程碑走，F 挪到 M7 开头做完全没问题——它不阻塞第 9 节的任何断言，
> 只影响 M8 分发 `request` 事件时能不能注册到响应器。

### F.2 `on_notice` 需要兼容三种传法

`plugins/Defalut/main.py:107` 传的是枚举（`NoticeEvents.GroupIncrease`），
但 M6 之后 `get_notice_int_type` 可能返回 `None`，所以要统一：

```python
def _type_value(type_): return type_.value if isinstance(type_, Enum) else type_

def on_notice(notice_type, block=False, priority=1):
    ... FuncMeta(func, "on_notice", block, priority, notice_type=_type_value(notice_type)) ...
```

### F.3 新增 `on_request` + 请求池

```python
request_func_pool: NoticeFuncPool = NoticeFuncPool()      # 复用 pool 里现成的类
def get_request_func_pool() -> NoticeFuncPool: return request_func_pool

def on_request(request_type, block=False, priority=1):
    ... FuncMeta(func, "on_request", block, priority, request_type=_type_value(request_type)) ...
```

`plugins/manager.py` 的 `FuncMeta` 要能存这个字段（否则 `func.request_type` 是 `AttributeError`）：

```python
# FuncMeta 类体
request_type: Optional[Union[int, str]]
# __init__ 里
self.request_type = kwargs.get("request_type")
```

（`FuncMeta.__init__` 已有 `**kwargs`，`on_request` 传进来就能收到；`NoticeFuncPool` 直接复用即可。）

### F.4 自测点

| # | 断言 |
| --- | --- |
| F-1 | `@on_notice(NoticeEvents.GroupIncrease)` 与 `@on_notice(4)` 注册出的 `func.notice_type` 都是 `4` |
| F-2 | `@on_request(RequestEvents.Group)` 注册后 `func.request_type == 2`，且出现在 `get_request_func_pool()` 里 |
| F-3 | 用 `NoticeEvent.model_validate({"notice_type":"group_increase"})` 时 `event.get_notice_int_type == func.notice_type` |

---

## 9. M6 验收清单（建议放 `tests/test_event.py`）

事件层没有 IO，用**纯 payload 单测**即可，**不需要起 mock 协议端**。但 payload **优先复用你
`tests/mock_snowluma.py` 里已经写好的构造器**（`group_message` / `private_message` / `notice` /
`group_request` / `_seg`），别再造一份——`private_message()` 的 docstring 里已经写明它是专门给
"不炸"用例准备的（见 `tests/mock_snowluma.py` 的 `private_message`）。

```python
# tests/test_event.py
from mock_snowluma import (       # pytest 会把 tests/ 加进 sys.path（见 test_connection.py 顶部）
    CaseRunner, _seg, group_message, group_request, notice, private_message,
)
from api.event import (
    MessageEvent, GroupMessageEvent, PrivateMessageEvent, WaitingEvent,
    NoticeEvent, RequestEvent,
)

SELF_ID = 999


def test_message_array():
    runner = CaseRunner()
    ev = MessageEvent(SELF_ID, group_message(
        "echo hi",
        segments=[_seg("text", text="echo hi"), _seg("at", qq="3592797817")],
    ))
    runner.check("A-1 get_message 是 CQ 串",
                 ev.get_message == "echo hi[CQ:at,qq=3592797817]", repr(ev.get_message))
    runner.check("A-2 段视图", [s.type for s in ev.get_message_segments] == ["text", "at"])
    runner.check("A-4 get_user_id 是 str", ev.get_user_id == "169699201", repr(ev.get_user_id))
    assert runner.finish() == 0          # 与 tests/test_connection.py 的收尾方式一致


def test_private_without_group_id():
    runner = CaseRunner()
    ev = PrivateMessageEvent(SELF_ID, private_message("hi"))   # 这条没有 group_id
    runner.check("B-1 私聊不炸", ev.get_group_id is None)
    runner.check("B-1 message_type 正确", ev.get_message_type == "private")
    assert runner.finish() == 0
```

`CaseRunner.finish()` 全过返回 0、有失败返回 1（见 `tests/mock_snowluma.py` 的 `CaseRunner.finish`），
所以 `assert runner.finish() == 0` 就等于 pytest 的判定——和 `tests/test_connection.py` 完全同构。
事件层是同步的，**不需要 asyncio**。

| 组 | 编号 | 覆盖 |
| --- | --- | --- |
| 消息（array） | A-1 ~ A-7 | CQ 渲染、段视图、属性兼容、`set_message` 回写、`reply`、`from_payload` |
| 消息（string） | S-1 ~ S-3 | `get_message` **原样**、畸形 CQ 不被转义、`get_plain_text` 已反转义 |
| 子类 | B-1 ~ B-4 | 私聊不抛异常、临时会话保留 `group_id`、`isinstance` 关系 |
| 等待事件 | C-1 ~ C-4 | `group_id`/`user_id`/`message_id` 正确复制 |
| 通知 | D-1 ~ D-4 | 未知类型返回 `None`、额外字段保留、最小 payload 可构造 |
| 请求 | D-5 ~ D-6 | 类型映射、`comment` 兜底 |
| 执行封装 | E-1 ~ E-6 | 同步/异步/`FinishException`/注解健壮性 |
| CQ 工具 | E-7 ~ E-9 | `ImageSegment` 修好、`AnalyseCQCode` 形状、`set_device` 无连接不炸 |
| 响应器 | F-1 ~ F-3 | 枚举归一、请求池 |

**回归门禁**（M6 结束必须过）：

```bash
pytest tests/ -q                      # 全绿
python -c "import main"               # 旧 main.py 仍可 import
pytest tests/test_connection.py -q    # M4/M5 不因事件层改动而退化
```

> **关于 `tests/test.py`（更新结论）**：这个文件**已经被删除**了。原先的实测结论是
> pytest 默认只收集 `test_*.py` / `*_test.py`，而它叫 `test.py`，所以 `pytest tests/`
> **根本不会收集它**，它不会让全量测试变红。既然已经删掉，这条就不用再管了。

---

## 10. 常见错误排查表

> 下面第 4~11 行描述的都是 **M6 动工前**的旧代码症状；现行实现已经全部修好，
> 这张表留着是为了"下次看到同样症状时知道往哪查"。

| 现象 | 原因 | 改法 |
| --- | --- | --- |
| `event.get_message` 返回 `list` | array 分支忘了 `segments_to_cq` | 按 A.4 两条分支都要产出 `_message` |
| 插件看到的文本里 `[` 变成了 `&#91;` | string 分支做了"解析再渲染" | string 分支**原样保留**（2.1） |
| `KeyError: 'group_id'` | 用了 `payload["group_id"]` | 全量改 `.get(...)` |
| 私聊被当成群聊 | 旧 `PrivateMessageEvent` 里 `_message_type = "group"` | 改 `"private"`（见 `api/event.py` 的 `PrivateMessageEvent`） |
| 日志里事件字段全是 `None` | 旧构造里提前 `return` | 删掉提前 return |
| 群里发消息但等待任务不触发 | 旧 `WaitingEvent` 的 `group_id` 错位 | 整份复制 payload（见 `api/event.py` 的 `WaitingEvent`） |
| `TypeError: object NoneType can't be used in 'await'` | `await func()` 先 await 后判断 | 先调用、再 `inspect.isawaitable` |
| `FinishException` 冒泡到分发层 | 只 `except Exception`（它是 `BaseException` 子类，会漏网） | `except FinishException` 放在最前 |
| `KeyError: 'group_recall'` | 通知类型表不全会用 `[...]` 索引 | 用 `NOTICE_TYPE_IDS.get()` |
| `ValidationError: time field required` | `NoticeEvent` 字段是必填 | 改 `Optional` |
| `isinstance` 抛 `TypeError` | 注解是字符串或下标泛型 | `func_accepts_event` 里 try/except |
| `func.request_type` 报 `AttributeError` | `FuncMeta` 没存这个字段 | F.3 |
| 图发不出去 | 旧 `ImageSegment` 生成的段名是 `img` | 改 `image`（E.4） |
| `[CQ:json,data={...}]` 被逗号截断 | 手拼 f-string | 用 `MessageSegment(...).to_cq()` 渲染 |

---

## 11. 与 M7 / M8 的交接清单

M7（`api/bot.py`）会 `from .utils import CreateOnWaitingTask, get_connection, require_connection`：

- 你 M6 **必须提供**：`get_connection()`、`require_connection()`、`CreateOnWaitingTask`（已存在，别删）。
- 你 M6 **必须提供**：`MessageEvent.get_message_id`（`Bot.reply` 要用）。

M8（`main.py`）会用到：

- `MessageEvent.from_payload(payload)`、`NoticeEvent.model_validate`、`RequestEvent.model_validate`
- `WaitingEvent(event)`、`await_run_func(func, bot, event)`、`func_accepts_event(func, event)`
- `get_notice_func_pool()` / `get_request_func_pool()`
- `shutdown()` / `is_shutdown_requested()`（退出监听）、`At`

> ⚠️ **别让 M8 去读 `utils.to_shutdown`**：它是个模块级 `bool`，`from api import to_shutdown`
> 拿到的是**导入那一刻的副本**，之后 `api.shutdown()` 改的是 `api.utils` 里的全局量，
> 副本永远是 `False` → "插件请求退出"永远不生效。M8 必须用 `is_shutdown_requested()`。

**两边都不要在这阶段动**，保持"每步可运行"。

> **下一步**：[M7 教程：发送层](m7-bot-layer-tutorial.md)（`api/bot.py` + holder 收尾 + 导出）。
> 里面复盘了一个实测结论：M6 留下的 holder 空壳 + `Bot` 里调 `self._outgoing_format()`
> 会让 `bot.send()` **静默失败**（`AttributeError` 被 `except Exception` 吞掉，日志只说"可能被风控"）。
> 所以 M7 的第 0 步就是把这三个空壳补上（§3 任务 A）。
>
> **再下一步**：[M8 教程：运行层](m8-runtime-layer-tutorial.md)（`main.py` + `script.py` + `debug.py`）。
> 它开头列的三项前置（`await_run_func` 吃同步函数、`LocalEchoConnection` / `require_connection`
> 导出）**都已经落地**。

---

## 附录 A：6 个标准 payload

> **首选**：直接用 `tests/mock_snowluma.py` 的构造器（测试里 `from mock_snowluma import ...`）：
>
> | 需要的东西 | 直接写 |
> | --- | --- |
> | 群消息（array，带 at 段） | `group_message("echo hi", segments=[_seg("text", text="echo hi"), _seg("at", qq="3592797817")])` |
> | 群消息（string） | `group_message("echo hi", message_format="string")` |
> | 私聊（无 `group_id`） | `private_message("hi")` |
> | 私聊临时会话（有 `group_id`） | `{**private_message("hi"), "sub_type": "group", "group_id": 123456}` |
> | 通知 | `notice("group_recall")` / `notice("group_increase")` / `notice("group_increase", honor_type="performer")` |
> | 请求 | `group_request("求进群")` |
>
> 下面这份手写 payload 只在你想让用例**不依赖 tests/ 其它文件**时使用（两者取其一，别重复维护）。

```python
SELF_ID = 999

GROUP_ARRAY = {                                   # A-1~A-7 / C-1~C-4
    "post_type": "message", "message_type": "group", "sub_type": "normal",
    "time": 1699108463, "self_id": SELF_ID, "message_id": 12345,
    "group_id": 123456, "user_id": 169699201, "font": 0,
    "message": [
        {"type": "text", "data": {"text": "echo hi"}},
        {"type": "at", "data": {"qq": "3592797817"}},
    ],
    "raw_message": "echo hi[CQ:at,qq=3592797817]",
    "sender": {"user_id": 169699201, "nickname": "雨弈", "card": "群名片",
               "role": "owner", "level": "", "title": ""},
    "anonymous": None,
}

GROUP_STRING = {**GROUP_ARRAY, "message": "echo hi[CQ:at,qq=3592797817]"}     # S-1~S-3

GROUP_STRING_MALFORMED = {**GROUP_ARRAY, "message": "[CQ:at,qq=123 没闭合"}     # S-2

PRIVATE = {                                       # B-1
    "post_type": "message", "message_type": "private", "sub_type": "friend",
    "time": 1699108463, "self_id": SELF_ID, "message_id": 54321,
    "user_id": 169699201, "message": "hi", "raw_message": "hi",
    "sender": {"user_id": 169699201, "nickname": "雨弈", "sex": "unknown", "age": 24},
}                                                  # 注意：没有 group_id

PRIVATE_TEMP = {**PRIVATE, "sub_type": "group", "group_id": 123456}            # B-2

NOTICE = {                                        # D-1~D-4
    "post_type": "notice", "notice_type": "group_increase", "sub_type": "approve",
    "time": 1699108463, "self_id": SELF_ID, "group_id": 123456,
    "user_id": 88888, "operator_id": SELF_ID,
}

REQUEST = {                                       # D-5~D-6
    "post_type": "request", "request_type": "group", "sub_type": "add",
    "time": 1699108463, "self_id": SELF_ID, "group_id": 123456,
    "user_id": 77777, "comment": "求进群", "flag": "flag-1",
}
```

---

## 附录 B：改动索引（按符号名，**核对现状见"现行状态"列**）

| 文件 · 符号 | 旧现状 | M6 动作 | 现行状态 |
| --- | --- | --- | --- |
| `api/event.py` 顶部 segment import | 注释掉的 import | 放开（只留用到的） | ✅ 已生效，且无未使用导入 |
| `SenderInfo.display_name` | 兜底会返回 `"None"` | `or ""` | ✅ 已改 |
| `SenderInfo.to_dict` | 返回内部字典 | `dict(self._raw)` | ✅ 已改 |
| `api/event.py` 模块级 assert | 曾有模块级 assert | 建议移到 `tests/test_event.py` | ✅ 已不在 `api/event.py`；断言都在 `tests/` 里 |
| `MessageEvent` | 旧实现 | 任务 A 重写 | ✅ 已重写 |
| `MessageEvent.__init__` | 提前 `return`（半初始化） | 删除 | ✅ 已删 |
| `MessageEvent.To*MessageEvent` | 挑字段复制 | 改成重包 `_payload` | ✅ 已改 |
| `MessageEvent.set_message` | 不同步 `_segments` | A.6 | ✅ 已同步 |
| `GroupMessageEvent` | 独立类 | 任务 B：继承 | ✅ 已改继承 |
| `PrivateMessageEvent` | 独立类 + 2 个 bug（`_group_id` / `_message_type`） | 任务 B | ✅ 已继承且两个 bug 已修 |
| `WaitingEvent` | `__init__` 里 id 错位 | 任务 C | ✅ 已改整份复制 |
| `NoticeEvent` | 必填字段 + `[...]` 索引 KeyError | 任务 D | ✅ 已 `Optional` + `NOTICE_TYPE_IDS.get()` |
| `RequestEvent` | 不存在 | 任务 D 新增 | ✅ 已新增 |
| `api/utils.py` import | import `httpx` 等 | 调整 | ✅ 已加 `asyncio` / `inspect` / `typing`；`httpx` 已不在本模块 |
| `api/utils.py` `run_func` | `res` 未绑定 | E.2 | ✅ 已修（`@logger.catch` 仍保留） |
| `api/utils.py` `await_run_func` | `await None` + `print` | E.2 | ✅ 已修 |
| `api/utils.py` `set_device` | 打错端口/端点（`httpx.post(:9920/send_msg)`） | E.6 | ✅ 已改走 `require_connection().call_action("_set_model_show", ...)` |
| `api/utils.py` `AnalyseCQCode` | 手写状态机 | E.5 | ✅ 已改复用 `parse_cq_to_segments` |
| `api/utils.py` `At` / `ImageSegment` / `MessageSegment` | `ImageSegment` 段名错（`img`） | E.4 | ✅ 已改 `image`；`to_shutdown` 仍是模块级内部量，外部请用 `is_shutdown_requested()` |
| `api/on.py` `on_notice` | 直接用 `.value` | F.2 | ✅ 已用 `_type_value` 兼容 int/枚举 |
| `api/on.py` `on_request` / `get_request_func_pool` | 不存在 | F.3 | ✅ 已新增 |
| `plugins/manager.py` `FuncMeta` | 无 `request_type` | F.3 | ✅ 已加 |
| `plugins/manager.py` `FuncMeta.name` / `__str__` | 嵌套 `WaitingFuncMeta` 时点 `__name__` 会炸 | —（M8 发现） | ✅ 已用 `_func_name` 兜底 |
| `tests/test.py` | 曾存在 | 删掉或改名 | ✅ 已删除；pytest 本来也不收集非 `test_*.py` |
