from typing import List
from plugins.manager import FuncMeta, WaitingFuncMeta, ScheduledTask


class FuncPool:
    funcs: List[FuncMeta]
    cur_index: int

    def __init__(self) -> None:
        self.cur_index = 0
        self.funcs = list()
    
    def __str__(self) -> str:
        return "\n".join((str(func)for func in self.funcs))
    
    def __iter__(self):
        # 返回**独立**迭代器：消费者提前 break（例如命中 block=True）时不会把游标留在半途。
        # 旧实现 `return self` + 单一 cur_index，会让下一条事件从中间开始遍历，静默漏掉池首的响应器。
        return iter(self.funcs)

    def __next__(self):
        # 保留：给 `next(pool)` 这类老用法兜底；`for` 已经不走这里了
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
        response_method: List[str]=None
    ) -> None:
        self.func = func
        self.user_id = user_id
        self.group_id = group_id
        # 别用可变默认值：["input"] 会被所有实例共享
        self.response_method = ["input"] if response_method is None else response_method
    
    def __str__(self) -> str:
        return (
            f"函数名: {getattr(self.func, 'name', None) or self.func}\n"
            "响应方式: 等待任务\n"
            f"{self.func}"
        )

    def __repr__(self) -> str:
        return (
            f"函数名: {getattr(self.func, 'name', None) or self.func}\n"
            "响应方式: 等待任务\n"
        )


class WaitingTaskPool:
    cur_index: int
    waiting_tasks: List[WaitingTask]

    def __init__(self) -> None:
        self.cur_index = 0
        self.waiting_tasks = list()
    
    def __iter__(self):
        return iter(self.waiting_tasks)      # 同上：独立迭代器
    
    def __next__(self):
        if self.cur_index < self.get_num_of_funcs:
            res = self.waiting_tasks[self.cur_index]
            self.cur_index += 1
            return res
        else:
            self.cur_index = 0
            raise StopIteration

    def add_task(self, task, priority=None):
        # 幂等：on_waiting 命中时框架会按"精确会话(user+group)"自动入池，而插件处理器里通常
        # **又**调一次 bot.input_value()（往往只给 group_id → user_id=None）。不去重的话
        # 用户的下一条消息会把子函数触发两次，而且死任务会一直堆在池子里。
        # 比较前把 id 归一化成 str：插件可能传 int，事件侧是 str（见 main.py 的匹配逻辑）。
        norm = lambda v: None if v is None else str(v)          # noqa: E731
        target = getattr(task.func, "_func", task.func)
        for existing in self.waiting_tasks:
            if getattr(existing.func, "_func", existing.func) is not target:
                continue
            if norm(existing.group_id) != norm(task.group_id):
                continue
            if (norm(existing.user_id) == norm(task.user_id)
                    or task.user_id is None or existing.user_id is None):
                return                      # 同一子函数的同一会话，留一个就够
        self.waiting_tasks.append(task)

    def add_tasks(self, tasks: List["WaitingTask"]):
        self.waiting_tasks += tasks
    
    def pop_task(self, task: "WaitingTask"):
        self.waiting_tasks.remove(task)
    
    def pop_tasks(self, tasks: List["WaitingTask"]):
        for task in tasks:
            if task in self.waiting_tasks:
                self.waiting_tasks.remove(task)
    
    @property
    def get_num_of_funcs(self):
        return len(self.waiting_tasks)


class NoticeFuncPool(FuncPool):
    def __init__(self) -> None:
        super().__init__()


class ScheduledTaskPool:
    tasks: List[ScheduledTask]
    cur_index: int
    
    def __init__(self) -> None:
        self.tasks = []
        self.cur_index = 0
    
    def __iter__(self):
        return iter(self.tasks)              # 同上：独立迭代器
    
    def __next__(self):
        if self.cur_index < len(self.tasks):
            res = self.tasks[self.cur_index]
            self.cur_index += 1
            return res
        else:
            self.cur_index = 0
            raise StopIteration
    
    def add_task(self, task):
        self.tasks.append(task)              # 旧实现 insert(-1) 会插到倒数第二

    def add_tasks(self, tasks: List["ScheduledTask"]):
        self.tasks += tasks
    
    def pop_task(self, task: "ScheduledTask"):
        self.tasks.remove(task)
    
    def pop_tasks(self, tasks: List["ScheduledTask"]):
        for task in tasks:
            if task in self.tasks:
                self.tasks.remove(task)
