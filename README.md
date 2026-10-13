# HysialX
此项目为学习项目_

使用 python 3.10 及以上
__详细教程请访问[我的主页](https://xinre.top/2023/09/02/hysialx-%E4%B8%80%E4%B8%AA%E7%AE%80%E6%98%93%E7%9A%84qq%E6%9C%BA%E5%99%A8%E4%BA%BA%E6%A1%86%E6%9E%B6 "我的主页")__

一个简易的qq机器人框架，可自行编写插件实现诸多功能
__本框架可对接所有实现 OneBot 标准的服务端__（当前主要适配 [SnowLuma](https://github.com/SnowLuma/SnowLuma)）

# 安装与启动
```bash
pip install -r requirements.txt      # 依赖含版本下限，见文件内注释
python main.py                       # 首次运行会生成 config/snowluma.json
```
- 连接配置全部在 `config/snowluma.json`：`mode`（`forward` 主动连 / `reverse` 接收反向 / `both`）、
  `snowluma_dir`（指向 SnowLuma 安装目录可自动发现端口与 token）、`message_format`（`auto`/`array`/`string`）、
  `api_transport`（`auto`/`ws`/`http`）。空字符串 / `null` / `0` 表示「跟 SnowLuma 或内置换算」。
- 也可用环境变量覆盖（便于测试与多账号）：`SNOWLUMA_FORWARD_WS`、`SNOWLUMA_FORWARD_TOKEN`、
  `SNOWLUMA_HTTP_BASE`、`SNOWLUMA_HTTP_TOKEN`、`SNOWLUMA_MODE`、`SNOWLUMA_REVERSE_TOKEN`、`SNOWLUMA_MESSAGE_FORMAT`、`SNOWLUMA_DIR`。
- 插件数据目录：`DataForXPlugin/`（由 `api.DEFAULT_PLUGINS_DATA_PATH` 决定，相对路径按仓库根解析）。

## 插件需要的环境变量（不配置则对应插件功能不可用，但不会影响启动）
| 变量 | 用途 |
| --- | --- |
| `WALLHAVEN_API_KEY` | `plugins/Xpic` 搜图（**必须自己去 wallhaven 申请**） |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | `plugins/chatgpt`（base_url 缺省为官方地址，可指向中转） |
| `CHROMEDRIVER_PATH` | `plugins/XHuaLao` 排行榜截图（缺省用 `PATH` 里的 `chromedriver`） |

# Lagrange / go-cqhttp 配置（历史文档，当前主用 SnowLuma）
<details>
<summary>展开旧的 Lagrange 配置示例</summary>

您需要在`appsettings.json`的`Implementlations`中添加
```json
{
      "Type": "ForwardWebSocket",
      "Host": "127.0.0.1",
      "Port": 1696,
      "Suffix": "/event",
      "ReconnectInterval": 5000,
      "HeartBeatInterval": 5000,
      "AccessToken": ""
},
{
      "Type": "Http",
      "Host": "*",
      "Port": 9920,
      "AccessToken": ""
}
```
go-cqhttp 的 `config.yml` 配置方式已弃用，不再维护。
</details>

# 插件编写
_本框架提供了几个示例插件供参考_  
本qq机器人框架插件应为标准python包, 且需置于<code>plugins</code>文件夹中

>为更好地使用与插件信息相关的api，用户需在插件中(最好在__init__.py中)添加如下常量&nbsp;&nbsp;_当然这是可选的_
```python
__plugin_meta__ = PluginMeta(
    PluginName,
    PluginFuncs,
    PluginUsage,
    PluginAuthor,
    PluginDescription
) # PluginMeta 在 plugins.manager 中，请自行导入
```

>插件函数需按以下模版进行编写
```python
@对应响应方式
async def test(bot: Bot, event: Event):
    ...
    await bot.send(event.get_group_id, to_send_message)
```

>为将命令与触发函数绑定，您需要给触发函数添加响应装饰器，这样框架将在加载插件时，将触发函数信息注册到函数池中，便于调用。
>以下为各种响应器使用方式：
```python
@on_command("命令")
@on_keyword("关键字")   # 匹配方式是 message.startswith(keyword)
@on_at()               # @机器人；不参与粗筛，由 main.py 在消息里检测到 [CQ:at,qq=机器人] 时触发
@on_regex("正则")       # 有捕获组时 event.get_message 会被换成第 1 组
@on_waiting("命令")     # 注册等待事件；配 add_child_func(父函数, 子函数)，子函数里用 event.input_value 取值
@on_startup            # 插件全部加载完毕后运行一次
@on_notice(...) / @on_request(...)
@RunInLoop             # 每条消息都会跑（用于统计这类钩子）
@custom(自定义响应函数) # 自定义匹配；匹配函数收到的是**原始**纯文本（保留前导空格语义）
```

>__匹配语义（容易踩的两点）__
>- 命令/关键字/正则匹配用的是**去掉 @机器人 前缀**的文本（`"@机器人 菜单"` 能命中 `@on_command("菜单")`）。
>- 等待任务：群聊传 `group_id`、私聊传 `user_id`（两个都不传会告警且永不触发）；
>  `on_waiting` 命中时框架会自动入池，处理器里再调 `bot.input_value()` 是幂等的。

>__API__
>本框架提供了如下api供用户使用(所有api均位于包 api 中)
```python
Bot.send(uid, message, mode="group", *, auto_escape=False)   # 失败只记日志并返回 None
Bot.send_group(group_id, message) / Bot.send_user(user_id, message) / Bot.send_private(...)
Bot.reply(event, message)          # 引用回复
Bot.finish(uid, message, mode)     # 发完抛 FinishException，终止当前插件函数
Bot.call_api(action, **params)     # 需要数据用这个：失败会抛（ActionFailed / ConnectionUnavailable）
Bot.input_value(user_id=None, group_id=None, type_=None)
set_device(device_name: str) -> bool
get_func_pool() / get_plugin_pool() / get_notice_func_pool() / get_request_func_pool()
get_waiting_task_pool() / get_scheduled_task_pool()
getExpectedFuncs(funcs_pool: FuncPool, expected_type: str) -> FuncPool
At(qq) / AtAll() / Text(s) / Reply(mid) / ImageSegment(file) ...   # 返回 CQ 串(str)，可直接拼进消息
api.shutdown()                     # 请求退出；轮询请用 api.is_shutdown_requested()
```
>__注意__：`from api import to_shutdown` 拿到的是导入时的**副本**（永远 False），
>判断退出请求请用 `api.is_shutdown_requested()`。

# 插件调试
与 `main.py` 同目录下的 `debug.py` 可以模拟qq客户端的收发消息，缩短插件调试时间
```bash
python debug.py                 # 会执行 on_startup（XHuaLao 会占用 1145 端口）
python debug.py --no-startup    # 跳过 on_startup，只进控制台
```
常用命令（完整列表见 `help`）：

| 命令 | 说明 |
| --- | --- |
| `build $msg echo 你好 -type=group -to=859874709 -format=array` | 造一条消息事件存进变量 |
| `send $msg [次数]` / `array 菜单` | 投递给真实分发链（不联网，只打印日志） |
| `notice group_increase` / `request group` / `sent 我在测试` | 造通知 / 请求 / 自己发的消息 |
| `conn` / `fail on|off` | 查看调试连接 / 注入发送失败（验证 `send` 吞异常、`call_api` 抛异常） |
| `pool` / `clear` / `plugins` / `reload` | 等待任务池 / 清空 / 插件列表 / 真正重载插件 |

# 测试
```bash
python -m pytest tests/ -q -W error::RuntimeWarning
```
用例覆盖段解析与转义、事件层、响应器分发（`on_at` / `@机器人 命令` / 等待任务链）、
`Bot` 各发送路径、连接层 echo 匹配与超时、调试台链路、以及 `main_async` 启动/关停烟测。
测试会把插件数据目录重定向到临时目录，**不会**写你的 `DataForXPlugin/`。
