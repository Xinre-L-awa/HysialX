# tests/test_connection.py —— M4：正向 WS + 动作调用（由 tests/mock_snowluma.py 驱动）
import asyncio
import time

from mock_snowluma import (                      # pytest 会把 tests/ 加进 sys.path
    CaseRunner,
    MockSnowLuma,
    group_message,
    meta_heartbeat,
)
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection
from snowluma.exception import ActionFailed, ConnectionUnavailable

SELF_ID = 999
DEVICE = "HysialX 测试机型"


def config_for(mock: MockSnowLuma, **overrides) -> SnowLumaConfig:
    """把 mock 的地址/token 塞进配置；用例里只关心差异项"""
    cfg = SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/",
        forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}",
        http_token=mock.http_token,
        api_transport="ws",          # M4 只有 WS；auto 的 HTTP 分支留到 M5
        message_format="auto",
        request_timeout=1.0,
        reconnect_interval=1.0,      # 重连快一点，别让用例等 5 秒
        ping_interval=0,             # 关掉 ws 心跳，避免干扰计时
        ping_timeout=0,
        device_name=DEVICE,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


async def wait_until(predicate, timeout: float = 3.0) -> bool:
    """轮询等待条件成立。

    mock 的 CaseRunner 只负责断言，等待逻辑放在用例这边（断言与等待分开，失败信息更干净）。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


async def _case() -> int:
    runner = CaseRunner()
    mock = await MockSnowLuma(ws_port=0, http_port=0).start()          # 端口 0：让系统分配，避免固定端口占用
    conn = OneBotConnection(config_for(mock))
    try:
        # ============================================== A 组：正向 WS + 动作（13 项）
        await conn.start()
        runner.check("A1 正向连接建立", await conn.wait_until_connected(3))

        # 注意：self_id 会被 lifecycle 事件提前填上，等它 == 999 并不代表探测完成；
        #       探测完成的标志是 login_info 里有内容（这是实测踩到的坑，见 §10）
        ok = await wait_until(lambda: (conn.login_info or {}).get("user_id") == SELF_ID)
        runner.check(
            "A2 登录探测拿到 self_id / nickname",
            ok and conn.self_id == SELF_ID and (conn.login_info or {}).get("nickname") == "Mock",
            f"self_id={conn.self_id} login_info={conn.login_info}",
        )

        ok = await wait_until(lambda: bool(mock.actions_named("_set_model_show")))
        params = (mock.last_action("_set_model_show") or {}).get("params", {})
        runner.check(
            "A3 按 device_name 调 _set_model_show 且参数正确",
            ok and params == {"model": DEVICE, "model_show": DEVICE},
            str(params),
        )

        version = await conn.call_action("get_version_info")
        runner.check(
            "A4 get_version_info 可解析",
            version.get("app_name") == "SnowLuma" and version.get("protocol_version") == "v11",
            str(version),
        )

        before = conn.event_queue.qsize()
        await mock.push(meta_heartbeat())
        await asyncio.sleep(0.2)
        await mock.push(group_message("ping"))
        got_message = await wait_until(lambda: conn.event_queue.qsize() == before + 1)
        payload = await asyncio.wait_for(conn.event_queue.get(), 1)
        runner.check(
            "A5 meta 不进队列、message 进队列",
            conn.event_queue.qsize() == before and got_message
            and payload.get("post_type") == "message",
            f"qsize={conn.event_queue.qsize()}/{before} payload={payload.get('post_type')}",
        )

        results = await asyncio.gather(
            conn.call_action("get_status"),
            conn.call_action("get_group_info", group_id=111),
            conn.call_action("get_group_info", group_id=222),
        )
        runner.check(
            "A6 并发动作 echo 不串台",
            results[0].get("online") is True
            and results[1].get("group_id") == 111
            and results[2].get("group_id") == 222,
            str(results),
        )

        tolerant = await conn.call_action("echo_less")
        runner.check("A7 应答缺 echo 时按唯一在途请求匹配", tolerant == {"message_id": 1}, str(tolerant))

        try:
            await conn.call_action("fail_test")
            runner.check("A8 retcode!=0 抛 ActionFailed", False, "没有抛异常")
        except ActionFailed as exc:
            runner.check(
                "A8 retcode!=0 抛 ActionFailed 且带上信封字段",
                exc.retcode == 100 and exc.status == "failed" and exc.detail == "请求失败",
                str(exc),
            )

        started = time.monotonic()
        try:
            await conn.call_action("no_reply", timeout=0.5)
            runner.check("A9 无应答超时抛 ConnectionUnavailable", False, "没有抛异常")
        except ConnectionUnavailable:
            elapsed = time.monotonic() - started
            runner.check("A9 无应答超时抛 ConnectionUnavailable", elapsed < 2.0, f"{elapsed:.2f}s")

        # 超时边界：0.2s 的慢应答要在 1s 超时内成功
        mock.slow_actions["get_status"] = 0.2
        slow_ok = await conn.call_action("get_status", timeout=1.0)
        # 2.0s 的慢应答必须在 0.5s 超时内失败
        mock.slow_actions["get_status"] = 2.0
        slow_failed = False
        try:
            await conn.call_action("get_status", timeout=0.5)
        except ConnectionUnavailable:
            slow_failed = True
        finally:
            mock.slow_actions.pop("get_status", None)
        runner.check(
            "A9b 慢应答边界（0.2s 内成功 / 2.0s 超时）",
            slow_ok.get("online") is True and slow_failed,
            f"slow_ok={slow_ok} slow_failed={slow_failed}",
        )

        try:
            await conn.call_action("definitely_not_an_action")
            runner.check("A10 未知动作 1404 按失败处理", False, "没有抛异常")
        except ActionFailed as exc:
            runner.check("A10 未知动作 1404 按失败处理", exc.retcode == 1404, str(exc))

        # A11：发一个「永远不回」的动作，然后从 mock 侧掐断连接
        pending_task = asyncio.create_task(conn.call_action("no_reply", timeout=10))
        in_flight = await wait_until(lambda: conn.pending_actions == 1)
        await mock.clients[0].close()
        try:
            await asyncio.wait_for(pending_task, 3)
            runner.check("A11 断线后在途请求立即失败", False, "没有抛异常")
        except ConnectionUnavailable:
            runner.check("A11 断线后在途请求立即失败", in_flight)
        except asyncio.TimeoutError:
            runner.check("A11 断线后在途请求立即失败", False, "一直等到超时了")

        runner.check("A12 断线后 connected=False", await wait_until(lambda: not conn.connected))

        # ============================================== B 组：发送与边界（9 项）
        runner.check(
            "B6 断线后自动重连（指数退避）",
            await wait_until(lambda: conn.connected and len(mock.clients) == 1, 6),
        )

        mock.actions.clear()
        data = await conn.send_message("hi", message_type="group", group_id=123456)
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B1 send_msg 群消息参数正确",
            data.get("message_id") == 1
            and sent.get("message_type") == "group"
            and sent.get("group_id") == 123456
            and sent.get("auto_escape") is False,
            str(sent),
        )
        runner.check(
            "B2 message 是消息段数组（跟随 array 格式）",
            isinstance(sent.get("message"), list)
            and sent["message"][0]["type"] == "text"
            and sent["message"][0]["data"]["text"] == "hi",
            str(sent.get("message")),
        )

        mock.actions.clear()
        await conn.send_message("hi", message_type="private", user_id="169699201")
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B3 私聊不带 group_id，且 id 转成 int",
            sent.get("message_type") == "private"
            and sent.get("user_id") == 169699201
            and "group_id" not in sent,
            str(sent),
        )

        await mock.push(group_message("ping", message_format="string"))
        detected = await wait_until(lambda: conn.message_format_detected == "string")
        mock.actions.clear()
        await conn.send_message("hi", message_type="group", group_id=1)
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B4 收到 string 事件后改为 CQ 字符串出参",
            detected and isinstance(sent.get("message"), str) and sent["message"] == "hi",
            str(sent.get("message")),
        )

        mock.actions.clear()
        await conn.send_message("[CQ:at,qq=1]", message_type="group", group_id=1, auto_escape=True)
        sent = (mock.last_action("send_msg") or {}).get("params", {})
        runner.check(
            "B5 auto_escape=True 时 CQ 码原样透传",
            sent.get("auto_escape") is True and sent.get("message") == "[CQ:at,qq=1]",
            str(sent),
        )

        await conn.stop()
        runner.check("B7 stop() 后 connected=False", not conn.connected)
        try:
            await conn.call_action("get_status", transport="ws")
            runner.check("B8 无通道 + transport=ws 抛 ConnectionUnavailable", False, "没有抛异常")
        except ConnectionUnavailable:
            runner.check("B8 无通道 + transport=ws 抛 ConnectionUnavailable", True)
        try:
            await conn.call_action("get_status", transport="auto")
            runner.check("B9 无通道 + auto 时暂抛（M5 接上 HTTP 后会改）", False, "没有抛异常")
        except ConnectionUnavailable:
            runner.check("B9 无通道 + auto 时暂抛（M5 接上 HTTP 后会改）", True)
    finally:
        await conn.stop()
        await mock.stop()
    return runner.finish()


def test_connection_against_mock():
    # 断言失败时 finish() 返回 1 → 测试红；全过返回 0 → 测试绿
    assert asyncio.run(_case()) == 0
