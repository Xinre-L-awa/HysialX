import httpx

from log import logger
from .utils import CreateOnWaitingTask
from .exception import FinishException
from plugins.manager import WaitingFuncMeta

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
    func: WaitingFuncMeta | None = None

    def __init__(self): ...

    async def send(self, uid, message, mode="group"):
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
        # return await asyncio.gather(send_(uid, "group", message), return_exceptions=True)
    
    async def finish(self, uid, message):
        return await send_(uid, "group", message)

    async def call_api(self, api: str, **kwargs):
        async with httpx.AsyncClient(base_url="http://127.0.0.1:570") as client:
            params = kwargs
            await client.post(f"/{api}", params=params)
        logger.opt(colors=True).success(f"Succeeded to call api {api}!")
    
    async def input_value(self):
        print("Created!")
        CreateOnWaitingTask(self.func.child_func)
