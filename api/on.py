from typing import Any, Callable, Optional, TYPE_CHECKING

from pool import FuncPool, WaitingPool
from plugins.manager import FuncMeta, PluginPool

if TYPE_CHECKING:
    from api import Bot, Event

func_pool: FuncPool = FuncPool() # 全局插件函数池
plugin_pool: PluginPool = PluginPool() # 全局插件池
waiting_pool: WaitingPool = WaitingPool()


def get_func_pool() -> FuncPool: return func_pool
def get_plugin_pool() -> PluginPool: return plugin_pool
def get_waiting_pool() -> WaitingPool: return waiting_pool


def on(func: Callable, pattern: str, **kwargs):
    return get_func_pool().add_func(FuncMeta(func, pattern, **kwargs))


class BaseOn:
    func: Callable

    def __init__(self, func: Callable) -> None:
        self.func = func

    def on_waiting(self, cmd: str) -> FuncMeta:
        return


# class on_command(BaseOn):
#     def __call__(self, cmd: Optional[str] = None) -> FuncMeta:
#         return on(
#             self.func,
#             "on_command",
#             cmd=cmd
#         )


def on_command(cmd: Optional[str]) -> FuncMeta:
    """

    Parameters
    ----------
    cmd : Optional[str]
        响应命令

    Returns
    -------
    FuncMeta
        DESCRIPTION.

    """
    def wrapper(func: Callable[["Bot", "Event"], None]):
        return on(
            func,
            "on_command",
            cmd=cmd
        )
    return wrapper


def on_keyword(cmd: Optional[str]=None):
    def wrapper(func: Callable[["Bot", "Event"], None]):
        return on(
            func,
            "on_keyword",
            cmd=cmd
        )
    return wrapper


def on_regex(regex: Optional[str]=None):
    def wrapper(func: Callable[["Bot", "Event"], None]):
        return on(
            func,
            "on_regex",
            regex=regex
        )
    return wrapper


def on_startup(func):
    get_func_pool().add_func(FuncMeta(func, "on_startup"))
    return func


def RunInLoop(func):
    get_func_pool().add_func(FuncMeta(func, "RunInLoop"))
    return func


def custom(response_method: Callable):
    def wrapper(func: Callable[["Bot", "Event"], None]):
        get_func_pool().add_func(FuncMeta(func, "custom", custom_response_method=response_method))
        return func
    return wrapper
