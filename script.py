import os
import re
import yaml
from log import logger
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from pool import FuncPool
    from plugins.manager import FuncMeta

def init(check_files=True):
    logger.opt(colors=True).info("Hysial Bot is staring...")
    if check_files:
        logger.opt(colors=True).info("Checking config files...")
        if not os.path.exists("./go-cqhttp"):
            logger.error("<r>No go-cqhttp founded!</r>")
            logger.opt(colors=True).info("Closed")
            exit(-1)
        if not os.path.exists("GroupStatistics.json"):
            logger.warning("GroupStatistics.json does not exist, and will be created.")
            with open("GroupStatistics.json", 'w'):
                logger.success("Created Successfully.")
        with open("go-cqhttp/config.yml", encoding="utf-8", mode='r') as f:
            data = yaml.safe_load(f)
        logger.opt(colors=True).info(f"The current account is {data['account']['uin']}")


def check_whether_func(
    message: str,
    func_pool: "FuncPool"
) -> List["FuncMeta"]:
    return [
        func 
        for func in func_pool
        if (func.cmd and message.startswith(func.cmd)) or (func.regex and re.search(func.regex, message))
    ]
