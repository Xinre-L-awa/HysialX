"""
所有响应方式均在本模块定义

`block`的值决定是否阻断
"""

from typing import Callable, Optional, TYPE_CHECKING, Union, List

from pool import FuncPool, WaitingTaskPool, NoticeFuncPool, ScheduledTaskPool
from plugins.manager import FuncMeta, WaitingFuncMeta, PluginPool, ScheduledTask

if TYPE_CHECKING:
    from .bot import Bot
    from .event import GroupMessageEvent, PrivateMessageEvent

func_pool: FuncPool = FuncPool() # 全局插件消息类函数池
plugin_pool: PluginPool = PluginPool() # 全局插件池
notic_func_pool: NoticeFuncPool = NoticeFuncPool() # 全局插件通知事件类函数池
waiting_task_pool: WaitingTaskPool = WaitingTaskPool() #全局等待任务池
scheduled_task_pool: ScheduledTaskPool = ScheduledTaskPool() # 全局计划任务池

def get_func_pool() -> FuncPool: return func_pool
def get_plugin_pool() -> PluginPool: return plugin_pool
def get_notice_func_pool() -> NoticeFuncPool: return notic_func_pool
def get_waiting_task_pool() -> WaitingTaskPool: return waiting_task_pool
def get_scheduled_task_pool() -> ScheduledTaskPool: return scheduled_task_pool

def on(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None] | FuncMeta | WaitingFuncMeta, pattern: str | None=None, cmd: List[str]=[], block=False, priority: int=1, **kwargs):
    return get_func_pool().add_func(func if isinstance(func, FuncMeta) else FuncMeta(func, pattern, block, priority, cmd=cmd, **kwargs))


# class BaseOn:ss
#     func: Callable

#     def __init__(self, func: Callable) -> None:
#         self.func = func

#     def on_waiting(self, cmd: str) -> FuncMeta:
#         retusrn


# class on_command(BaseOn):
#     def __call__(self, cmd: Optional[str] = None) -> FuncMeta:
#         return on(
#             self.func,
#             "on_command",
#             cmd=cmd
#         )


def on_at(qq: Optional[int]=None, block: bool=True, priority: int=1):
    """
    qq 为指定要检测的 qq号, 默认为机器人本身
    """
    def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
        return on(
            func,
            "on_at",
            at=qq,
            block=block,
            priority=priority
        )
    return wrapper


def on_command(cmd: str, alias: List[str]=[]) -> FuncMeta:
    """

    Parameters
    ----------
    cmd : str | List[str]
        响应命令

    Returns
    -------
    FuncMeta
        DESCRIPTION.

    """
    def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
        return on(
            func,
            "on_command",
            cmd=[cmd] + alias
        )
    return wrapper


def on_keyword(cmd: Optional[str]=None):
    def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
        return on(
            func,
            "on_keyword",
            cmd=cmd
        )
    return wrapper


def on_notice(notice_type, block: bool=False, priority: int=1):
    def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
        return get_notice_func_pool().add_func(func if isinstance(func, FuncMeta) else FuncMeta(func, "on_notice", block, priority, notice_type=notice_type.value))
    return wrapper


def on_regex(regex: Optional[str]=None):
    def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
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

    def __call__(self, func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
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
        self.func.child_func = child_func
    
    def then(self, cmd: Optional[str]=None, regex: Optional[str]=None, response_method: Callable=None):
        def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
            meta: WaitingFuncMeta
            for meta in get_func_pool():
                if meta == self.func:
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


def on_scheduled(task_type: str="timely", frequency: int=0, fixed_execute_time: str="", disposable: bool=False):
    def wrapper(func: Callable):
        get_scheduled_task_pool().add_task(ScheduledTask(func, task_type, frequency, fixed_execute_time, disposable))
        return func
    return wrapper


def custom(response_method: Callable):
    def wrapper(func: Callable[["Bot", Union["GroupMessageEvent", "PrivateMessageEvent"]], None]):
        return on(
            func, 
            "custom",
            custom_response_method=response_method
        )
    return wrapper
