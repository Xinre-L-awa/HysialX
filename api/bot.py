import json
import httpx
import websockets

from log import logger
from .utils import CreateOnWaitingTask
from .exception import FinishException
from plugins.manager import WaitingFuncMeta

async def send_(uid, mode, message):
    try:
        params = {
            f'{mode if mode == "group" else "user"}_id': uid,
            "message": message
        }
        httpx.post("http://127.0.0.1:9920/send_msg",json=params)
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
            params = {
                f'{mode if mode == "group" else "user"}_id': uid,
                "message": message
            }
            httpx.post("http://127.0.0.1:9920/send_msg", json=params)
            logger.opt(colors=True).success(f'发送消息 "{message}" 到群 {uid} 成功')
        except Exception as e:
            logger.exception(e)
            logger.opt(colors=True).warning(f'发送消息 "{message}" 到群 {uid} 失败, 账号可能被风控')
        # return await asyncio.gather(send_(uid, "group", message), return_exceptions=True)
    
    async def finish(self, uid, message):
        return await send_(uid, "group", message)

    async def call_api(self, api: str, **kwargs):
        params = {
                        "action": api,
                        "params": kwargs
                    }
        await httpx.AsyncClient("http://127.0.0.1:9920", params=params)
        logger.opt(colors=True).success(f"Succeeded to call api {api}!")
    
    async def input_value(self, user_id: int=None, group_id: int=None):
        logger.info("A OnWaiting Task has been successfully created.")
        CreateOnWaitingTask(self.func.child_func, user_id, group_id)
