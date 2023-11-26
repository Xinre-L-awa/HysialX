from typing import Any, List, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api import Bot, Event


class FuncMeta:
    x: bool
    cmd: Optional[str]
    _func: Callable
    regex: Optional[str]
    aliases: set
    match_pattern: Optional[str]
    custom_response_method: Callable[[str], str]

    def __init__(self, func, pattern, **kwargs) -> None:
        self.x = True
        self._func = func
        self.match_pattern = pattern

        self.cmd = kwargs.get("cmd") if kwargs.get("cmd") else None
        self.regex = kwargs.get("regex") if kwargs.get("regex") else None
        self.aliases = kwargs.get("aliases")
        self.custom_response_method = kwargs.get("custom_response_method")
    
    def __call__(self, bot: "Bot"=None, event: "Event"=None, isDebug=False) -> None:
        if self.match_pattern == "on_startup":
            return self._func()
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



class PluginMeta:
    PluginName: str
    PluginFuncs: Optional[List[FuncMeta]]
    PluginUsage: str
    PluginAuthor: str
    PluginDescription: str

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
    plugins: Optional[List[PluginMeta]]

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

    def add_plugins(self, *args: Optional[List[PluginMeta]]):
        self.plugins.extend(args)
    
    def dispose_all(self):
        self.plugins.clear()
    
    @property
    def get_num_of_plugins(self):
        return len(self.plugins)
