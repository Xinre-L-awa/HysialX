from loguru import logger
from random import choice

import wallhavenapi
from api import (
    Bot,
    MessageEvent,
    on_regex
)

api_key = "nBINp1gNmmkwL3lgLLjJmXZKiqyqxgqj"


@on_regex(r"搜图(.*)")
async def get_pic(
    bot: Bot,
    event: MessageEvent
):
    para = event.get_message

    for ch in para:
        if u'\u4e00' <= ch <= u'\u9fff':
            await bot.send(
                event.get_group_id,
                f"[CQ:at,qq={event.get_user_id}] 暂不支持中文搜索!"
            )
            return
    
    if not len(para):
        wallhaven_api= wallhavenapi.WallhavenApiV1(api_key=api_key)
        data = wallhaven_api.search(para, purities="SFW")
    else:
        wallhaven_api= wallhavenapi.WallhavenApiV1(api_key=api_key)
        data = wallhaven_api.search(para, purities="SFW", page=3)
    
    if not len(data['data']):
        logger.info(f"查询图片{para} 失败: 查无此图")

        await bot.send(
            event.get_group_id,
            f"[CQ:at,qq={event.get_user_id}]\n"
            "查无此图！"
        )
        return

    await bot.send(
        event.get_group_id,
        f"[CQ:at,qq={event.get_user_id}]\n"
        f"[CQ:image,file={choice(data['data'])['path']}]"
    )
