# ADR-0001：插件层的消息表示 —— CQ 码字符串 vs 消息段数组

| 项 | 值 |
| --- | --- |
| 状态 | **已采纳（Accepted）** |
| 日期 | 2026-10-01 |
| 决策者 | HysialX 维护者 |
| 影响范围 | `snowluma/segment.py`、`snowluma/connection.py`、`api/event.py`、`api/bot.py`、`api/utils.py`、`main.py`、`plugins/*` |
| 相关文档 | [设计文档](../snowluma-protocol-design.md)、[M6 事件层教程](../m6-event-layer-tutorial.md) |

> 注：本文中的行号会随重构漂移，请以函数名/符号名为准。

---

## TL;DR

1. **协议层内部以消息段数组为准**（结构上安全、可组合、能表达转发/卡片）。
2. **插件 API 默认给 CQ 码字符串**（`event.get_message`、`send()` 接受 `str`），因为
   现有 5 个插件、OneBot 生态示例、日志与模板都建立在它之上。
3. **段数组是一等公民而非逃生舱**：`event.get_message_segments`、`send()` 接受
   `MessageSegment` / 段列表。
4. **三个视图语义固定**：`get_plain_text`（未转义，只用于匹配）、`get_message`（已转义，
   可直接回发）、`get_message_segments`（结构）。
5. **不可协商的硬规则**：`send()` 收到的**字符串一律按 CQ 码语义解析**，因此任何来自
   用户/外部的字节在进入 `send()` 前必须是 `MessageSegment` / `Text(...)` / 裸串 +
   `auto_escape=True` 三种安全形态之一。

---

## 1. 背景（Context）

### 1.1 协议端给了两种表示

SnowLuma（OneBot v11）的 `messageFormat` 决定事件里 `message` 字段的形态：

- `array`（默认）：`[{"type": "text", "data": {"text": "hi"}}, {"type": "at", "data": {"qq": "1"}}]`
- `string`：`"hi[CQ:at,qq=1]"`

发送时两种都收，另有 `auto_escape` 表示"整条消息不解析 CQ 码"。

### 1.2 现有资产全部长在 CQ 字符串上

