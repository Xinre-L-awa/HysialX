from typing import List
from plugins.manager import FuncMeta


class BasePool:
    cur_index: int
    funcs: List[FuncMeta]

    def __init__(self) -> None:
        self.cur_index = 0
        self.funcs = list()
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.cur_index < self.get_num_of_funcs:
            res = self.funcs[self.cur_index]
            self.cur_index += 1
            return res
        else:
            raise StopIteration

    def add_func(self, func: "FuncMeta", priority=-1): # type: ignore
        self.funcs.insert(priority, func)
    
    def add_func(self, funcs: List[FuncMeta]):
        self.funcs += funcs
    
    def pop_func(self, func: "FuncMeta"):
        self.funcs.pop(self.funcs.index(func))
    
    @property
    def get_num_of_funcs(self):
        return len(self.funcs)


class FuncPool:
    funcs: List["FuncMeta"]
    cur_indx: int
    cur_index_: int

    def __init__(self) -> None:
        self.cur_index = 0
        self.cur_index_ = 0
        self.funcs = list()
    
    def __str__(self) -> str:
        return "\n".join((str(func)for func in self.funcs))
    
    def __iter__(self):
        return self

    def __next__(self):
        if self.cur_index < self.get_num_of_funcs:
            res = self.funcs[self.cur_index]
            self.cur_index += 1
            return res
        else:
            self.cur_index = 0
            raise StopIteration

    def add_func(self, func: "FuncMeta", priority=0):
        self.funcs.insert(priority, func)
    
    def add_funcs(self, funcs: List["FuncMeta"]):
        self.funcs += funcs
    
    def pop_func(self, func: "FuncMeta"):
        self.funcs.pop(self.funcs.index(func))
    
    @property
    def get_num_of_funcs(self):
        return len(self.funcs)


class WaitingPool:
    cur_index: int
    waiting_funcs: List["FuncMeta"]

    def __init__(self) -> None:
        self.cur_index = 0
        self.waiting_funcs = list()
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.cur_index < self.get_num_of_funcs:
            res = self.waiting_funcs[self.cur_index]
            self.cur_index += 1
            return res
        else:
            self.cur_index = 0
            raise StopIteration

    def add_func(self, func: "FuncMeta", priority=-1):
        self.waiting_funcs.insert(priority, func)
    
    def add_funcs(self, funcs: List["FuncMeta"]):
        self.waiting_funcs += funcs
    
    def pop_func(self, func: "FuncMeta"):
        self.waiting_funcs.pop(self.waiting_funcs.index(func))
    
    @property
    def get_num_of_funcs(self):
        return len(self.waiting_funcs)


class ResponsePool(BasePool):
    pass
