import json
import websockets
from log import logger
from pool import FuncPool
from plugins.manager import FuncMeta
from .exception import FinishException
from .on import get_waiting_task_pool
from pool import WaitingFuncMeta, WaitingTask
from typing import List, Dict, Union, Callable


@logger.catch
def run_func(func: "FuncMeta", *args, isDebug=False) -> int:
    """
    封装函数运行，丰富运行参数
    """
    exit_code = 0
    try:
        res = func(*args)
    except FinishException as finish:
        if isDebug:
            if isinstance(func, FuncMeta):
                logger.debug(f"{func.name} 触发了 {finish}")
            else:
                logger.debug(f"{func.__name__} 触发了 {finish}")
    except Exception as e:
        logger.error(e)
        exit_code = -1
    if isDebug:
        if isinstance(func, FuncMeta):
            logger.debug(f"{func.name} 执行完毕")
        else:
            logger.debug(f"{func.__name__} 执行完毕")
    return res


@logger.catch
async def await_run_func(func: "FuncMeta", *args, isDebug=False) -> int:
    """
    封装函数运行，丰富运行参数
    """
    exit_code = 0
    # print(type(func._func))
    try:
        res = await func(*args)
    except FinishException as finish:
        if isDebug:
            logger.debug(f"{func.name} 触发了 {finish}")
    except Exception as e:
        logger.error(e)
        exit_code = -1
    if isDebug:
        logger.debug(f"{func.name} 函数执行完毕")
    # return res
    # return exit_code


async def set_device(name: str):
    async with websockets.connect("ws://127.0.0.1:1696/event/") as websocket:
            await websocket.send(
                    json.dumps({
                        "action": "_get_model_show",
                        "params": {
                            "model": name,
                            "model_show": name
                        }
                    })
            )
    logger.opt(colors=True).success(f'设置机型 {name} 成功!')


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
    res = []
    type_ = []
    is_: bool = False
    prop = ""
    prop_v = ""
    stack = []
    for ch in cq:
        stack.append(ch)
        if stack[-1] == '[':
            is_ = True
            if len(stack) > 1:
                res.append(
                    {
                        "type": "text",
                        "content": "".join(stack[:-1]).strip()
                    }
                )
                stack = []
            continue
        elif is_:
            if ch ==',':
                type_ = "".join(stack[:-1])
                stack = []
                continue
            elif ch == '=' and not prop:
                prop = "".join(stack[:-1])
                stack = []
                continue
            elif ch == ']':
                _ = "".join(stack[:-1]).split('=')
                prop_v = "".join(stack[:-1])
                res.append(
                    {
                        "type": type_.split(':')[1],
                        prop: prop_v
                    }
                )
                is_ = False
                prop = ""
                prop_v = ""
                stack = []
                continue
    return res


def CreateOnWaitingTask(func: Callable, user_id: int, group_id: int, type_: str=None):
    get_waiting_task_pool().add_task(WaitingTask(WaitingFuncMeta(func), user_id, group_id, type_))


def At(qq: Union[int, str]) -> str: return f"[CQ:at,qq={qq}]"
def ImageSegment(content: str) -> str: return f"[CQ:img,file={content}]"
def MessageSegment(content: str) -> str: return content
