import os
import re
import sys
import yaml
import importlib
from log import logger
from api import get_plugin_pool
from typing import List, TYPE_CHECKING
from plugins.manager import FuncMeta, PluginMeta
if TYPE_CHECKING:
    from pool import FuncPool


sys.path.append(os.getcwd())


def init(check_files=True):
    logger.opt(colors=True).info("Hysial Bot is starting...")
    if check_files:
        logger.opt(colors=True).info("Checking config files...")

        if not os.path.exists("./go-cqhttp"):
            logger.error("<r>No go-cqhttp founded!</r>")
            logger.opt(colors=True).info("Closed")
            exit(-1)
        
        if not os.path.exists("GroupStatistics.json"):
            logger.warning('"GroupStatistics.json" does not exist, and will be created.')
            with open("GroupStatistics.json", 'w'):
                logger.success("Created Successfully.")
            
        with open("go-cqhttp/config.yml", encoding="utf-8", mode='r') as f:
            data = yaml.safe_load(f)
        logger.opt(colors=True).info(f"The current account is {data['account']['uin']}")

def check_whether_func(
    message: str,
    func_pool: "FuncPool"
) -> List["FuncMeta"]:
    return sorted(
        [
            func 
            for func in func_pool
            if (func.cmd and message.startswith(func.cmd)) or (func.regex and re.search(func.regex, message)) or ("[CQ:at" in message and func.match_pattern == "on_at")
        ],
        key=lambda x: x.priority
    )

def import_module(module):
    try:
        module_ = importlib.import_module(module)
        return module_
    except Exception as e:
        logger.exception(e)
        logger.error(f"Failed to import plugin {module}")
        return None

def load_plugins():
    """
    加载plugins目录下的插件
    """
    os.chdir("./plugins")

    sys.path.append(os.getcwd())
    plugins = [
        x for x in os.listdir() 
        if not (x.startswith('__') or x.endswith('.py'))
    ]

    for module in filter(
        lambda x: bool(x),
        [import_module(plugin) for plugin in plugins]
    ):
        if hasattr(module, "__plugin_meta__"):
            get_plugin_pool().add_plugin(module.__plugin_meta__)
        else:
            get_plugin_pool().add_plugin(PluginMeta(module.__name__))
        
        logger.opt(colors=True).success(f'Succeeded to import plugin <y>"{module.__name__}"</y>')

    os.chdir('..')
