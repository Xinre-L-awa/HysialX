import httpx
from log import logger
from pool import FuncPool

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
    expected_type: str
) -> FuncPool:
    res: FuncPool = FuncPool()
    for func in func_pool:
        if func.match_pattern == expected_type:
            func.x = False if func.match_pattern in ("RunInLoop", "custom", "on_startup") else True
            res.add_func(func)
    
    return res
