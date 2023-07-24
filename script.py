"""
本模块集合了所需函数及变量
"""
import os
import yaml
from log import *
from typing import Callable, Dict, List, Union


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


def getExpectedFuncs(
    func_dict: Dict[str, List[Union[Callable, str]]],
    expected_type: str
) -> List[Union[Callable, str]]:
    return [[func_dict[k][0], func_dict[k][1]] for k in func_dict if expected_type in func_dict[k][1]]
