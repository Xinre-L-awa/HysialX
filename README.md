# HysialX
一个简易的qq机器人框架，可自行编写插件实现诸多功能
# 插件编写
本qq机器人框架插件应为标准python包, 且需至于<code>plugins</code>文件夹中

插件函数需按以下模版进行编写
<pre><code>async def test(send_func: Callable, group_id, sender_id, sender_name, message):
    ...
    await send_func(group_id, message)
</code></pre>
其中 send_func 为发信函数，您可自行编写。默认 send_func 为 script.py 里的 sends 函数
##命令绑定
为将命令与触发函数绑定，您需要按照以下模版进行编写
<pre><code>
func_dict = {
    "触发器名称": [
        对应函数名,
        "触发方式"
    ],
    ...
}
</code></pre>
其中触发方式包括 <code>on_command</code> <code>on_keyword</code>

注: 推荐将该字典置于__init__.py中
