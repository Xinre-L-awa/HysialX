from loguru import logger
from random import choice

import wallhavenapi
from api import (
    At,
    Bot,
    GroupMessageEvent,
    on_regex
)

api_key = "nBINp1gNmmkwL3lgLLjJmXZKiqyqxgqj"


@on_regex(r"搜图(.*)")
async def get_pic(
    bot: Bot,
    event: GroupMessageEvent
):
    para = event.get_message

    for ch in para:
        if u'\u4e00' <= ch <= u'\u9fff':
            await bot.send(
                event.get_group_id,
                f"[CQ:at,qq={event.get_user_id}] 暂不支持中文搜索!"
            )
            return
    try:
        if not len(para):
            wallhaven_api= wallhavenapi.WallhavenApiV1(api_key=api_key, timeout=4.0)
            data = wallhaven_api.search(para, purities="sfw")
        else:
            wallhaven_api= wallhavenapi.WallhavenApiV1(api_key=api_key, timeout=4.0)
            data = wallhaven_api.search(para, purities="sfw", page=3)
    except Exception as e:
        logger.exception(e)
        await bot.finish(event.get_group_id, f"{At(event.get_user_id)} 连接超时")
    
    if not len(data['data']):
        logger.info(f"查询图片{para} 失败: 查无此图，请尝试使用对应英文重试")

        await bot.send(
            event.get_group_id,
            f"{At(event.get_user_id)}\n"
            "查无此图！"
        )
        return

    await bot.send(
        event.get_group_id,
        f"{At(event.get_user_id)}\n"
        f"[CQ:image,file={choice(data['data'])['path']}]"
    )
