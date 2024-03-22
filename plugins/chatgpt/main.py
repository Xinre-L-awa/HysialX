import psutil
from openai import OpenAI

from api import (
    Bot,
    Event,
    At,
    on_at,
    on_command
)

client = OpenAI(
    # defaults to os.environ.get("OPENAI_API_KEY")
    api_key="sk-DuG5Ml5suYY3yfLFNrdIzN5N8amjoXabnEd6bpZx0t8NnKb0",
    base_url="https://api.chatanywhere.tech/v1"
)

# 非流式响应
def gpt_35_api(messages: list):
    """为提供的对话消息创建新的回答

    Args:
        messages (list): 完整的对话消息
    """
    completion = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    print(completion.choices[0].message.content)
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


@on_at()
async def chat(
    bot: Bot,
    event: Event
):
    await bot.send(
        event.get_group_id,
        event.reply(At(event.get_user_id) + gpt_35_api([{'role': 'user','content': event.get_message}]))
    )


@on_command("服务器状态")
async def get_server_info(
    bot: Bot,
    event: Event
):
    psutil.cpu_percent(None)

    await bot.send(
        event.get_group_id,
        f"当前服务器CPU使用率: {psutil.cpu_percent()} 内存占用率: {psutil.virtual_memory().percent}"
    )
