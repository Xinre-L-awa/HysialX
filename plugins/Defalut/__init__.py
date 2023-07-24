from typing import List, Dict, Union, Callable

from .main import *


func_dict: Dict[str, List[Union[Callable[[Bot, Event], None], str]]] = {
    "echo": [
        echo,
        "on_keyword"
    ],
    "菜单": [
        DisplayAllFunc,
        "on_command"
    ]    
}
