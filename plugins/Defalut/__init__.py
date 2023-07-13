from typing import List, Dict, Union

from .main import *


func_dict: Dict[str, List[Union[Callable, str]]] = {
    "echo": [
        echo,
        "on_keyword"
    ]
}
