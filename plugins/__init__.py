"""
@Author: Xinre
本模块用于动态导入插件
""" 

import os
import importlib
from log import sys, logger
from api import get_plugin_pool
from .manager import PluginMeta

os.chdir("./plugins")

sys.path.append(os.getcwd())
plugins = [
    x for x in os.listdir() 
    if not (x.startswith('__') or x.endswith('.py'))
]
modules = [
    importlib.import_module(plugin) for plugin in plugins
]

func_dicts = {}
for module in modules:
    if hasattr(module, "__plugin_meta__"):
        get_plugin_pool().add_plugin(module.__plugin_meta__)
    else:
        get_plugin_pool().add_plugin(PluginMeta(module.__name__))
    
    logger.opt(colors=True).success(f'Succeeded to import plugin <y>"{module.__name__}"</y>')

os.chdir('..')
