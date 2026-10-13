# tests/test_reverse.py —— 反向 WS：由 SnowLuma 主动连进来（M5 链路，此前零覆盖）
"""覆盖三件事：

1. 反向监听能起来，带 token 的客户端能接入（`_process_reverse_request` 鉴权 + `_reverse_handler`）
2. 反向通道上既能**收事件**（进 event_queue），也能**发动作**（echo 回包匹配）
3. token 不对时必须 401 拒绝（`hmac.compare_digest` 那条分支）
"""

import asyncio
import json
import socket

import pytest
import websockets
from websockets.exceptions import InvalidStatus

from mock_snowluma import group_message
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection

TOKEN = "revtok"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def reverse_config(port: int) -> SnowLumaConfig:
    cfg = SnowLumaConfig(
        mode="reverse", api_transport="ws", message_format="array",
        request_timeout=2.0, reconnect_interval=1.0, ping_interval=0, ping_timeout=0,
    )
    cfg.reverse.enabled = True
    cfg.reverse.host = "127.0.0.1"
    cfg.reverse.port = port
    cfg.reverse.path = "/event"
    cfg.reverse.access_token = TOKEN
    return cfg


async def _connect_with_retry(url: str, **kwargs):
    """反向服务端是异步起来的，这里重试几次等它 listen"""
    last: Exception | None = None
    for _ in range(50):
        try:
            return await websockets.connect(url, **kwargs)
        except OSError as exc:                  # ConnectionRefused：还没起来
            last = exc
            await asyncio.sleep(0.1)
    raise AssertionError(f"反向服务端没起来: {last!r}")


def test_reverse_ws_end_to_end():
    asyncio.run(_case())


async def _case() -> None:
    port = _free_port()
    conn = OneBotConnection(reverse_config(port))
    await conn.start()
    client = None
    reader = None
    try:
        client = await _connect_with_retry(
            f"ws://127.0.0.1:{port}/event?access_token={TOKEN}",
            additional_headers={"X-Self-ID": "999", "X-Client-Role": "Universal"},
        )
        assert conn.connected, "反向客户端接入后 connected 应为 True"

        # 1) 反向通道收事件
        await client.send(json.dumps(group_message("hi"), ensure_ascii=False))
        payload = await asyncio.wait_for(conn.event_queue.get(), timeout=3)
        assert payload.get("post_type") == "message", payload

        # 2) 反向通道发动作：客户端按 echo 回包
        async def echo_reader():
            async for raw in client:
                request = json.loads(raw)
                await client.send(json.dumps({
                    "status": "ok", "retcode": 0,
                    "data": {"online": True}, "echo": request.get("echo"),
                }))

        reader = asyncio.create_task(echo_reader())
        data = await conn.call_action("get_status")
        assert data == {"online": True}, data

        # 3) 鉴权失败必须被拒（客户端会抛 InvalidStatus/401）
        with pytest.raises(InvalidStatus):
            await websockets.connect(f"ws://127.0.0.1:{port}/event?access_token=wrong")
    finally:
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if client is not None:
            await client.close()
        await conn.stop()
