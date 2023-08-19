# HysialX
一个简易的qq机器人框架，可自行编写插件实现诸多功能
__本框架依赖于go-cqhttp运行__
# go-cqhttp配置
您需要在config.yml中添加
```
- ws-reverse:
      universal: ws://0.0.0.0:8080/hysialx/event
      reconnect-interval: 3000
      middlewares:
        <<: *default # 引用默认中间件
```
# 插件编写
_本框架提供了几个示例插件供参考_  
本qq机器人框架插件应为标准python包, 且需置于<code>plugins</code>文件夹中

>为更好地使用与插件信息相关的api，用户需在插件中(最好在__init__.py中)添加如下常量&nbsp;&nbsp;_当然这是可选的_
```
__plugin_meta__ = PluginMeta(
    PluginName,
    PluginFuncs,
    PluginUsage,
    PluginAuthor,
    PluginDescription
) # PluginMeta 在 plugins.manager 中，请自行导入
```

>插件函数需按以下模版进行编写
```
@对应响应方式
async def test(bot: Bot, event: Event):
    ...
    await bot.send(event.get_group_id, to_send_message)
```

>为将命令与触发函数绑定，您需要给触发函数添加响应装饰器，这样框架将在加载插件时，将触发函数信息注册到函数池中，便于调用。
>以下为各种响应器使用方式：
```
@on_command("命令")
@on_keyword("命令")
@on_startup            # 被该装饰器装饰的函数将在插件全部加载完毕后首先运行，且只允许一次
@RunInLoop             # 被该装饰器装的是函数将在消息事件循环中循环运行
@custom(自定义响应函数) # 该装饰器允许用户自定义响应方式(自定义响应函数 仅能够接收一个参数，即接收到的消息)，在示例插件中有实际应用(详见 plugins.Default.main.echo_)，
```
>__API__
>本框架提供了如下api供用户使用(所有api均位于包 api 中)
```
set_device(device_name: str) -> None
get_func_pool() -> FuncPool
get_plugin_pool() -> PluginPool
get_waiting_pool() -> WaitingPool #该api尚无实际用途
getExpectedFuncs(funcs_pool: FuncPool, expected_type: str) -> FuncPool
```
