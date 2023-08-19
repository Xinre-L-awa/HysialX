import psutil
from api import (
    Bot,
    Event,
    on_command
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
