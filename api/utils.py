import asyncio
import inspect

from typing import List, Dict, Callable

from log import logger
from plugins.manager import FuncMeta

from .exception import FinishException
from .on import get_waiting_task_pool, FuncPool
from pool import WaitingFuncMeta, WaitingTask

from snowluma.connection import OneBotConnection
from snowluma.exception import ConnectionUnavailable
from snowluma.segment import MessageSegment, escape_cq, normalize_cq, parse_cq_to_segments

to_shutdown: bool = False

def _name_of(func) -> str:
    return getattr(func, "name", None) or getattr(func, "__name__", str(func))

def _run_awaitable(awaitable):
    """没有事件循环时把协程跑完；已经在循环里则转成 task（不能 asyncio.run 嵌套）"""
    async def _runner():
        return await awaitable
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_runner())

    task: "asyncio.Task" = asyncio.ensure_future(awaitable)
    task.add_done_callback(_log_task_exception)
    return task


def _log_task_exception(task: "asyncio.Task") -> None:
    """兜住 fire-and-forget 任务的异常，否则会被静默吞掉（或只在 GC 时警告）"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception(exc)

@logger.catch
def run_func(func: "FuncMeta" | Callable, *args, isDebug=False) -> int:
    """
    封装函数运行，丰富运行参数
    """
    try:
        res = func(*args)
    except FinishException as finish:
        return None
    except Exception as exc:
        logger.exception(exc); return -1
    if inspect.isawaitable(res):
        try:
            res = _run_awaitable(res)
        except FinishException:
            return None
        except Exception as exc:
            logger.exception(exc); return -1
    if isDebug:
        logger.debug(f"{_name_of(func)} 执行完毕")
    return res


@logger.catch
async def await_run_func(func: "FuncMeta", *args, isDebug=False) -> int:
    """
    封装函数运行，丰富运行参数
    """
    try:
        res = func(*args)                       # FuncMeta.__call__ → 插件函数的返回值/协程
    except FinishException:
        return None
    except Exception as exc:
        logger.exception(exc); return -1

    if inspect.isawaitable(res):                # ← 关键：同步函数返回 None 时不会 await None
        try:
            res = await res
        except FinishException:
            return None
        except asyncio.CancelledError:
            raise                                  # 退出时要原样抛，否则 gather 卡住
        except Exception as exc:
            logger.exception(exc); return -1

    if isDebug:
        logger.debug(f"{_name_of(func)} 执行完毕")

    return res


async def set_device(name: str) -> bool:
    try:
        await require_connection().call_action("_set_model_show", model=name, model_show=name)
    except Exception as exc:
        logger.warning(f"设置机型 {name} 失败: {exc}")
        return False
    logger.success(f"设置机型 {name} 成功!")
    return True



def getExpectedFuncs(
    func_pool: "FuncPool",
    expected_type: str=None,
    check_func: Callable[["FuncMeta"], bool]=None
) -> FuncPool:
    res: FuncPool = FuncPool()
    for func in func_pool:
        if func.match_pattern == expected_type:
            func.x = func.match_pattern not in ("RunInLoop", "custom", "on_startup")
            res.add_func(func)
        elif check_func != None and check_func(func):
            func.x = func.match_pattern not in ("RunInLoop", "custom", "on_startup")
            res.add_func(func)
    
    return res


def AnalyseCQCode(cq: str) -> List[Dict[str, str]]:
    result = []
    for seg in parse_cq_to_segments(cq):
        if seg.type == "text":
            result.append({"type": "text", "content": seg.get("text", "")})
        else:
            result.append({"type": seg.type, **{k: str(v) for k, v in seg.data.items()}})
    return result

def func_accepts_event(func, event) -> bool:
    """判断插件函数是否声明接收该事件。

    `event` 要传**事件实例**（`GroupMessageEvent(...)`），不是事件类。
    放行（返回 True）的三种情况：没写 `event` 注解、注解无法用于 isinstance（字符串注解）、
    以及注解是联合类型时的正常 isinstance 判定。

    放行的意义：宁可不必要地调用插件函数，也不要因为读不懂注解就把整条消息的分发打断。
    """
    target = getattr(func, "_func", func)          # FuncMeta → 真正的插件函数
    annotation = (getattr(target, "__annotations__", None) or {}).get("event")
    if annotation is None:
        return True
    try:
        return isinstance(event, annotation)
    except TypeError:               # 字符串注解 / 不可用于 isinstance 的注解
        return True                 # 保守放行，交给函数自己处理

def shutdown():
    global to_shutdown
    to_shutdown = True


def is_shutdown_requested() -> bool:
    """是否有插件请求退出。

    必须用这个函数：`from api import to_shutdown` 拿到的是**导入那一刻的副本**（bool 不可变），
    之后 `shutdown()` 改的是 api.utils 里的全局量，副本永远是 False。
    """
    return to_shutdown


# api/utils.py：只有显式传入时才覆盖默认响应方式
def CreateOnWaitingTask(func, user_id, group_id, type_=None):
    # func 可能是已经被包过的 WaitingFuncMeta（add_child_func 的产物），再包一层会让
    # `name` / `__str__` 找不到 __name__
    meta = func if isinstance(func, WaitingFuncMeta) else WaitingFuncMeta(func)
    if user_id is None and group_id is None:
        # 匹配规则要求 user_id 与 group_id 同时相等，两个都不给的任务永远不会触发
        logger.warning("创建等待任务时既没给 user_id 也没给 group_id，这个任务永远不会被触发")
    task = WaitingTask(meta, user_id, group_id,
                       type_ if type_ is not None else ["input"])
    get_waiting_task_pool().add_task(task)



# CQ 串工具：**全部返回 str**，可直接拼进 f-string 再发送（ADR-0001 D2）。
# 需要结构化消息段请用 event.get_message_segments()（D5），别指望这些函数返回 MessageSegment。
def At(qq) -> str:                        return MessageSegment("at", {"qq": str(qq)}).to_cq()
def AtAll() -> str:                       return "[CQ:at,qq=all]"
def Reply(mid) -> str:                    return MessageSegment("reply", {"id": str(mid)}).to_cq()
def ImageSegment(file) -> str:            return MessageSegment("image", {"file": file}).to_cq()
def FaceSegment(id) -> str:               return MessageSegment("face", {"id": str(id)}).to_cq()
def RecordSegment(file) -> str:           return MessageSegment("record", {"file": file}).to_cq()
def VideoSegment(file) -> str:            return MessageSegment("video", {"file": file}).to_cq()
def FileSegment(file) -> str:             return MessageSegment("file", {"file": file}).to_cq()
def Text(content) -> str:                 return escape_cq(str(content))
def Message(value) -> str:                return normalize_cq(value)


_connection: "OneBotConnection | None" = None

def set_connection(connection: "OneBotConnection | None") -> None:
    """登记当前连接（main.py 启动时 / debug.py 用假连接 / 测试用例注入）"""
    global _connection
    _connection = connection

def get_connection() -> "OneBotConnection | None":
    """当前连接，可能为 None（离线调试、还没连上、刚断开）"""
    return _connection

def require_connection() -> "OneBotConnection":
    """拿连接，没有就抛——给"必须能调用动作"的路径用"""
    if _connection is None:
        raise ConnectionUnavailable("当前没有可用的 SnowLuma 连接")
    return _connection
