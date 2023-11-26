import httpx
import asyncio

from log import logger
from .exception import FinishException


async def send_(uid, mode, message):
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:570") as client:
            params = {
                f"{mode}_id": uid,
                "message": message,
            }
            await client.post("/send_msg", params=params)
        logger.opt(colors=True).success(f'发送消息 "{message}" 到群 {uid} 成功')
    except Exception as e:
        logger.warning(e)
        logger.opt(colors=True).warning(f'发送消息 "{message}" 到群 {uid} 失败, 账号可能被风控')
    finally:
        raise FinishException


class Bot:
    def __init__(self): ...

    async def send(self, uid, message):
        return await send_(uid, "group", message)
        # return await asyncio.gather(send_(uid, "group", message), return_exceptions=True)

    async def call_api(self, api: str, **kwargs):
        async with httpx.AsyncClient(base_url="http://127.0.0.1:570") as client:
            params = kwargs
            await client.post(f"/{api}", params=params)
        logger.opt(colors=True).success(f"Succeeded to call api {api}!")
