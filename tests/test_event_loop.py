# tests/test_event_loop.py —— event_loop 的并发限流与退出语义（m8 §9 的 D7 / D8）
"""D8 钉的就是这次修的 bug：`finally` 里 `asyncio.gather(*running, ...)` 少了 `await`，
退出时不等在途 handler 跑完。手法是"慢 handler + 立刻取消 event_loop"，然后断言
handler 已经结束——少了 await 时这里只会看到 "start"。
"""

import asyncio
import time

from mock_snowluma import MockSnowLuma, group_message
from api import get_waiting_task_pool, on_command, set_connection
from api.bot import Bot
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection
import main as main_module

SELF_ID = 999


def config_for(mock: MockSnowLuma, *, workers: int) -> SnowLumaConfig:
    return SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/", forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}", http_token=mock.http_token,
        api_transport="ws", message_format="array",
        request_timeout=1.0, reconnect_interval=1.0, ping_interval=0, ping_timeout=0,
        event_workers=workers,
    )


def _payload(text: str) -> dict:
    payload = group_message(text)
    payload["self_id"] = SELF_ID
    return payload


async def _with_loop(workers: int, body):
    """起 mock + 连接 + event_loop，跑 body(conn, loop_task, marks)，最后统一收尾。

    数据隔离是必须的：别的用例（test_debug）可能已经把真实插件登记进全局函数池了，
    而 event_loop 会经 `refresh_funcs()` 把它们带进 loopFuncs —— 那样 XHuaLao 的统计
    钩子会写进真实 DataForXPlugin/。所以这里①清空函数池 ②把数据目录指到临时目录。
    """
    import uuid
    from pathlib import Path
    import shutil
    import api

    data_dir = Path(".workbuddy") / "pytest-data" / uuid.uuid4().hex / "DataForXPlugin"
    data_dir.mkdir(parents=True, exist_ok=True)
    saved_data_path = api.DEFAULT_PLUGINS_DATA_PATH
    api.DEFAULT_PLUGINS_DATA_PATH = str(data_dir)
    saved_funcs = [list(pool.funcs) for pool in (api.get_func_pool(),
                                                 api.get_notice_func_pool(),
                                                 api.get_request_func_pool())]
    for pool in (api.get_func_pool(), api.get_notice_func_pool(), api.get_request_func_pool()):
        pool.funcs.clear()

    mock = await MockSnowLuma(ws_port=0, http_port=0).start()
    conn = OneBotConnection(config_for(mock, workers=workers))
    await conn.start()
    loop_task = None
    try:
        assert await conn.wait_until_connected(3), "没连上 mock"
        set_connection(conn)
        loop_task = asyncio.create_task(main_module.event_loop(conn))
        await body(mock, loop_task)
    finally:
        if loop_task is not None and not loop_task.done():
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)
        set_connection(None)
        left = list(get_waiting_task_pool())
        if left:
            get_waiting_task_pool().pop_tasks(left)
        await conn.stop()
        await mock.stop()
        # 还原全局池与数据目录
        for pool, backup in zip((api.get_func_pool(), api.get_notice_func_pool(),
                                 api.get_request_func_pool()), saved_funcs):
            pool.funcs[:] = backup
        api.DEFAULT_PLUGINS_DATA_PATH = saved_data_path
        main_module.refresh_funcs()
        shutil.rmtree(data_dir.parent, ignore_errors=True)


def test_event_workers_serialize_handlers():
    """D7：event_workers=1 时第二条事件要等第一条处理完"""
    marks: list[tuple[str, float]] = []

    async def body(mock, loop_task):
        @on_command("慢")
        async def slow(bot: Bot, event):
            marks.append(("start", time.monotonic()))
            await asyncio.sleep(0.25)
            marks.append(("end", time.monotonic()))

        main_module.refresh_funcs()
        await mock.push(_payload("慢"))
        await mock.push(_payload("慢"))
        await asyncio.sleep(0.8)

        assert [m[0] for m in marks] == ["start", "end", "start", "end"], marks
        assert marks[2][1] >= marks[1][1], f"第二个 handler 在第一个结束前就开始了: {marks}"

    asyncio.run(_with_loop(1, body))


def test_event_loop_waits_for_inflight_handler():
    """D8：关停 event_loop 时，在途 handler 必须跑完再退出（不能被丢掉）"""
    marks: list[str] = []

    async def body(mock, loop_task):
        @on_command("慢")
        async def slow(bot: Bot, event):
            marks.append("start")
            await asyncio.sleep(0.3)
            marks.append("end")

        main_module.refresh_funcs()
        await mock.push(_payload("慢"))
        for _ in range(20):                      # 等 handler 真的开始
            if marks:
                break
            await asyncio.sleep(0.02)
        assert marks == ["start"], marks

        loop_task.cancel()                       # 模拟关停
        await asyncio.gather(loop_task, return_exceptions=True)
        assert marks == ["start", "end"], f"退出时丢掉了在途 handler: {marks}"

    asyncio.run(_with_loop(2, body))
