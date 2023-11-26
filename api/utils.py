import httpx
from log import logger
from pool import FuncPool
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.manager import FuncMeta
    from typing import List, Dict, Union, Callable

async def set_device(name: str):
    async with httpx.AsyncClient(base_url="http://127.0.0.1:570") as client:
        params = {
            "model": name,
            "model_show": name
        }
        await client.post("/_get_model_show", params=params)
    logger.opt(colors=True).success(f'设置机型 {name} 成功!')


def getExpectedFuncs(
    func_pool: "FuncPool",
    expected_type: str=None,
    check_func: Callable[["FuncMeta"], bool]=None
) -> FuncPool:
    res: FuncPool = FuncPool()
    for func in func_pool:
        if func.match_pattern == expected_type or check_func(func):
            func.x = False if func.match_pattern in ("RunInLoop", "custom", "on_startup") else True
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


def At(qq: Union[int, str]) -> str: return f"[CQ:at,qq={qq}]"
def ImageSegment(content: str) -> str: return f"[CQ:img,file={content}]"
def MessageSegment(content: str) -> str: return content
