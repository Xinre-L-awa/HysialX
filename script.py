import os
import re
import sys
import importlib
from pathlib import Path

from log import logger
from api import get_plugin_pool, DEFAULT_PLUGINS_DATA_PATH
from typing import List, TYPE_CHECKING
from plugins.manager import FuncMeta, PluginMeta
from snowluma.config import SnowLumaConfig, write_default_config, DEFAULT_CONFIG_PATH, load_config
if TYPE_CHECKING:
    from pool import FuncPool


sys.path.append(os.getcwd())


def init(check_files=True):
    """打印启动横幅、准备配置文件，返回 SnowLuma 连接配置"""
    logger.opt(colors=True).info("Hysial Bot is starting...")

    if check_files:
        logger.opt(colors=True).info("Checking config files...")
        if write_default_config(DEFAULT_CONFIG_PATH):
            logger.opt(colors=True).success(
                f"已生成默认配置文件 <y>{DEFAULT_CONFIG_PATH}</y>（留空字段表示跟随 SnowLuma）")
        data_dir = Path(DEFAULT_PLUGINS_DATA_PATH)
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            logger.opt(colors=True).info(f"已创建插件数据目录 <y>{DEFAULT_PLUGINS_DATA_PATH}</y>")

    config = load_config(DEFAULT_CONFIG_PATH, create=check_files)
    logger.opt(colors=True).info("SnowLuma 连接配置:\n" + config.describe())
    return config

def check_whether_func(message: str, func_pool: "FuncPool") -> List["FuncMeta"]:
    """粗筛：按 cmd 前缀 / 正则挑出候选响应器。

    `message` 请传**去掉了 @机器人 前缀**的纯文本（main.py 传的是 command_text），
    on_at 不在这里判定——它的判据是 CQ 串里的 `[CQ:at,qq=...]`，由 main.py 单独补进候选。
    """
    matched = []
    for func in func_pool:
        cmds = func.cmd
        if isinstance(cmds, str):
            cmds = [cmds]
        hit = False
        if cmds:
            try:
                hit = message.startswith(tuple(str(c) for c in cmds))
            except TypeError:
                hit = False
        if not hit and func.regex:
            hit = re.search(func.regex, message) is not None
        if hit:
            matched.append(func)
    return sorted(matched, key=lambda x: x.priority)

def import_module(module):
    try:
        module_ = importlib.import_module(module)
        return module_
    except Exception as e:
        logger.exception(e)
        logger.error(f'Failed to import plugin <y>"{module}"</y>')
        return None

def load_plugins():
    """
    加载plugins目录下的插件
    """
    plugins_dir = Path("plugins").resolve()
    if not plugins_dir.is_dir():
        logger.error(f"未找到插件目录: {plugins_dir}")
        return
    plugins = [p.name for p in plugins_dir.iterdir()
             if p.is_dir() and not p.name.startswith("__")
             # 只把真正的"包"当插件：必须有 __init__.py 或 main.py，
             # 否则 logs/、__pycache__/ 之类目录会被当成插件 import 一遍
             and ((p / "__init__.py").exists() or (p / "main.py").exists())]

    cwd = os.getcwd()
    if str(plugins_dir) not in sys.path:
        sys.path.append(str(plugins_dir))
    try:
        os.chdir(plugins_dir)
        for plugin in plugins:
            module = import_module(plugin)
            if module is None:
                continue
            get_plugin_pool().add_plugin(getattr(module, "__plugin_meta__", PluginMeta(module.__name__)))
            logger.opt(colors=True).success(f'Succeeded to import plugin <y>"{module.__name__}"</y>')
    finally:
        os.chdir(cwd)
