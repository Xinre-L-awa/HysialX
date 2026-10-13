# HysialX × SnowLuma 信息收发重写 —— 设计文档

> 本文是**设计规格**，不含实现代码，供你自行落地。
> 结论先行：SnowLuma 是 **OneBot v11 协议端**，HysialX 只需按 OneBot v11 的
> 「WebSocket 事件 + 动作信封」模型实现收发即可，重点是 **三种通道、access token、
> `retcode` 应答信封、`messageFormat` 双格式（array / string）** 四件事。
>
> 文档里标注了 `【实测】` 的内容，是我在一台真实的 SnowLuma `1.14.19-node`
> 实例上验证过的行为，可直接当作验收基准。

---

## 目录

1. [背景与结论](#1-背景与结论)
2. [SnowLuma 协议事实](#2-snowluma-协议事实)
3. [HysialX 现状与差距](#3-hysialx-现状与差距)
4. [目标架构](#4-目标架构)
5. [配置层设计](#5-配置层设计)
6. [连接层设计](#6-连接层设计)
7. [事件层设计](#7-事件层设计)
8. [发送与动作层设计](#8-发送与动作层设计)
9. [运行层设计](#9-运行层设计)
10. [必须修正的既有缺陷](#10-必须修正的既有缺陷)
11. [测试与验收方案](#11-测试与验收方案)
12. [已知坑与注意事项](#12-已知坑与注意事项)
13. [分阶段实施建议](#13-分阶段实施建议)
14. [附录：实测证据与事件样例](#14-附录实测证据与事件样例)

---

## 1. 背景与结论

### 1.1 SnowLuma 是什么

SnowLuma 是一个 **QQ 客户端互操作运行时**（TypeScript + 原生 Hook 模块），把 QQ 原生
会话转换成 **OneBot v11 的动作与事件**，再通过 HTTP / WebSocket / WebUI / SDK / MCP
暴露出来。它**不是机器人框架**，机器人进程连过去即可。

- 仓库：<https://github.com/SnowLuma/SnowLuma>
- 文档：<https://snowluma.github.io/zh/docs/guide/configuration>（配置）、
  <https://snowluma.github.io/zh/docs/api>（动作参考）、
  <https://snowluma.github.io/zh/docs/guide/connect-bot>（对接机器人）
- 实现参考：LagrangeV2（协议定义）+ NapCatQQ（实现思路）
- 本机实测版本：`SnowLuma 1.14.19-node`，OneBot `v11`【实测】

### 1.2 结论

对 HysialX 来说，「按 SnowLuma 协议重写收发」= **按 OneBot v11 重写收发**，具体四件事：

| # | 事项 | 一句话说明 |
| --- | --- | --- |
| 1 | 通道 | 正向 WS（我们连它）/ 反向 WS（它连我们）/ HTTP API 三种，事件与动作都走同一套动作名 |
| 2 | 鉴权 | `Authorization: Bearer <token>` 或 `?access_token=`；HTTP 与 WS 可能各自一个 token |
| 3 | 应答信封 | `{status, retcode, data, message, wording}`，**只有 `retcode == 0` 才算成功**（HTTP 200 也可能是业务失败） |
| 4 | 消息格式 | `messageFormat` 为 `array`（默认）或 `string`；事件里 `message` 是段数组或 CQ 码字符串 |

---

## 2. SnowLuma 协议事实

### 2.1 网络适配器与配置文件

配置文件（JSON）：

```
config/onebot.json          # 全局默认
config/onebot_<uin>.json    # 账号级覆盖（优先）
config/runtime.json         # 进程级：webuiPort(5099)、hookAutoLoad
```

网络适配器按类型分组放在 **`networks`** 对象下：

```jsonc
{
  "networks": {
    "httpServers": [{                 // 提供 HTTP API
      "name": "http-default", "enabled": true,
      "host": "0.0.0.0", "port": 3000, "path": "/",
      "accessToken": "自动生成", "messageFormat": "array", "reportSelfMessage": false
    }],
    "httpClients": [{ "url": "http://...", "timeoutMs": 5000 }],   // 主动 POST 上报事件
    "wsServers": [{                   // 提供 WebSocket 服务
      "name": "ws-default", "enabled": true,
      "host": "0.0.0.0", "port": 3001, "path": "/",
      "role": "Universal",            // Api | Event | Universal（大写驼峰）
      "accessToken": "自动生成", "messageFormat": "array", "reportSelfMessage": false
    }],
    "wsClients": [{                   // 反向 WebSocket：它连我们
      "url": "ws://127.0.0.1:6700/", "role": "Universal",
      "reconnectIntervalMs": 5000     // 会被规范化为最小 1000
    }]
  },
  "musicSignUrl": ""
}
```

通用字段（`NetworkBase`）：`name`（同类型内唯一）、`enabled`、`accessToken`、
`messageFormat`（`array` / `string`）、`reportSelfMessage`。

> **旧格式兼容**：早期版本把 `httpServers` / `wsServers` 直接放顶层，用
> `httpPostEndpoints` 表示上报；SnowLuma 检测到会自动迁移到 `networks` 并把
> `httpPostEndpoints` 改名为 `httpClients`。**做配置发现时要同时兼容两种结构。**

环境变量：`SNOWLUMA_HOOK_AUTOLOAD`、`SNOWLUMA_LOG_LEVEL`、
`SNOWLUMA_VERBOSE_WARMUP`、`SNOWLUMA_DEV_MODE`、`SNOWLUMA_DEV_WEBUI`。

### 2.2 动作调用（HTTP / WS 动作名一致）

| 项目 | HTTP | WebSocket |
| --- | --- | --- |
| 地址 | `POST http://127.0.0.1:3000/{动作名}` | `ws://127.0.0.1:3001/` |
| 请求体 | **`params` 直接作为 JSON body** | `{"action": "...", "params": {...}, "echo": "任意回显"}` |
| 应答 | 同一套信封 | 同一套信封，需带回 `echo` |
| 鉴权 | `Authorization: Bearer <token>` 或 `?access_token=<token>` | 握手时同上（查询参数或 Header） |

应答信封：

```json
{ "status": "ok", "retcode": 0, "data": {}, "message": "", "wording": "" }
```

**判定成功的唯一标准是 `retcode == 0`。**【实测】未知动作会返回
`status="failed"`、`retcode=1404`、`message="unknown action"`。

常用动作（全量 115+ 个，见官方动作参考）：

- 消息：`send_msg`、`send_group_msg`、`send_private_msg`、`get_msg`、`delete_msg`、`send_custom_face`
- 信息：`get_login_info`、`get_status`、`get_version_info`、`can_send_image`、`can_send_record`
- 列表/资料：`get_group_list`、`get_friend_list`、`get_group_info`、`get_group_member_info`、`get_group_member_list`、`get_stranger_info`
- 扩展：`_get_model_show` / `_set_model_show`（机型展示，**占位实现**）、`send_poke`、`set_group_ban`、`set_msg_emoji_like`、`mark_msg_as_read`、`get_group_msg_history`、`send_forward_msg`、`upload_forward_msg`、`ocr_image`、`get_cookies`、`get_credentials`、`get_rkey`、`set_online_status`、`set_qq_profile`、`set_self_longnick` …

`send_msg` 关键点：

```jsonc
// params
{
  "message_type": "group" | "private",   // 也支持按 group_id / user_id 自动路由
  "group_id": 123456,                    // message_type=group
  "user_id": 169699201,                  // message_type=private
  "message": [ ...段数组... ] | "CQ 码字符串",
  "auto_escape": false                   // true 时不解析消息里的 CQ 码
}
// data
{ "message_id": 123 }
```

> README 补充：JSON 消息段接受标准的 `data.xxx` 字符串，也兼容 `data` 为非数组对象、
> 以及 `{ "type": "json", "data": "..." }` 简写；`data` 必填，最终内容必须是 JSON 对象。

### 2.3 事件

事件由 WS 或 HTTP 上推送来，共同字段：`time`、`self_id`、`post_type`。

| `post_type` | 说明 | 关键字段 |
| --- | --- | --- |
| `message` | 收到消息 | `message_type`(group/private)、`sub_type`、`message_id`、`group_id`、`user_id`、`message`、`raw_message`、`font`、`sender{user_id,nickname,card,role,level,title,sex,age,area}`、`anonymous` |
| `message_sent` | **机器人自己发的消息**（`reportSelfMessage=true` 时） | 与 `message` 同构 |
| `notice` | 通知 | `notice_type`、`sub_type`、`group_id`、`user_id`、`operator_id`、`target_id`、`message_id`、`duration`、`file` |
| `request` | 请求 | `request_type`(friend/group)、`sub_type`(add/invite)、`comment`、`flag`、`user_id`、`group_id` |
| `meta_event` | 生命周期 / 心跳 | `meta_event_type`(lifecycle/heartbeat)、`sub_type`(connect/enable/disable)、`interval`、`status{online,good}` |

常见 `notice_type`：
`group_upload`、`group_admin`、`group_decrease`、`group_increase`、`group_ban`、
`friend_add`、`group_recall`、`friend_recall`、`group_card`、`offline_file`、
`client_status`、`essence`、`notify`（戳一戳 / 运气王等，看 `sub_type`）。

【实测】真实 SnowLuma 在连接建立后会依次推送 **`lifecycle/connect`** 与
**`lifecycle/enable`** 两条 meta 事件，随后按 `interval` 发 heartbeat。

### 2.4 消息格式：array vs string

事件里的 `message` 字段取决于该适配器的 `messageFormat`：

```jsonc
// array（默认）
"message": [
  { "type": "text", "data": { "text": "你好" } },
  { "type": "at",   "data": { "qq": "169699201" } },
  { "type": "image","data": { "file": "https://..." } }
]
// string
"message": "你好[CQ:at,qq=169699201][CQ:image,file=https://...]"
```

`raw_message` 通常是 CQ 码字符串形态。

**CQ 码转义规则**（两种表示互转必须处理，否则 `[`/`]`/`,` 会破坏结构）：

| 原字符 | 转义为 |
| --- | --- |
| `&` | `&amp;` |
| `[` | `&#91;` |
| `]` | `&#93;` |
| `,` | `&#44;` |

建议同时转义 **参数值** 与 **text 段内容**，保证 round-trip 无损。

---

## 3. HysialX 现状与差距

现有收发链路（`main.py` + `api/bot.py` + `api/event.py` + `api/utils.py`）：

| 现状 | 问题 |
| --- | --- |
| `websocket-client` 的同步 `WebSocketApp.run_forever()` 跑在子线程 | 与 asyncio 混用；每个事件用 `asyncio.run()` 起独立事件循环，无法共享连接状态 |
| 地址硬编码 `ws://127.0.0.1:3001/`、`http://127.0.0.1:3000/send_msg` | 无法配置、无 token、无反向 WS、无重连 |
| `httpx.post(...)` 同步调用写在 `async def` 里 | 阻塞事件循环 |
| `event.get_message` 直接取 `msg["message"]` | 假设它是 CQ 字符串；SnowLuma 默认 `array` 会拿到 list |
| 只认 `post_type in ("message", "notice")` | `message_sent`、`request` 被丢弃 |
| `Bot.call_api` 写的是 `await httpx.AsyncClient(url, params=params)` | 从未真正发出请求，也不会检查 `retcode` |
| `PrivateMessageEvent.__init__` 读 `msg["group_id"]` | 私聊事件没有该字段 → `KeyError` |
| `WaitingEvent` 把 `_group_id` 设成 `get_user_id` | 群聊等待任务的 `group_id` / `user_id` 错位 |
| `ImageSegment()` 生成 `[CQ:img,...]` | 段名错误，标准是 `image` |
| 计划任务用 `timedelta.seconds` 比较 | 定时逻辑基本失效（负 timedelta 的 `.seconds` 是极大正数） |
| `init(False)` 跳过了所有配置检查 | 启动时完全没校验配置 |

---

## 4. 目标架构

建议分层，**收发内核与插件框架解耦**（内核不 import 插件层）：

```
snowluma/                     # 新：协议内核（不依赖 api/、plugins/）
├─ config.py                  # 连接配置 + SnowLuma 配置目录发现
├─ segment.py                 # 消息段 ⇄ CQ 码
├─ connection.py              # 正向/反向 WS + HTTP + echo 应答 + 重连 + 事件队列
├─ exception.py               # ActionFailed / ConnectionUnavailable / ConfigError
└─ __init__.py
api/                          # 改造：插件面向的公共 API
├─ event.py                   # 事件模型（对外统一 CQ 字符串 + 段视图）
├─ bot.py                     # 发送与动作封装（走内核）
├─ utils.py                   # 执行封装、当前连接、CQ 工具
├─ on.py                      # 响应器注册（新增 on_request）
└─ __init__.py
main.py                       # 改造：单一事件循环 + 事件队列分发 + 优雅退出
config/snowluma.json          # 新：HysialX 侧连接配置（可留空自动跟随 SnowLuma）
```

依赖方向：`main → api → snowluma → log`，**不允许反向**。
`api/event.py` 只依赖 `snowluma/segment.py` 与 `htyping`，因此内核可单独测试。

---

## 5. 配置层设计

### 5.1 三层优先级（后者覆盖前者）

1. **内置默认**：HTTP `http://127.0.0.1:3000` + path `/`；正向 WS `ws://127.0.0.1:3001/`；反向监听 `0.0.0.0:6700`。
2. **SnowLuma 目录发现**：读取 `config/onebot.json` / `config/onebot_<uin>.json`，提取地址、端口、path、`accessToken`、`messageFormat`、以及 `wsClients` 反推出的监听地址。
3. **HysialX 配置 + 环境变量**：`config/snowluma.json` 里的非空字段、以及 `SNOWLUMA_*` 环境变量。

> **设计约定**：配置里凡是 `""` / `null` / `0` 都表示「自动」，这样用户只需要维护 SnowLuma 一侧。

### 5.2 字段表（`config/snowluma.json`）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `snowluma_dir` | str | `""` | SnowLuma 安装目录（含 `config/onebot.json` 的那一层）；非空则自动发现 |
| `account` | int\|null | `null` | 多账号时指定 `onebot_<uin>.json`；只有一个账号文件时自动选中 |
| `mode` | str | `"both"` | `forward` / `reverse` / `both` |
| `forward_url` | str | `""`(→3001) | 正向 WS 地址 |
| `forward_token` | str | `""` | 正向 token |
| `http_base` / `http_path` / `http_token` | str | `""` | HTTP API 地址 / 路径前缀 / token |
| `reverse.enabled` | bool | `true` | 是否开反向 WS 服务端 |
| `reverse.host` / `port` / `path` / `access_token` | | `""`/`null`/`""`/`""` | 反向监听与期望 token |
| `message_format` | str | `"auto"` | `auto` / `array` / `string` |
| `api_transport` | str | `"auto"` | `auto`（有 WS 走 WS）/ `ws` / `http` |
| `request_timeout` | float | `10.0` | 动作等待应答超时（秒） |
| `reconnect_interval` | float | `5.0` | 重连基础间隔（秒），建议指数退避到 60 |
| `ping_interval` / `ping_timeout` | float | `30.0` | WS 心跳；`0` 表示关闭 |
| `event_workers` | int | `4` | 事件并发处理数 |
| `device_name` | str | `""` | 非空则连接后调用 `_set_model_show` |

### 5.3 发现规则（`discover_from_dir`）

```
1. 目录定位：<dir>/config 或 <dir> 自身，取其中存在 onebot*.json 的那个
2. 选文件：account 指定 → onebot_<uin>.json；否则恰好一个 onebot_*.json → 用它；
   否则 onebot.json；账号文件缺 networks 时回退全局文件
3. 兼容新旧结构：raw["networks"] 存在则用它，否则回退顶层
   httpServers/wsServers/wsClients/httpClients(或 httpPostEndpoints)
4. 只取 enabled 不为 false 的第一项：
   wsServers[0]  → forward_url = ws://{host|127.0.0.1}:{port}{path}，token，messageFormat
   httpServers[0]→ http_base = http://{host|127.0.0.1}:{port}，http_path = path，token
   wsClients[0]  → 解析 url 得到反向 host/port/path，token 用作我们的期望 token
5. 通配地址替换：0.0.0.0 / :: / * / 空 → 127.0.0.1（**只用于我们主动连的方向**；
   反向监听要保持 0.0.0.0）
```

自动探测候选目录（`snowluma_dir` 为空时）：环境变量 `SNOWLUMA_DIR` →
`./SnowLuma`、`./snowluma`、`../SnowLuma`、`../snowluma`。

### 5.4 环境变量（Docker / systemd 友好）

```
SNOWLUMA_DIR                    等价 snowluma_dir
SNOWLUMA_FORWARD_WS             正向 WS（别名 SNOWLUMA_WS_URL）
SNOWLUMA_FORWARD_TOKEN          正向 token（别名 SNOWLUMA_WS_TOKEN）
SNOWLUMA_HTTP_BASE              别名 SNOWLUMA_HTTP_PATH / SNOWLUMA_HTTP_TOKEN
SNOWLUMA_REVERSE_HOST/PORT/TOKEN
SNOWLUMA_MODE / SNOWLUMA_MESSAGE_FORMAT / SNOWLUMA_API_TRANSPORT
SNOWLUMA_ACCOUNT / SNOWLUMA_DEVICE_NAME
```

配置解析完成后应打印一份**脱敏**摘要（token 只显示「已配置/未配置」），便于排障。

---

## 6. 连接层设计

### 6.1 三种通道与统一抽象

```python
class Channel:                 # 一条已建立的 OneBot 通道
    raw            # websockets 连接对象
    kind           # "forward" | "reverse"
    last_seen      # 最近收到报文的时间
    async def send_json(payload)  # 内部加锁，避免并发写同一连接
```

`OneBotConnection` 负责：通道注册/注销、动作发送、事件入队、meta 事件处理、登录探测。

### 6.2 正向 WS 客户端

```python
async with websockets.connect(
        uri,                                  # 带 ?access_token= 的地址
        additional_headers={"Authorization": f"Bearer {token}"} if token else None,
        max_size=16 * 1024 * 1024,            # 事件里可能有 base64 图片
        open_timeout=10,
        ping_interval=..., ping_timeout=...,
        close_timeout=5,
) as ws:
    ...  # 注册通道 → 读循环 → finally 注销通道
```

要点：

- **重连**：外层 `while not closing` 循环 + 指数退避（`base=max(1, reconnect_interval)`，上限 60s）。
- 异常分类：`OSError / InvalidStatus / InvalidHandshake / ConnectionClosed / TimeoutError` → 记警告并按退避重试；`CancelledError` 必须原样抛出。
- 鉴权**两种都带上**（查询参数 + Header），因为 SnowLuma 两种都支持，兼容性最好。
- `proxy`：本机直连建议显式不启用代理（`websockets>=15` 才有 `proxy` 参数，见 §12）。

### 6.3 反向 WS 服务端

```python
async with websockets.serve(
        handler,                                  # 新 asyncio API：handler(connection)
        host, port,
        process_request=self._check_token,        # 握手阶段鉴权
        max_size=..., ping_interval=..., ping_timeout=...):
    await forever                                 # 直到任务被取消
```

- 握手鉴权：从 `request.path` 的查询串或 `request.headers` 里取 token
  （`Authorization: Bearer`、`X-Access-Token`），不匹配时
  `return connection.respond(401, "Unauthorized\n")` 拒绝【实测可用】。
- 未配置 token 时不做校验（与 SnowLuma 默认行为一致）。
- 监听失败（端口占用）应记错误并按间隔重试，**不能让整个进程退出**。
- 允许多个账号同时接入（通道按 id 存在字典里）。

### 6.4 动作调用（核心：echo 应答匹配）

```
async def call_action(action, *, transport=None, timeout=None, **params):
    transport = transport or config.api_transport       # auto/ws/http
    channel = 挑一条通道（forward 优先） if transport in (auto, ws) else None
    if channel:
        echo   = uuid4().hex
        future = loop.create_future();  pending[echo] = future
        await channel.send_json({"action": action, "params": params, "echo": echo})
        payload = await wait_for(future, timeout)       # 超时 → ConnectionUnavailable
        return unwrap(action, payload)                  # retcode != 0 → ActionFailed
    if transport == "ws":  raise ConnectionUnavailable("没有可用的 WebSocket 通道")
    return await call_over_http(action, params, timeout)
```

**必须知道的三个坑**：

1. **单读者死锁**：WS 连接只能有一个协程在读。绝不能在读循环里 `await call_action()`
   （应答要由读循环投递到 future）。连接建立后的「登录探测」必须 `create_task` 成独立任务。
2. **不重复发送**：`api_transport=auto` 时，**只有「完全没有 WS 通道」才退到 HTTP**；
   WS 已发出但等待应答超时时**绝不**再走 HTTP，否则同一条消息会发两次。
3. **宽容匹配**：极少数实现不回填 `echo`。可以加一条兜底：报文没有 `post_type`
   且有 `status`/`retcode` 字段、且**在途请求恰好只有 1 个**时，按该请求的应答处理。

### 6.5 事件队列与背压

- 收到 `post_type` 报文 → 投递到 `asyncio.Queue`（容量 512~1024）。
- 队列满时**丢弃最旧事件**并告警（比阻塞读循环更好：阻塞会导致心跳/应答超时）。
- `meta_event` **不进队列**，由连接层自行消化（见 6.6）。
- 顺带做一件事：从 `message` 字段类型推断对端 `messageFormat`（`list`→array，`str`→string），
  发送时用它做格式自适应（§8.3）。

### 6.6 meta 事件与登录探测

- `lifecycle/connect|enable`：记成功日志，并把 `self_id` 记下来（payload 里有）。
- `heartbeat`：debug 级日志，可用于观察连接健康。
- **登录探测**：通道一建立（不论正向/反向）以及收到 lifecycle 时，触发一次
  `get_login_info`（`create_task`，且同一时刻只允许一次在途），成功后打印
  「Connected successfully! 当前机器人账号 …（昵称）」，再顺带 `get_version_info`
  打印协议端版本；若配置了 `device_name`，调用 `_set_model_show`。

---

## 7. 事件层设计

### 7.1 事件类结构

```
SenderInfo            # sender 字段：user_id/nickname/card/role/level/title/sex/age/display_name
MessageEvent          # 基类：message 与 message_sent 共用
├─ GroupMessageEvent
└─ PrivateMessageEvent
WaitingEvent        # 由某个事件转换而来，额外带 input_value
NoticeEvent(BaseModel)
RequestEvent(BaseModel)
```

工厂：`MessageEvent.from_payload(payload)` 按 `message_type` 返回对应子类。

### 7.2 双格式归一（关键设计）

对外（插件层）**统一暴露 CQ 码字符串**，对内保留消息段视图：

| 成员 | 语义 |
| --- | --- |
| `get_message` → `str` | CQ 码字符串（**插件现有代码依赖它**） |
| `get_message_segments` → `list[MessageSegment]` | 段视图 |
| `get_plain_text` → `str` | 只拼 text 段，便于命令匹配/日志 |
| `set_message(value)` | 接受 `str` 或段数组，两种都能存 |
| `get_raw_message` | 原始 `raw_message` |

实现要点：`array` 事件 → 段数组转 CQ 字符串；`string` 事件 → **原样保留服务端字符串**
（避免转义往返造成差异）。两条路径都要能 `set_message` 回去。

> 为什么插件层默认给 CQ 串、什么时候必须用段数组、用户内容如何避免 CQ 注入：
> 见 [ADR-0001：插件层的消息表示](adr/0001-message-representation.md)。

### 7.3 属性映射（与旧 API 完全兼容）

| 旧属性 | 新值 | 备注 |
| --- | --- | --- |
| `get_user_id` | `str(sender.user_id)` | 旧代码返回 str，**保持 str**，插件里都是 f-string/CQ 拼接 |
| `get_user_name` | `sender.nickname` | 注意不是群名片 |
| `get_user_group_name` | `sender.card` | 无名片时是 `""` |
| `get_group_id` | `str(group_id)` 或 `None` | **私聊必须返回 None 而不是报错** |
| `get_message_id` / `get_time` / `get_self_id` / `get_message_type` | 原样 | |
| `reply(content)` | `f"[CQ:reply,id={message_id}] {content}"` | 保持旧前缀格式 |
| 新增 | `get_sender`、`get_display_name`、`get_sub_type`、`get_post_type`、`is_group`、`is_private`、`is_self_message`、`get_payload`、`get_target_id` | |

`NoticeEvent` / `RequestEvent` 用 pydantic v2 模型（建议 `extra="allow"`，
协议端新增字段时不会炸），并提供 `get_notice_int_type` / `get_request_int_type`
（映射到 `htyping` 的枚举值，供响应器比较），未知类型返回 `None` 而不是 `KeyError`。

### 7.4 消息段与 CQ 码工具（`segment.py`）

```
MessageSegment(type, data)
  .from_dict(raw)  .from_cq(cq)  .to_dict()  .to_cq()
  .text() .at() .image() .face() .reply() .record() .video() .file()

parse_cq_to_segments(str) -> list[MessageSegment]     # 文本段也会保留
segments_to_cq(list) -> str
segments_to_dicts(list) -> list[dict]
normalize_segments(str|list|dict) -> list[MessageSegment]
normalize_cq(任意) -> str
message_format_of(message) -> "array" | "string" | None
message_to_payload(message, fmt) -> str | list[dict]   # 发送用
```

---

## 8. 发送与动作层设计

### 8.1 `Bot` 的对外契约（保持不变）

```python
class Bot:
    func                      # 当前触发的响应器（等待任务需要）
    connection                # 连接层实例（None 表示离线/调试）
    self_id / is_connected

    async def send(uid, message, mode="group", *, auto_escape=False) -> dict | None
    async def send_group(group_id, message) / send_private(user_id, message)
    async def reply(event, message)
    async def finish(uid, message, mode="group")     # 发送后 raise FinishException
    async def call_api(api, *, transport=None, timeout=None, **kwargs) -> Any
    async def input_value(user_id=None, group_id=None, type_=None)
    # 便捷封装：get_login_info / get_status / get_group_list / get_friend_list
    #           get_group_member_info / delete_msg
```

替换当前连接的入口：`api.set_connection(conn)` / `api.get_connection()`
（`main.py` 启动时登记；`debug.py` 登记离线假连接）。

### 8.2 发送流程

```
mode == "group" → message_type="group"，参数带 group_id
否则            → message_type="private"，参数带 user_id
（uid 兼容 str/int，非数字原样透传）
params = { message_type, message: <按格式转换后的载荷>, auto_escape,
           group_id 或 user_id }
data = await connection.call_action("send_msg", **params)
```

失败的语义（供插件层决策）：

- `ActionFailed`（retcode≠0，含风控文案）与 `ConnectionUnavailable`（无通道/超时）
  → **记警告日志并返回 `None`，不打断插件函数**（与旧行为一致，但日志要能看出原因）。
- `bot.finish()`：`try: await send(...) finally: raise FinishException`。
  `FinishException` 继承自 `BaseException`，执行封装里要**显式** `except FinishException`，
  否则会穿透 `except Exception`。

### 8.3 格式自适应策略

| 场景 | 出参 |
| --- | --- |
| `message_format = array` | 段数组 `[{"type": "text", "data": {"text": ...}}, ...]` |
| `message_format = string` | CQ 码字符串 |
| `message_format = auto` | 用最近一次**收到的事件**推断出的格式；还没收到过事件则默认 `array` |

理由：SnowLuma 两种都能收，但**跟随对端配置最稳**（避免对端在 string 模式下对 CQ 码
解析/routing 的差异），同时让日志里看到的就是对端真实使用的格式。

---

## 9. 运行层设计

### 9.1 单一事件循环

```
main():
    asyncio.run(main_async())

main_async():
    config = init()                     # 建/读 config/snowluma.json，打印脱敏摘要
    load_plugins(); refresh_funcs()      # 插件池 → loopFuncs / customFuncs / onstartupFuncs
    for f in onstartupFuncs: await await_run_func(f)     # on_startup 支持 async
    connection = OneBotConnection(config); set_connection(connection)
    await connection.start()             # 起正向/反向通道（不阻塞）
    安装信号处理（SIGINT/SIGTERM → stop_event.set）
    tasks = [event_loop, scheduled_loop, shutdown_watcher]
    await stop_event.wait()
    finally: 取消任务 → connection.stop() → 日志 Closed
```

- **信号**：Windows 上 `loop.add_signal_handler` 不可用，用 `signal.signal` +
  `loop.call_soon_threadsafe(stop_event.set)`。
- **优雅退出**：另提供 `api.shutdown()`（置 `to_shutdown` 标志），由一个
  `shutdown_watcher` 任务轮询后置 `stop_event`，方便插件主动要求退出。

### 9.2 事件分发

```
event_loop(connection):
    sem = Semaphore(event_workers)
    while True:
        payload = await connection.event_queue.get()
        create_task(guarded(payload))     # guarded 里 async with sem
```

每个事件内部的触发顺序（与旧版一致，保持行为可预测）：

```
message 事件：
  1. RunInLoop 函数（receive-only 钩子，如 XHuaLao 统计）
  2. custom 响应器（自定义判断函数）
  3. 等待任务池匹配（按 group_id + user_id，命中后从池中移除）
  4. check_whether_func 粗筛 → 按 priority 升序 → on_keyword / on_at / on_regex /
     on_command / on_waiting，命中后按 func.block 决定是否 break
notice 事件：按 notice_type 匹配，priority 排序，block 生效
request 事件（新增）：按 request_type 匹配
```

触发前的类型检查要**健壮**：读 `func._func.__annotations__.get("event")`，
注解缺失或无法 `isinstance`（例如插件用了 `from __future__ import annotations`）
时**保守放行**，不要直接抛 `KeyError` / `TypeError`。

### 9.3 等待任务（on_waiting）语义

- 触发 `on_waiting` 时向等待池加入 `WaitingTask(child_func, user_id, group_id)`，
  然后执行父函数；父函数里 `bot.input_value()` 再追加（`CreateOnWaitingTask`）。
- 后续消息到来时，遍历等待池，**同时**比较 `group_id` 与 `user_id`，命中即构造
  `WaitingEvent`（群聊里 `group_id` 是群号、`user_id` 是发言人，**不能错位**），
  需要输入内容时设置 `input_value`，执行完成后把任务出池。

### 9.4 计划任务（on_scheduled）

修正判定逻辑（旧实现基本失效）：

- `fixed_execute_time` 非空 → 按时间串匹配（`str == stamp` 或 `stamp.endswith(fixed)`，
  支持 `HH:MM` / `HH:MM:SS` / 完整格式），且同一秒内不重复执行。
- 否则按 `frequency`（秒）与 `last_execution_time` 求差；`frequency <= 0` 建议兜底为 1s。
- `task_type == "shell"` 走 `popen`；函数任务若返回 awaitable 要 `await`。
- `disposable=True` 执行一次后从池中移除。

---

## 10. 必须修正的既有缺陷

实现时逐条对照，每条都要有验证点：

| # | 缺陷 | 修法要点 | 验证点 |
| --- | --- | --- | --- |
| 1 | 硬编码 `1696/9920` 端口 | 配置化 + SnowLuma 目录发现 | 改 SnowLuma 端口后无需改代码 |
| 2 | 无 token 鉴权 | 正向/HTTP 带 Bearer+query；反向握手校验并 401 拒绝 | 错 token 连不上；对 token 正常 |
| 3 | 同步 `httpx` 阻塞循环 | `httpx.AsyncClient` 单一实例 | 长动作不阻塞收消息 |
| 4 | 每事件 `asyncio.run()` | 单一事件循环 + 队列分发 | 连接状态跨事件共享 |
| 5 | `array` 格式事件被当成字符串 | `normalize_cq` / `normalize_segments` | array 事件能命中命令并 @ 回复 |
| 6 | 私聊事件 `KeyError: group_id` | `.get("group_id")`，缺省 None | 私聊消息可正常分发 |
| 7 | `WaitingEvent` group/user 错位 | 直接沿用原事件的 id | 群聊等待任务能匹配到正确的人 |
| 8 | `ImageSegment` 生成 `[CQ:img]` | 改为 `[CQ:image]` | 发图不报错 |
| 9 | `call_api` 从未发请求、不看 retcode | 走 `call_action`，`retcode!=0` 抛 `ActionFailed` | 未知动作能看到 1404 |
| 10 | 计划任务定时判定错误 | 见 §9.4 | 定时任务按预期触发一次 |
| 11 | `init(False)` 跳过配置检查 | `init()` 始终读配置并打印摘要 | 启动日志里有连接摘要 |
| 12 | `message_sent` / `request` 事件被丢弃 | 新增分发分支 | 自消息与加群请求有日志/可响应 |
| 13 | `check_whether_func` 用 `str.startswith(list)` | 归一为 tuple（list 会 `TypeError`） | 有 `on_command` 插件时不再抛异常 |
| 14 | 日志文件被写到 `plugins/logs/` | 见 §12 的 cwd 坑 | 日志只出现在项目根的 `logs/` |

---

## 11. 测试与验收方案

### 11.1 自建 mock 协议端（强烈建议先写这个）

用一个不依赖 SnowLuma 的 mock 服务端（`websockets` 起正向 WS + `http.server` 起 HTTP API），
即可在 CI/本地反复验证。**建议 39 项断言**，分组如下：

> 具体搭建步骤、可直接运行的完整代码与端口选择注意点，见配套教程
> [M3 教程：自建 SnowLuma mock 协议端](m3-mock-snowluma-tutorial.md)。

**A. 正向 WS + 动作（12 项）**

| # | 检查 |
| --- | --- |
| 1 | 带正确 token 能建立正向连接 |
| 2 | 连接后自动 `get_login_info`，`self_id` 正确 |
| 3 | `device_name` 非空时调用 `_set_model_show` 且参数为 `{model, model_show}` |
| 4 | `get_version_info` 结果被解析（app_name / protocol_version） |
| 5 | `lifecycle/connect` 与 `heartbeat` 不进入事件队列 |
| 6 | `echo` 应答能正确配对（并发多个动作不串台） |
| 7 | 应答缺少 `echo` 且只有一个在途请求时仍能配对 |
| 8 | `retcode != 0` → 抛 `ActionFailed`，带 status/retcode/wording |
| 9 | 无应答 → 超时抛 `ConnectionUnavailable`，且耗时 ≈ timeout |
| 10 | 未知动作（1404）按失败处理 |
| 11 | WS 断开后所有在途请求立即失败（不会悬挂） |
| 12 | `connection.connected` 随通道增删正确变化 |

**B. 事件分发（11 项）**

| # | 检查 |
| --- | --- |
| 13 | `array` 格式群消息命中 `on_command` |
| 14 | 命中后 `bot.send` 真的发出 `send_msg` |
| 15 | `send_msg` 的 `message_type=group` 且带 `group_id` |
| 16 | `send_msg` 的 `auto_escape` 默认 `False` |
| 17 | `array` 事件触发时发送载荷也是段数组 |
| 18 | `array` 事件被识别为 `array`（格式推断） |
| 19 | `string` 事件被识别为 `string` 且发送回退为 CQ 字符串 |
| 20 | 私聊消息按 `message_type=private` + `user_id` 发送，且**不带 group_id** |
| 21 | `notice/group_increase` 命中 `on_notice` 并正确 @ 新成员 |
| 22 | `request/group/add` 命中 `on_request` 且 `comment` 可用 |
| 23 | `message_sent` 不报错且被分发 |

**C. 反向 WS（6 项）**

| # | 检查 |
| --- | --- |
| 24 | 错误 token 被 401 拒绝 |
| 25 | 正确 token 接入成功，`connected=True` |
| 26 | 通过反向通道发 `send_msg` 能拿到应答 |
| 27 | 反向通道收到的事件进入队列 |
| 28 | 反向通道接入时也做登录探测 |
| 29 | 多个反向连接互不影响（多账号） |

**D. HTTP 兜底（5 项）**

| # | 检查 |
| --- | --- |
| 30 | 无 WS 通道时自动走 HTTP |
| 31 | HTTP 请求带 `Authorization: Bearer` |
| 32 | HTTP 打到 `/{action}`（如 `/send_msg`） |
| 33 | HTTP 请求体就是 params（不是 `{action, params}` 包裹） |
| 34 | `transport="ws"` 且无通道时抛 `ConnectionUnavailable`（不偷偷走 HTTP） |

**E. 配置发现（5 项）**

| # | 检查 |
| --- | --- |
| 35 | 从 `wsServers` 得到正向 url/token |
| 36 | 从 `httpServers` 得到 http_base/token |
| 37 | 从 `wsClients` 反推出反向 port/token |
| 38 | `0.0.0.0` 被替换为 `127.0.0.1` 用于直连 |
| 39 | HysialX 配置里的显式值覆盖自动发现 |

### 11.2 真实实例只读验收（9 项）

对着真实 SnowLuma（**只调用只读动作**）：

```
正向 WS 连接成功
get_login_info      → {"user_id": ..., "nickname": ...}      【实测通过】
get_version_info    → {"app_name":"SnowLuma","app_version":"1.14.19-node","protocol_version":"v11"}  【实测通过】
get_status          → {"online": true, "good": true}          【实测通过】
get_group_list      → list（本机 9 个群）                      【实测通过】
get_friend_list     → list（本机 24 个好友）                   【实测通过】
未知动作            → ActionFailed(status=failed, retcode=1404)【实测通过】
HTTP API 通道       → get_status 同样可用                       【实测通过】
连接正常关闭
```

### 11.3 端到端（真实插件）

用 mock 协议端跑真实 `main.py`：

1. 启动后能连上并完成登录探测；
2. 推一条 `echo hello` 群消息 → Defalut 的 `on_regex("echo(.*)")` 回复 `hello`；
3. 推一条 `group_increase` 通知 → Defalut 的欢迎语发出；
4. 主循环与计划任务不崩；
5. `api.shutdown()` 能在 15s 内优雅退出。

### 11.4 手工验收

```bash
# 1) 真实 SnowLuma 联调（只读）
python main.py            # 观察日志：连接成功 / 账号 / 协议端版本 / 收发日志

# 2) 群里发一条命令（如 "echo hi"、"菜单"）
# 3) 关掉 SnowLuma 再看日志：应有断线告警 + 指数退避重连，进程不退出
# 4) 重开 SnowLuma：应自动恢复
# 5) Ctrl+C：应打印 Closed 并干净退出
```

> ⚠️ **测试前务必备份 `DataForXPlugin/*.json`**！
> `plugins/XHuaLao/main.py` 的 `@RunInLoop` 统计函数会在**每条消息**上写
> `GroupStatistics.json` / `GroupRecordingTime.json`；`plugins/t` 的“签到/个人信息”
> 会写 `qian_dao_.json` / `wealth.json`（后者会把 `all.json` 的内容覆盖到 `wealth.json`）。
> 我用 mock 与真实实例测试时，这些数据文件被真实地追加/覆盖过，最后是靠 `git checkout` 还原的。

---

## 12. 已知坑与注意事项

1. **websockets 版本**：`websockets>=14` 才能用顶层 `websockets.connect` / `websockets.serve`
   的新 asyncio 实现；Header 参数名是 `additional_headers`（旧版叫 `extra_headers`）。
   新 API 的 `serve` handler **只接收一个 `ServerConnection` 参数**（旧版是 `(ws, path)`）。
   `proxy` 参数 **websockets>=15** 才有（本机 16.0），写代码时要么跳过它，要么做版本判断。
   反向握手拒绝用 `connection.respond(401, "Unauthorized\n")`。
2. **`retcode` 优先于 HTTP 状态码**：`HTTP 200` + `retcode=100` 是失败。
3. **单读者**：WS 只能一个协程 `recv()`；所有动作应答靠 future 投递（见 §6.4 坑 1）。
4. **不要二次发送**：WS 超时后不要再走 HTTP（见 §6.4 坑 2）。
5. **id 类型**：协议里 id 是数字，但插件历史代码传字符串；`get_user_id`/`get_group_id`
   返回 `str` 以兼容旧插件，发往协议端前再转 `int`（非数字则原样透传）。
6. **`FinishException` 继承 `BaseException`**：`except Exception` 抓不到它，
   执行封装里要显式捕获，否则会穿透到分发层。
7. **loguru + cwd**：`log.py` 里的文件 sink 用的是相对路径 `./logs/HysialLog.log`，
   而 `load_plugins()` 会 `os.chdir("plugins")`。如果此时才触发 sink 打开，
   就会生成 `plugins/logs/`。建议：加载插件用 `try/finally` 恢复 cwd，
   或把日志路径改为基于项目根目录的绝对路径。
8. **`logger.catch` 与 async**：loguru 的 `logger.catch` 支持协程函数，但会吞掉异常栈
   到日志里；调试阶段建议少用装饰器、多用显式 `try/except` + `logger.exception`。
9. **pydantic v2**：`NoticeEvent` / `RequestEvent` 建议 `model_config = ConfigDict(extra="allow")`，
   并用 `model_validate`（不是 `parse_obj`）；字段缺失要靠 `Optional` + 默认值兜底，
   否则协议端加字段/降级时会直接抛 `ValidationError`。
10. **Windows 信号**：`loop.add_signal_handler` 不可用；用 `signal.signal` +
    `loop.call_soon_threadsafe`。被强杀时进程退出码可能是 1，不代表代码错。
11. **心跳**：`ping_interval/ping_timeout` 由客户端维护；SnowLuma 侧也会发 heartbeat
    meta 事件，两者别混为一谈。
12. **max_size**：事件里可能带 base64 图片，默认 1MB 会直接断连；建议放宽到 16MB。
13. **插件数据污染**：见 §11.4 的警告。
14. **依赖清理**：改造后 `main.py` 不再需要 `websocket-client`，`requirements.txt`
    应改为 `websockets>=14`；同时别忘 `httpx`。

---

## 13. 分阶段实施建议

每个阶段都能独立验收，建议按此顺序提交：

| 阶段 | 目标 | 验收 |
| --- | --- | --- |
| 1 | `snowluma/segment.py` + `exception.py` | 单测：CQ ⇄ 段数组 round-trip；转义字符；`message_to_payload` 两种格式 |
| 2 | `snowluma/config.py` | 单测：发现规则 5 项（§11.1-E）+ 环境变量覆盖 + 脱敏摘要 |
| 3 | `snowluma/connection.py` 正向 WS + 动作 | mock 正向：§11.1-A 12 项 |
| 4 | 反向 WS + HTTP 兜底 | mock：§11.1-C 6 项 + D 5 项 |
| 5 | `api/event.py` + `api/utils.py` | mock 事件：§11.1-B 前 6 项 |
| 6 | `api/bot.py` + `snowluma` 发送路径 | mock：§11.1-B 剩余项 + 真实实例只读 9 项 |
| 7 | `main.py` 运行层 + `script.py` + `debug.py` | e2e：§11.3 五项 |
| 8 | 真实 SnowLuma 联调 + 文档更新 | §11.4 手工验收 |

建议只在第 6 阶段之后再连真实 QQ 账号；前面全部用 mock 跑通。

> 分阶段教程：[M6 事件层教程](m6-event-layer-tutorial.md)（兼容性契约、逐步实现、24 条验收断言）、
> [M7 发送层教程](m7-bot-layer-tutorial.md)（`Bot` 契约、失败语义、`reply`/`finish`/`input_value` 的坑、16 条验收断言）、
> [M8 运行层教程](m8-runtime-layer-tutorial.md)（单事件循环、队列并发分发、优雅退出、计划任务、调试台重写、8 条分发断言）。

---

## 14. 附录：实测证据与事件样例

### 14.1 真实 SnowLuma 应答样例【实测】

```jsonc
// 请求（WS）
{"action": "get_login_info", "params": {}, "echo": "e1"}
// 应答
{"status": "ok", "retcode": 0, "data": {"user_id": 3508166608, "nickname": "Hysial"}, "message": "", "wording": "", "echo": "e1"}

{"action": "get_version_info"} →
{"status":"ok","retcode":0,
 "data":{"app_name":"SnowLuma","app_version":"1.14.19-node","protocol_version":"v11"}}

{"action": "get_status"} → {"status":"ok","retcode":0,"data":{"online":true,"good":true}}

// 未知动作
{"status": "failed", "retcode": 1404, "data": null, "message": "unknown action"}
```

### 14.2 事件样例

```jsonc
// 群消息（messageFormat=array）
{
  "post_type": "message", "message_type": "group", "sub_type": "normal",
  "time": 1699108463, "self_id": 3592797817, "message_id": -1763953745,
  "group_id": 859874709, "user_id": 169699201, "font": 0,
  "message": [{"type": "text", "data": {"text": "echo hi"}},
              {"type": "at", "data": {"qq": "3592797817"}}],
  "raw_message": "echo hi[CQ:at,qq=3592797817]",
  "sender": {"user_id": 169699201, "nickname": "雨弈", "card": "群名片", "role": "owner", "level": "", "title": ""},
  "anonymous": null
}

// 私聊消息（注意没有 group_id）
{
  "post_type": "message", "message_type": "private", "sub_type": "friend",
  "time": 1699108463, "self_id": 3592797817, "message_id": 54321,
  "user_id": 169699201, "message": "hi", "raw_message": "hi",
  "sender": {"user_id": 169699201, "nickname": "雨弈", "sex": "unknown", "age": 24}
}

// 通知：入群
{"post_type":"notice","notice_type":"group_increase","sub_type":"approve",
 "time":1699108463,"self_id":3592797817,"group_id":859874709,"user_id":88888,"operator_id":3592797817}

// 请求：加群
{"post_type":"request","request_type":"group","sub_type":"add",
 "time":1699108463,"self_id":3592797817,"group_id":859874709,"user_id":77777,
 "comment":"求进群","flag":"flag-1"}

// meta：生命周期（真实 SnowLuma 连接后会连发 connect 与 enable）
{"post_type":"meta_event","meta_event_type":"lifecycle","sub_type":"connect",
 "time":1699108463,"self_id":3508166608}

// meta：心跳
{"post_type":"meta_event","meta_event_type":"heartbeat","time":1699108463,
 "self_id":3508166608,"interval":5000,"status":{"online":true,"good":true}}
```

### 14.3 参考链接

- 配置参考：<https://snowluma.github.io/zh/docs/guide/configuration>
- 动作参考：<https://snowluma.github.io/zh/docs/api>
- 对接机器人：<https://snowluma.github.io/zh/docs/guide/connect-bot>
- 开发者文档（生命周期/模块边界）：<https://snowluma.github.io/zh/docs/guide/developer>
- 协议规范：<https://github.com/botuniverse/onebot-11>
- 主仓 README：<https://github.com/SnowLuma/SnowLuma>
