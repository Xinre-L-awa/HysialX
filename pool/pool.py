from typing import List
from plugins.manager import FuncMeta, WaitingFuncMeta


class FuncPool:
    funcs: List[FuncMeta]
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

    def add_func(self, func: FuncMeta | WaitingFuncMeta, priority=0):
        self.funcs.insert(priority, func)
        return func
    
    def add_funcs(self, funcs: List["FuncMeta"]):
        self.funcs += funcs
        return funcs
    
    def pop_func(self, func: "FuncMeta"):
        return self.funcs.pop(self.funcs.index(func))
    
    @property
    def get_num_of_funcs(self):
        return len(self.funcs)


class WaitingTask:
    def __init__(
        self, 
        func: WaitingFuncMeta,
        user_id: int=None,
        group_id: int=None,
        response_method: List[str]=["input"]
    ) -> None:
        self.func = func
        self.user_id = user_id
        self.group_id = group_id
        self.response_method = response_method
    
    def __str__(self) -> str:
        return (
            f"函数名: {self.func.name}\n"
            "响应方式: 等待任务\n"
            f"{self.func}"
        )

    def __repr__(self) -> str:
        return (
            f"函数名: {self.func.name}\n"
            "响应方式: 等待任务\n"
        )


class WaitingTaskPool:
    cur_index: int
    waiting_tasks: List[WaitingTask]

    def __init__(self) -> None:
        self.cur_index = 0
        self.waiting_tasks = list()
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.cur_index < self.get_num_of_funcs:
            res = self.waiting_tasks[self.cur_index]
            self.cur_index += 1
            return res
        else:
            self.cur_index = 0
            raise StopIteration

    def add_task(self, task, priority=-1):
        self.waiting_tasks.insert(priority, task)

    def add_tasks(self, tasks: List["WaitingTask"]):
        self.waiting_tasks += tasks
    
    def pop_task(self, task: "WaitingTask"):
        self.waiting_tasks.remove(task)
    
    def pop_tasks(self, tasks: List["WaitingTask"]):
        for task in tasks:
            self.waiting_tasks.remove(task)
    
    @property
    def get_num_of_funcs(self):
        return len(self.waiting_tasks)


class NoticeFuncPool(FuncPool):
    def __init__(self) -> None:
        super().__init__()