| 位置 | 用法 |
| --- | --- |
| [plugins/Defalut/main.py:28](<../plugins/Defalut/main.py#L28>)、[:38](<../plugins/Defalut/main.py#L38>) | `event.get_message.strip()` 直接回显 |
| [plugins/chatgpt/main.py:81](<../plugins/chatgpt/main.py#L81>) | `event.reply(At(uid) + 文本)` |
| [plugins/t/main.py:47](<../plugins/t/main.py#L47>)、[:53](<../plugins/t/main.py#L53>) | `f"[CQ:at,qq={user_id}]"`、`f"[CQ:image,file=...]"` |
| [plugins/Xpic/main.py:53](<../plugins/Xpic/main.py#L53>) | `f"[CQ:image,file={path}]"`（path 来自外部 API） |
| [plugins/XHuaLao/main.py:94](<../plugins/XHuaLao/main.py#L94>) | `f"[CQ:image,file=base64://{img_str}]"` |
| [main.py:43](<../main.py#L43>) | `sender_message = event.get_message` 之后做命令/正则匹配 |

M1 已经实现了双向转换与转义：[snowluma/segment.py](../snowluma/segment.py) 的
`escape_cq` / `parse_cq_to_segments` / `segments_to_cq` / `segments_to_dicts` /
`normalize_segments` / `message_to_payload`。

### 1.3 两种表示各有不可替代之处

- **CQ 串赢在**：可读（能直接打日志）、能被 `startswith`/`in`/正则处理、
  能塞进 JSON 当自动回复模板、生态示例最多、插件作者零学习成本。
- **段数组赢在**：参数无需手工转义（结构不会被 `]` `,` 破坏）、可按类型取内容、
  能表达 CQ 串表达不了或各家方言不一的东西（合并转发、json/markdown 卡片、mface）。

### 1.4 风险：字符串即代码

`send()` 把字符串按 CQ 码解析，等价于"字符串是代码"。一旦把**用户内容**拼进 CQ 串，
用户就能让机器人替他执行 CQ 码——@全体成员、发任意图片/语音、伪造引用回复等。
这是 QQ 机器人框架的经典漏洞类别，且在本项目的代码里已有"安全但脆弱"的写法
（见 §4.2）。

### 1.5 约束

- 不重写现有 5 个插件（迁移成本必须接近 0）。
- 已具备完整的段工具（M1），转换是常数开销。
- 日志与排障必须保持人可读。

---

## 2. 决策（Decision）

### D1 —— 协议层内部以段数组为准

`MessageSegment` 是内部唯一的结构化表示；`snowluma/segment.py` 的转换函数是唯一的
解析/序列化入口。任何"手写 CQ 串解析"（如旧 `api/utils.py` 的 `AnalyseCQCode` 状态机）
一律改为调用 M1。

### D2 —— 插件 API 默认暴露 CQ 码字符串

- `event.get_message` → **已转义**的 CQ 串，可直接回发、可打日志。
- `bot.send(uid, message, mode)` 接受 `str`（CQ 码语义）。

### D3 —— 段数组是一等公民

- `event.get_message_segments` → 段视图。
- `send()` 同样接受 `MessageSegment` 与段列表。
- `api/__init__.py` 导出 `MessageSegment` 与常用段构造，使段路径与串路径同样"官方"。

### D4 —— 三个视图语义固定，不许混用

| 视图 | 内容 | 允许用途 | 禁止用途 |
| --- | --- | --- | --- |
| `get_plain_text` | 只拼 text 段，**未转义** | 命令/关键词/正则匹配、展示、统计 | **直接回发** |
| `get_message` | 框架转义后的 CQ 串 | 日志、回发、模板 | 用手工裁剪破坏其结构 |
| `get_message_segments` | 段数组 | 取图/@/文件、拼复杂消息 | — |

### D5 —— 用户内容进 `send()` 前必须转成安全形态（不可协商）

三种安全形态，任选其一：

```python
await bot.send(gid, MessageSegment.text(user_text))      # ① 推荐：结构化
await bot.send(gid, Text(user_text))                     # ② CQ 串风格 + 显式转义
await bot.send(gid, user_text, auto_escape=True)         # ③ 整条不解析
```

反面（**禁止**）：

```python
await bot.send(gid, f"{At(uid)} {user_text}")            # ✗ user_text 未转义 → CQ 注入
await bot.send(gid, event.get_plain_text)                # ✗ 未转义 → CQ 注入
```

### D6 —— 匹配一律用 `get_plain_text`

`on_command` / `on_keyword` / `on_regex` 的输入改为 `get_plain_text`，不再用 CQ 串。
直接后果：`@机器人 菜单` 也能命中 `on_command("菜单")`（现在是命中不了的，因为串是
`[CQ:at,qq=...] 菜单`）。

### D7 —— `on_at` 降级为"必须 @"的修饰条件

命令匹配不再依赖 `on_at` 才能去 @；`on_at` 只表示"这条消息必须 @ 机器人才算"。

---

## 3. 理由（Rationale）

| 场景 | 选哪个 | 原因 |
| --- | --- | --- |
| 纯文本回复、命令、关键词 | CQ 串 | 可读、可日志、正则/`startswith` 直接可用 |
| `@某人` + 文本 | CQ 串（`At()` + f-string） | 生态习惯，迁移成本 0 |
| 图片/语音/文件的 `file` 来自用户或外部 API | **段数组** | 参数由框架转义，`]` `,` 不会破坏结构 |
| 合并转发、json/markdown 卡片 | **段数组** | CQ 串表达不了或属方言 |
| 按类型取内容（找图、取所有 @） | **段数组** | 结构直接可用，不用写正则 |
| 命令/关键词/正则匹配 | **plain text** | 否则 `@机器人 命令` 永远匹配不上 |
| 存 JSON 当自动回复模板 | CQ 串（简单）/ 段数组（含结构） | 两者都可序列化 |
| 日志、排障 | CQ 串 | 段数组的 repr 不适合人读 |

一句话：**简单场景用串（省事），参数化/结构化场景用段（安全），匹配用纯文本（正确）。**

---

## 4. 后果（Consequences）

### 4.1 正面

- 5 个现有插件零改动；README 里"可对接所有实现 OneBot 标准的服务端"仍然成立。
- 用户内容有明确的安全出口（`Text()` / `auto_escape` / 段对象），注入面可被测试锁死。
- 转发、卡片、结构化拼装这类能力不被 CQ 串的表达力限制。
- 匹配逻辑顺带修好"@机器人 命令 不生效"的老问题。

### 4.2 负面 / 成本

- **要维护两套表示**：转换本身是常数开销（M1 已实现），真正成本是**文档纪律** ——
  插件作者必须知道"什么时候用哪个"。用 §6 的规则与 review checklist 摊平。
- **转义正确性成为关键路径**：`escape_cq`/`unescape_cq` 一旦有 bug，安全性直接失效。
  因此 M1 的断言（[segment.py:225-274](../snowluma/segment.py) 那一批）必须常驻测试。
- **既有的"安全但脆弱"写法仍需收口**：例如
  [Defalut/main.py:28](<../plugins/Defalut/main.py#L28>) 回显 `get_message` 目前是安全的
  （因为 `get_message` 已转义），但它依赖"没人把它改成 `get_plain_text`"这一隐含前提。
  §6 的注入用例就是为了把这个前提变成回归测试。
- `get_plain_text` 的存在本身是陷阱源（未转义却长得像"纯文本"），只能靠 D4 的用途表约束。

### 4.3 需要配套的强制项

1. `send()` 的签名必须同时接受 `str | MessageSegment | list[MessageSegment]`。
2. `api/__init__.py` 导出 `MessageSegment`（M6 的产物清单里已含此项）。
3. §6 的注入回归用例必须落地。
4. README 必须含一正一反示例（§2 D5 的两段代码）。

---

## 5. 备选方案（Alternatives）

### 方案 A：只用 CQ 码字符串（无段视图）

**拒绝。** 无法表达合并转发/json 卡片等结构；取内容只能靠正则（旧 `AnalyseCQCode`
就是这条路的产物，遇到多参数与 base64 就会错）；参数转义责任完全落在插件作者身上，
注入面最大化。

### 方案 B：只用消息段数组（字符串即字面量）

**拒绝（当前）。** 安全性最好，但代价是：`At()` / `ImageSegment()` 等现在返回 `str`
的工具必须改为返回段对象；5 个插件里所有 `f"{At(uid)} 文本"` 都要改成列表拼接；
`get_message` 不再是"可直接回发"的东西。在"插件已大量使用 CQ 串 + 协议端两种格式都收
+ M1 转义已可靠"的前提下，收益不抵迁移与教学成本。

**重估条件**见 §7。

### 方案 C：字符串=字面量（NoneBot2 风格），结构一律用段对象

即方案 B 的严格版（不存在"字符串是 CQ 码"这一层）。**同样拒绝（当前）**，理由同上；
它与方案 B 的区别只在"是否保留 CQ 解析入口"，而本项目必须保留，因为
[a 的 `auto_escape` 与 CQ 串模式是协议端的一等能力](#11-协议端给了两种表示)。

### 方案 D：双表示，串为默认、段为一等公民，用规则约束用户内容（**采纳**）

即 §2。它是 A 与 B 的折中：**保留零迁移成本与生态习惯，同时给结构化和安全性留出口**。
代价是"两套表示 + 一条纪律"，用 §6 的规则与测试兜底。

---

## 6. 执行与验证（Enforcement）

### 6.1 代码约定

| 约定 | 位置 |
| --- | --- |
| 唯一的解析/序列化入口，禁止手写 CQ 解析 | `snowluma/segment.py` |
| `send_message()` 同时接受 `str` / `MessageSegment` / 段列表，并按 `auto_escape` 短路 | [connection.py:463](../snowluma/connection.py#L463) |
| 发出格式跟随 `message_format`（配置 > 对端探测 > array） | [connection.py:194](../snowluma/connection.py#L194) |
| 三个事件视图语义固定 | M6 的 `api/event.py` |
| 匹配用 `get_plain_text` | M8 的 `check_whether_func` / 分发器 |

### 6.2 注入回归用例（已落地在 `tests/test_event.py`，段级断言在 `tests/test_segment.py`）

核心不变式：**把用户写的字面量 CQ 码当内容回发，协议端必须收到"文本"而不是"动作"。**

| # | 用例 | 期望 |
| --- | --- | --- |
| S1 | 用户发的字面量在段视图里是 text：`group_message("x", segments=[_seg("text", text="[CQ:at,qq=all]")])` | `get_plain_text == "[CQ:at,qq=all]"`（裸），且 `get_message` 含 `&#91;CQ:at&#44;qq=all&#93;`（已转义） |
| S2 | 回发 `get_message` | mock 收到的 `send_msg.params["message"]` 里该内容是 **text 段**（array 模式）/ 仍为转义串（string 模式） |
| S3 | 回发 `Text(get_plain_text)` | 同上：text 段 / 转义串 |
| S4 | 回发 `get_plain_text, auto_escape=True` | 整条原样透传（`auto_escape is True`），协议端不解析 |
| S5 | 反例留档：`f"{At(uid)} {get_plain_text}"` 在 `message_to_payload(..., "array")` 后**会出现 at 段** | 作为"为什么禁止"的可执行证据（断言其**存在** at 段，用于说明风险） |

> S5 是"断言漏洞存在"的元测试：它故意证明反例不安全，防止有人日后以为"反正框架会转义"。
> 若要避免长期红灯，可把 S5 只写进 ADR 文档而不进测试套件（二选一，建议留在测试里并标注
> `# 反例：证明危险，不是期望行为`）。

#### 6.2.1 实测输出（2026-10-01，实测对象 `snowluma/segment.py`）

已用当前代码跑通，可直接把这些值抄成断言里的期望值：

| 用例 | 表达式 | 实测结果 |
| --- | --- | --- |
| S1 | `get_plain_text` | `'[CQ:at,qq=all]'`（裸） |
| S1 | `get_message` | `'&#91;CQ:at&#44;qq=all&#93;'`（已转义） |
| S2 | `message_to_payload(转义串, "array")` | `[{"type":"text","data":{"text":"[CQ:at,qq=all]"}}]` |
| S2 | `message_to_payload(转义串, "string")` | `'&#91;CQ:at&#44;qq=all&#93;'` |
| S3 | `message_to_payload(escape_cq(裸串), "array")` | 同 S2（text 段） |
| S4 | `message_to_payload(裸串, "array", auto_escape=True)` | `'[CQ:at,qq=all]'`（原样透传） |
| S5 | `message_to_payload("[CQ:at,qq=169699201] [CQ:at,qq=all]", "array")` | `[{at,169699201}, {text," "}, {at,"all"}]` ← **注入成立** |

结论：**注入与目标格式无关**——`message_to_payload` 对字符串一律先 `normalize_segments`
再按格式渲染，所以 array 模式下未转义的 `[CQ:at,qq=all]` 同样会变成真正的 `at` 段。
防线只能在"进入 `send()` 之前"（D5），不能指望发送侧兜底。

### 6.3 Review checklist（提 PR 时对照）

- [ ] 新增的 `send()` 调用里，插入的字符串是否**全部**来自 `At()` / `ImageSegment()` /
      `Text()` 等框架函数，或本身是数字 id？
- [ ] 是否把 `get_plain_text` 直接回发了？（禁止）
- [ ] 需要"取图 / 取 @ / 取文件"的地方，是否用 `get_message_segments` 而不是正则？
- [ ] 新响应器的匹配输入是否是 `get_plain_text`？
- [ ] README/教程示例是否遵守 D5 的正反两例？

---

## 7. 重审触发条件（Revisit triggers）

出现下列任一情况时重开本 ADR：

1. **再次发生 CQ 注入事故**（哪怕是"安全但脆弱"的写法导致的），且 review checklist 未能拦住；
2. 需要**合并转发 / json 卡片 / mface 成为常见需求**（占比高到"CQ 串只是装饰"）；
3. SnowLuma 或 OneBot v12 **弃用 string 模式**（则 D2 的存在理由消失，可直接转向方案 C）；
4. 插件数量增长到"两套表示的教学成本 > 迁移成本"的临界点（经验阈值：新插件作者
   连续 3 次问"这个该用串还是段"）。

---

## 8. 参考

- OneBot v11 消息段与 CQ 码规范：<https://github.com/botuniverse/onebot-11>
- SnowLuma 配置参考（`messageFormat` / `reportSelfMessage`）：<https://snowluma.github.io/zh/docs/guide/configuration>
- SnowLuma 动作参考（`send_msg` / `auto_escape` / `send_forward_msg`）：<https://snowluma.github.io/zh/docs/api>
- 项目内：[设计文档](../snowluma-protocol-design.md) §7「事件层设计」、[M6 教程](../m6-event-layer-tutorial.md) §1「决定 1/2」
