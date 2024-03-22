from typing import Any, Callable, Optional, TYPE_CHECKING

from pool import FuncPool, WaitingTaskPool
from plugins.manager import FuncMeta, WaitingFuncMeta, PluginPool

if TYPE_CHECKING:
    from api import Bot, Event

func_pool: FuncPool = FuncPool() # 全局插件函数池
plugin_pool: PluginPool = PluginPool() # 全局插件池
waiting_task_pool: WaitingTaskPool = WaitingTaskPool() #全局等待任务池


def get_func_pool() -> FuncPool: return func_pool
def get_plugin_pool() -> PluginPool: return plugin_pool
def get_waiting_task_pool() -> WaitingTaskPool: return waiting_task_pool


def on(func: Callable[["Bot", "Event"], None] | FuncMeta | WaitingFuncMeta, pattern: str | None=None, **kwargs):
    return get_func_pool().add_func(func if isinstance(func, FuncMeta) else FuncMeta(func, pattern, **kwargs))


# class BaseOn:
#     func: Callable

#     def __init__(self, func: Callable) -> None:
#         self.func = func

#     def on_waiting(self, cmd: str) -> FuncMeta:
#         return


# class on_command(BaseOn):
#     def __call__(self, cmd: Optional[str] = None) -> FuncMeta:
#         return on(
#             self.func,
#             "on_command",
#             cmd=cmd
#         )


def on_at(qq: int | None=None):
    """
    qq 为指定要检测的 qq号, 默认为机器人本身
    """
    def wrapper(func: Callable[["Bot", "Event"], None]):
        return on(
            func,
            "on_at",
            qq=qq
        )
    return wrapper


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


class on_waiting:
    func: WaitingFuncMeta

    def __init__(self,cmd: Optional[str]=None, regex: Optional[str]=None, response_method: Callable=None) -> None:
        self.cmd = cmd
        self.regex = regex
        self.response_method = response_method

    def __call__(self, func):
        self.func = func
        on(
            WaitingFuncMeta(
                func,
                cmd=self.cmd,
                regex=self.regex,
                response_method=self.response_method
            )
        )
        return self

    def add_child_func(self, child_func):
        # print(child_func.__name__, 1)
        self.func.child_func = child_func
    
    def then(self, cmd: Optional[str]=None, regex: Optional[str]=None, response_method: Callable=None):
        # print("test")
        def wrapper(func: Callable[["Bot", "Event"], None]):
            meta: WaitingFuncMeta
            for meta in get_func_pool():
                # print("test")
                # print(meta, self.func)
                if meta == self.func:
                    # print(meta)
                    meta.child_func = func
            return on(
                WaitingFuncMeta(
                    func,
                    cmd=cmd,
                    regex=regex,
                    parrend_func=self.func,
                    response_method=response_method,
                    isChildFunc=True
                )
            )
        return wrapper


def add_child_func(func: on_waiting, child_func):
    for meta in get_func_pool():
        if meta._func == func.func:
            meta.child_func = WaitingFuncMeta(child_func)


def on_startup(func):
    get_func_pool().add_func(FuncMeta(func, "on_startup"))
    return func


def RunInLoop(func):
    get_func_pool().add_func(FuncMeta(func, "RunInLoop"))
    return func


def custom(response_method: Callable):
    def wrapper(func: Callable[["Bot", "Event"], None]):
        return on(
            func, 
            "custom",
            custom_response_method=response_method
        )
    return wrapper
