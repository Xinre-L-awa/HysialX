import httpx
import psutil
from openai import OpenAI


from api import (
    Bot,
    MessageEvent,
    At,
    on_at,
    on_command,
    get_func_pool
)

client = OpenAI(
    # defaults to os.environ.get("OPENAI_API_KEY")
    api_key="your key",
    base_url="https://api.chatanywhere.tech/v1"
)

# 非流式响应
def gpt_35_api(messages: list):
    """为提供的对话消息创建新的回答

    Args:
        messages (list): 完整的对话消息
    """
    completion = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    return completion.choices[0].message.content

def gpt_35_api_stream(messages: list):
    """为提供的对话消息创建新的回答 (流式传输)

    Args:
        messages (list): 完整的对话消息
    """
    stream = client.chat.completions.create(
        model='gpt-3.5-turbo',
        messages=messages,
        stream=True,
    )
    for chunk in stream:
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
    
    if current_mode == "answer_question":
        func1.set_priority(3)
        current_mode = "chat"
    else:
        func1.set_priority(1)
        current_mode = "answer_question"
    
    await bot.send(
        event.get_group_id,
        f"切换成功，当前为 {current_mode} 模式"
    )


@on_at(block=True)
async def answer_question(
    bot: Bot,
    event: MessageEvent
):
    await bot.send(
        event.get_group_id,
        event.reply(At(event.get_user_id) + gpt_35_api([{'role': 'user','content': event.get_message}]))
    )


@on_at(block=True, priority=2)
async def chat(
    bot: Bot,
    event: MessageEvent
):
    async with httpx.AsyncClient() as client:
        res = await client.get(f"http://api.qingyunke.com/api.php?key=free&appid=0&msg={event.get_message}")
        await bot.send(
            event.get_group_id,
            f"{At(event.get_user_id)} {res.json()["content"]}"
        )


@on_command("服务器状态")
async def get_server_info(
    bot: Bot,
    event: MessageEvent
):
    psutil.cpu_percent(None)

    await bot.send(
        event.get_group_id,
        f"当前服务器CPU使用率: {psutil.cpu_percent()} 内存占用率: {psutil.virtual_memory().percent}"
    )
