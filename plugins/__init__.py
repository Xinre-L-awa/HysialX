"""
@Author: Xinre
本模块用于动态导入插件及其函数
"""

import os
import sys
import importlib
from script import *

os.chdir('./plugins')
sys.path.append(os.getcwd())
plugins = os.listdir()[1:-2]
print(plugins)


modules = []
for plugin in plugins:
    modules.append(importlib.import_module(plugin))

func_dicts = {}
for module in modules:
    try:
        for k, v in module.func_dict.items():
            func_dicts[k] = v
        logger.opt(colors=True).success(f'Succeeded to import plugin <y>"{module.__name__}"</y>')
    except:
        logger.opt(colors=True).error(f'<r><bg #f8bbd0>Failed to import "{module.__name__}"</bg #f8bbd0></r>')
        logger.opt(colors=True).error(f'<r>The format of plugin "{module.__name__}" '
                                      'is incorrect</r>')


print(func_dicts)
os.chdir('..')
