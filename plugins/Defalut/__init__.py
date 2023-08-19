from plugins.manager import PluginMeta
# from typing import List, Dict, Union, Callable

from .main import *


# custom_response = lambda x: x[1:] if x[0] == ' ' else ''

__plugin_meta__ = PluginMeta(
    "Defalut",
    Usage="echo ... -> say ...",
    Author="Xinre",
    Description="The defalut plugin of HysialX"
)


# func_dict: Dict[str, List[Union[Callable[[Bot, Event], None], str]]] = {
#     "echo": [
#         echo,
#         "on_regex",
#         r"echo(.*)"
#     ],
#     "复读机": [
#         echo_,
#         "custom",
#         custom_response
#     ],
#     "菜单": [
#         DisplayAllFunc,
#         "on_command"
#     ]    
# }
