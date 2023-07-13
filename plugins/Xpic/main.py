from loguru import logger
from random import choice, random
import wallhavenapi


api_key = "nBINp1gNmmkwL3lgLLjJmXZKiqyqxgqj"


async def get_pic(
    send_func,
    group_id,
    sender_id,
    sender_name,
    para_message
):

    for ch in para_message:
        if u'\u4e00' <= ch <= u'\u9fff':
            await send_func(
                group_id,
                "暂不支持中文搜索!"
            )
            return
    
    if not len(para_message):
        wallhaven_api= wallhavenapi.WallhavenApiV1(api_key=api_key)
        data = wallhaven_api.search(para_message, purities="SFW")
    else:
        wallhaven_api= wallhavenapi.WallhavenApiV1(api_key=api_key)
        data = wallhaven_api.search(para_message, purities="SFW", page=random(1, 10))
    
    if not len(data['data']):
        logger.info(f"查询图片{para_message} 失败: 查无此图")

        await send_func(
            group_id,
            "查无此图！"
        )
        return

    await send_func(
        group_id,
        f"[CQ:image,file={choice(data['data'])['path']}]"
    )
