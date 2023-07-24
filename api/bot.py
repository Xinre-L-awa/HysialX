import httpx
from script import logger


class Bot:
    def __init__(self, func_dict):
        self.func_dict = func_dict
    
    async def send(self, uid, message):
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:570") as client:
                params = {
                    "group_id": uid,
                    "message": message,
                }
                await client.post("/send_msg", params=params)
            logger.opt(colors=True).success(f'发送消息 "{message}" 到群 {uid} 成功')
        except Exception as e:
            logger.debug(e)
            logger.opt(colors=True).warning(f'发送消息 "{message}" 到群 {uid} 失败, 账号可能被风控')
