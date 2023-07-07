"""
本模块集合了所需的库和函数
"""
import os
import sys
import yaml
import httpx
from log import *
from loguru import logger
from typing import Callable

logger.opt(colors=True).info("Hysial Bot is staring...")
logger.opt(colors=True).info("Checking config files...")
if not os.path.exists("GroupStatistics.json"):
    logger.warning("GroupStatistics.json does not exist, and will be created.")
    with open("GroupStatistics.json", 'w'):
        logger.success("Created Successfully.")
with open("./go-cqhttp/config.yml", encoding="utf-8", mode='r') as f:
    data = yaml.safe_load(f)
logger.opt(colors=True).info(f"The current account is {data['account']['uin']}")


async def sends(uid, message):
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5700") as client:
            params = {
                "group_id": uid,
                "message": message,
            }
            await client.post("/send_msg", params=params)
        logger.opt(colors=True).success(f'发送消息 "{message}" 到群 {uid} 成功')
    except:
        logger.opt(colors=True).warning(f'发送消息 "{message}" 到群 {uid} 失败, 账号可能被风控')
