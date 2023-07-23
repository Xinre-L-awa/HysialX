# HysialX
一个简易的qq机器人框架，可自行编写插件实现诸多功能
# 插件编写
本qq机器人框架插件函数需按以下模版进行编写
<pre><code>async def test(send_func: Callable, group_id, sender_id, sender_name, message):
    ...
    await send_func(group_id, message)
</code></pre>
其中 send_func 为发信函数，您可自行编写。原 send_func 为 script.py 里的 sends 函数
