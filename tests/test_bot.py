# tests/test_bot.py
import asyncio

from mock_snowluma import CaseRunner, MockSnowLuma, group_message
from api.bot import Bot
from api.event import GroupMessageEvent
from api.exception import FinishException
from api import get_waiting_task_pool, set_connection
from snowluma.config import SnowLumaConfig
from snowluma.connection import OneBotConnection
from snowluma.exception import ActionFailed


def config_for(mock: MockSnowLuma, **overrides) -> SnowLumaConfig:
    """与 test_connection.py 里同名助手保持一致"""
    cfg = SnowLumaConfig(
        mode="forward",
        forward_url=f"ws://127.0.0.1:{mock.ws_port}/", forward_token=mock.ws_token,
        http_base=f"http://127.0.0.1:{mock.http_port}", http_token=mock.http_token,
        api_transport="ws", message_format="auto",
        request_timeout=1.0, reconnect_interval=1.0, ping_interval=0, ping_timeout=0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


async def _case() -> int:
    runner = CaseRunner()
    mock = None
    conn = None
    try:
        mock = await MockSnowLuma(ws_port=0, http_port=0).start()      # 端口 0：让系统分配，避免固定端口占用
        conn = OneBotConnection(config_for(mock))
        await conn.start()
        runner.check("C0 连上 mock", await conn.wait_until_connected(3))
        set_connection(conn)                       # 全局状态：finally 里必须还原
        bot = Bot()

        # C1 私聊别名不能再发成群
        await bot.send_user(169699201, "hi")
        sent = mock.last_action("send_msg")
        runner.check("C1 send_user 走 private",
                     sent is not None and sent["params"]["message_type"] == "private",
                     str(sent))

        # C2 群里 reply 发到群，且带 reply 前缀
        ev = GroupMessageEvent(999, group_message("hi"))
        await bot.reply(ev, "收到")
        replied = mock.last_action("send_msg")
        msg = replied["params"]["message"] if replied else None
        # array 模式下 reply 前缀是 {"type": "reply"} 段；string 模式下才是 [CQ:reply,...]
        has_reply = bool(msg) and ("CQ:reply" in msg if isinstance(msg, str)
                                   else any(seg.get("type") == "reply" for seg in msg))
        runner.check("C2 reply 发到群且带引用",
                     bool(replied) and replied["params"]["group_id"] == 123456 and has_reply,
                     str(replied))

        # C3 bot.finish 抛 FinishException（插件用它中止后续逻辑）
        try:
            await bot.finish(123456, "结束")
            finished = False
        except FinishException:
            finished = True
        runner.check("C3 finish 抛 FinishException", finished)

        # C4 空消息不发（normalize_cq 只把 "" 判成空；纯空格会被原样发出，这里一并钉住）
        before = len(mock.actions_named("send_msg"))
        result = await bot.send(123456, "")
        after = len(mock.actions_named("send_msg"))
        runner.check("C4 空消息被跳过", result is None and after == before, f"{before}->{after}")

        # C5 call_api 拿得到 data；业务失败（mock 对 group_id=999 注入 retcode 100）必须抛
        status = await bot.call_api("get_status")
        runner.check("C5 call_api 返回 data", isinstance(status, dict) and status.get("online") is True,
                     str(status))
        failed = False
        try:
            await bot.call_api("send_msg", group_id=999, message="x", message_type="group")
        except ActionFailed as exc:
            failed = exc.retcode == 100
        runner.check("C5b call_api 业务失败抛 ActionFailed", failed)

        # C6 delete_msg 走到协议端
        await bot.delete_msg(12345)
        runner.check("C6 delete_msg 发出动作", mock.last_action("delete_msg") is not None)

    finally:
        set_connection(None)
        left = list(get_waiting_task_pool())
        if left:
            get_waiting_task_pool().pop_tasks(left)
        if conn is not None:
            await conn.stop()
        if mock is not None:
            await mock.stop()
    return runner.finish()


def test_bot_against_mock():
    assert asyncio.run(_case()) == 0
