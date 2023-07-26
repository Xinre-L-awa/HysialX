# HysialX
一个简易的qq机器人框架，可自行编写插件实现诸多功能
__本框架基于go-cqhttp运行__
# go-cqhttp配置
您需要在config.yml中添加
# 插件编写
_本框架提供了几个示例插件供参考_  
本qq机器人框架插件应为标准python包, 且需置于<code>plugins</code>文件夹中

插件函数需按以下模版进行编写
<pre><code>async def test(bot: Bot, event: Event):
    ...
    await bot.send(event.get_group_id, to_send_message)
</code></pre>

>为将命令与触发函数绑定，您需要按照以下模版进行编写
<pre><code>func_dict = {
    "触发器名称": [
         对应函数名,
         "触发方式",
         "正则表达式"
     ],
     ...
}</code></pre>
触发方式包括 <code>on_command</code> <code>on_keyword</code> <code>on_regex</code>  
其中 <code>"正则表达式"</code> 仅当触发方式为 <code>on_regex</code> 时需要填写

注: 推荐将该字典置于__init__.py中
