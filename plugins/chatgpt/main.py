import os
from urllib.parse import quote

import httpx
import psutil
from loguru import logger
from openai import AsyncOpenAI


from api import (
    Bot,
    MessageEvent,
    At,
    on_at,
    on_command,
    get_func_pool
)

# 密钥与地址都从环境变量读，官方地址兜底；不再硬编码第三方 base_url 与假 key
_api_key = os.environ.get("OPENAI_API_KEY")
_base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"

# 按需创建：没配 key 时不要让 import 阶段就抛，交给下面的处理器友好回复"未配置"
client = AsyncOpenAI(api_key=_api_key, base_url=_base_url) if _api_key else None
if not _api_key:
    logger.warning(
        "未配置环境变量 OPENAI_API_KEY，ChatGPT 问答功能将不可用。"
        "设置方法（Windows）：setx OPENAI_API_KEY \"sk-...\"；"
        "如需第三方兼容网关，另设 OPENAI_BASE_URL（默认 https://api.openai.com/v1）"
    )

# 非流式响应
async def gpt_35_api(messages: list):
    """为提供的对话消息创建新的回答

    Args:
        messages (list): 完整的对话消息
    """
    completion = await client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    return completion.choices[0].message.content

async def gpt_35_api_stream(messages: list):
    """为提供的对话消息创建新的回答 (流式传输)

    Args:
        messages (list): 完整的对话消息
    """
    # 客户端换成了 AsyncOpenAI，这里也必须 await / async for（名字保持不变）
    stream = await client.chat.completions.create(
        model='gpt-3.5-turbo',
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            print(chunk.choices[0].delta.content, end="")


current_mode = "answer_question"

@on_command("/switch")
async def switch_(
    bot: Bot,
    event: MessageEvent
):
    global current_mode

    func1 = None
    for func in get_func_pool():
        if func.name == "answer_question":
            func1 = func

    if func1 is None:
        await bot.send(event.get_group_id or event.get_user_id,
                       "切换失败：没有找到 answer_question 响应器（插件可能没加载成功）")
        return

    if current_mode == "answer_question":
        func1.set_priority(3)
        current_mode = "chat"
    else:
        func1.set_priority(1)
        current_mode = "answer_question"

    # 私聊时 get_group_id 是 None，按"群"发会静默丢消息
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, f"切换成功，当前为 {current_mode} 模式")
    else:
        await bot.send(event.get_user_id, f"切换成功，当前为 {current_mode} 模式", "private")


@on_at(block=True)
async def answer_question(
    bot: Bot,
    event: MessageEvent
):
    if client is None:
        await bot.send(
            event.get_group_id,
            event.reply(At(event.get_user_id) + "ChatGPT 未配置：请先设置环境变量 OPENAI_API_KEY 后重启")
        )
        return

    # 用的是 AsyncOpenAI：请求在事件循环里 await，不会像同步客户端那样阻塞数秒
    answer = await gpt_35_api([{'role': 'user','content': event.get_message}])
    await bot.send(
        event.get_group_id,
        event.reply(At(event.get_user_id) + answer)
    )


@on_at(block=True, priority=2)
async def chat(
    bot: Bot,
    event: MessageEvent
):
    # 日志提醒：聊天内容会原样发给第三方（api.qingyunke.com）
    logger.warning(f"青云客聊天：会把用户消息内容发送给第三方 api.qingyunke.com（用户 {event.get_user_id}）")

    # https://api.qingyunke.com 实测不可用（连接被拒），http 才通，所以这里只能继续用 http。
    # 明文的代价：必须把参数做 URL 编码，否则消息里的 & = # 会把 query 截断/篡改。
    url = "http://api.qingyunke.com/api.php"
    params = {"key": "free", "appid": "0", "msg": quote(event.get_message, safe="")}
    async with httpx.AsyncClient() as http_client:
        res = await http_client.get(url, params=params)

    res_json = res.json()
    # 先取变量再拼串：避免 PEP 701 的嵌套同引号 f-string（Python 3.10 不支持）
    content = res_json["content"]
    await bot.send(
        event.get_group_id,
        f"{At(event.get_user_id)} {content}"
    )


# 注意：`服务器状态` 的另一份注册在 plugins/Defalut/main.py:47（那边群聊/私聊都处理），
# 这里不再重复注册（否则同一命令双回复）。详见本次修复报告。
