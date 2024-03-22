from typing import List, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api import Bot, Event


class FuncMeta:
    x: bool     # 标记该函数类型是否特殊（区别于 on_command, on_regex, on_keyword, on_waiting）
    at: int
    cmd: Optional[str]
    _func: Callable
    regex: Optional[str]
    aliases: Optional[set]
    child_func: Optional[Callable]
    match_pattern: Optional[str]
    custom_response_method: Callable[[str], str] | None

    def __init__(self, func: Callable[["Bot", "Event"], None], pattern, **kwargs) -> None:
        self.x = True
        self._func = func
        self.match_pattern = pattern

        self.at = kwargs.get("at")
        self.cmd = kwargs.get("cmd")
        self.regex = kwargs.get("regex")
        self.aliases = kwargs.get("aliases")
        self.custom_response_method = kwargs.get("custom_response_method")
    
    def __call__(self, bot: Optional["Bot"]=None, event: Optional["Event"]=None, isDebug=False) -> None:
        if self.match_pattern == "on_startup":
            return self._func()
        elif bot == None and event == None: return

        return self._func(bot, event)
    
    def __str__(self) -> str:
        return (
            f"函数名: {self._func.__name__}\n"
            f"响应方式: {self.match_pattern}\n"
            f"调用命令: {self.cmd}\n"
            f"正则匹配: {self.regex}\n"
            f"别名: {self.aliases}"
        )

    def __repr__(self) -> str:
        return (
            f"函数名: {self._func.__name__}\n"
            f"响应方式: {self.match_pattern}\n"
            f"调用命令: {self.cmd}\n"
            f"正则匹配: {self.regex}\n"
            f"别名: {self.aliases}"
        )

    @property
    def name(self) -> str:
        return self._func.__name__


class WaitingFuncMeta(FuncMeta):
    isChildFunc: bool
    child_func = None
    parrent_func = None

    def __init__(
        self, 
        func, 
        child_func=None,
        parrend_func=None,
        isChildFunc=False,
        **kwargs
    ) -> None:
        super().__init__(func, "on_waiting", **kwargs)
        
        self.isChildFunc = isChildFunc
        self.child_func = child_func
        self.parrent_func = parrend_func
    
    def __str__(self) -> str:
        return (
            f"函数名: {self._func.__name__}\n"
            f"响应方式: {self.match_pattern}\n"
            f"调用命令: {self.cmd}\n"
            f"正则匹配: {self.regex}\n"
            f"父函数: {self.parrent_func.__name__ if self.parrent_func else '无'}, 子函数: {self.child_func if self.child_func else '无'}\n"
            f"别名: {self.aliases}"
        )

    def __repr__(self) -> str:
        return (
            f"函数名: {self._func.__name__}\n"
            f"响应方式: {self.match_pattern}\n"
            f"调用命令: {self.cmd}\n"
            f"正则匹配: {self.regex}\n"
            f"父函数: {self.parrent_func.__name__ if self.parrent_func else '无'}, 子函数: {self.child_func if self.child_func else '无'}\n"
            f"别名: {self.aliases}"
        )


class PluginMeta:
    PluginName: Optional[str]
    PluginFuncs: Optional[List[Callable]]
    PluginUsage: Optional[str]
    PluginAuthor: Optional[str]
    PluginDescription: Optional[str]

    def __init__(
        self,
        Name=None,
        Funcs=None,
        Usage=None,
        Author=None,
        Description=None
    ):
        self.PluginName = Name
        self.PluginFuncs = Funcs
        self.PluginUsage = Usage
        self.PluginAuthor = Author
        self.PluginDescription = Description

    def add_func(self, func: Callable):
        self.PluginFuncs.append(func)

    def __str__(self) -> str:
        return (
            f"插件名称: {self.PluginName}\n"
            f"插件用法: {self.PluginUsage}\n"
            f"插件作者: {self.PluginAuthor}\n"
            f"插件描述: {self.PluginDescription}"
        )
    
    def __repr__(self) -> str:
        return (
            f"插件名称: {self.PluginName}\n"
            f"插件用法: {self.PluginUsage}\n"
            f"插件作者: {self.PluginAuthor}\n"
            f"插件描述: {self.PluginDescription}"
        )


class PluginPool:
    cur_index: int
    plugins: List[PluginMeta]

    def __init__(self) -> None:
        self.plugins = []
        self.cur_index = 0

    def __iter__(self):
        return self
    
    def __next__(self):
        if self.cur_index < self.get_num_of_plugins:
            res = self.plugins[self.cur_index]
            self.cur_index += 1
            return res
        else:
            self.cur_index = 0
            raise StopIteration

    def add_plugin(self, plugin: PluginMeta):
        self.plugins.append(plugin)

    def add_plugins(self, *args: List[PluginMeta]):
        self.plugins.extend(args) # type: ignore
    
    def dispose_all(self):
        self.plugins.clear()
    
    @property
    def get_num_of_plugins(self):
        return len(self.plugins)
