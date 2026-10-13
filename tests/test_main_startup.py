# tests/test_main_startup.py —— main_async 启动/关停烟测（用 mock 协议端，不联网、不起 Flask）
"""这条路径此前零覆盖，所以下面几个 bug 一直没被发现：

- `main.py:327` 调用未定义的 `shutdown_watcher` → NameError
- 同一行 `asyncio.create_task(coro, "name")` → TypeError（name 是关键字参数）
- `scheduled_loop` 里 `asyncio.sleep(1)` 漏 await → 循环不让出事件循环
- `event_loop` 退出时 `asyncio.gather(...)` 漏 await → 不等在途 handler

现在这个用例把 `main_async()` 真跑起来：连 mock → 收一条事件 → 用 `api.shutdown()` 触发
shutdown_watcher → 断言能干净退出并把全局连接清空。
"""

import asyncio
import signal

import pytest

import api
import main as main_module
from mock_snowluma import MockSnowLuma, group_message
from snowluma.config import SnowLumaConfig


def config_for(mock: MockSnowLuma) -> SnowLumaConfig:
    return SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/", forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}", http_token=mock.http_token,
        api_transport="ws", message_format="array",
        request_timeout=1.0, reconnect_interval=1.0, ping_interval=0, ping_timeout=0,
    )


async def _run(monkeypatch) -> None:
    mock = await MockSnowLuma(ws_port=0, http_port=0).start()          # 端口 0：让系统分配
    # 不加载真实插件（XHuaLao 的 on_startup 会在 1145 起 Flask），也不读 config/snowluma.json
    # 注意：别的用例可能已经把插件处理器登记进全局函数池了，这里必须清空，
    # 否则 push 的 mock 群(123456)事件会命中 XHuaLao 的统计钩子、写进真实 DataForXPlugin/。
    import shutil
    import uuid
    from pathlib import Path
    data_dir = Path(".workbuddy") / "pytest-data" / uuid.uuid4().hex / "DataForXPlugin"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "DEFAULT_PLUGINS_DATA_PATH", str(data_dir), raising=False)
    for pool in (api.get_func_pool(), api.get_notice_func_pool(), api.get_request_func_pool()):
        pool.funcs.clear()

    monkeypatch.setattr(main_module, "init", lambda *a, **k: config_for(mock))
    monkeypatch.setattr(main_module, "load_plugins", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "refresh_funcs", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "onstartupFuncs", [])
    monkeypatch.setattr(api.utils, "to_shutdown", False)        # 用后自动还原

    saved_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    task = asyncio.create_task(main_module.main_async(), name="startup-smoke")
    try:
        # 等它连上并走到 create_task(shutdown_watcher...)：有阻断级 bug 这里就会 done
        for _ in range(50):
            if api.get_connection() is not None and api.get_connection().connected:
                break
            await asyncio.sleep(0.1)
        assert not task.done(), f"main_async 启动即失败: {task.exception()!r}"
        connection = api.get_connection()
        assert connection is not None, "main_async 没有登记全局连接"

        # event_loop 真的在收事件（mock 推一条，队列应被消费）
        assert await mock.push(group_message("hi")) >= 1, "mock 没有已连接的客户端"
        for _ in range(20):
            if connection.event_queue.qsize() == 0:
                break
            await asyncio.sleep(0.05)
        assert connection.event_queue.qsize() == 0, "事件没有被 event_loop 消费"

        # 插件请求退出 → shutdown_watcher 置位 stop_event → main_async 走完 finally
        api.shutdown()
        await asyncio.wait_for(task, timeout=10)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for sig, handler in saved_signals.items():
            signal.signal(sig, handler)                          # main_async 会改信号处理器，还原
        api.set_connection(None)
        await mock.stop()
        shutil.rmtree(data_dir.parent, ignore_errors=True)       # 别把临时数据目录留在工作区


def test_main_async_startup_and_shutdown(monkeypatch):
    asyncio.run(_run(monkeypatch))
    assert api.get_connection() is None, "关闭后应清空全局连接"


def test_shutdown_watcher_exists_and_is_coroutine():
    """直接钉住那两个启动级 bug：函数必须存在，且 create_task 的 name 必须能用关键字传"""
    assert hasattr(main_module, "shutdown_watcher"), "main_async 调用了未定义的 shutdown_watcher"
    assert asyncio.iscoroutinefunction(main_module.shutdown_watcher)

    async def _check_create_task_name():
        async def _noop():
            return None
        return asyncio.create_task(_noop(), name="with-keyword")

    task = asyncio.run(_check_create_task_name())
    assert task.get_name() == "with-keyword"
