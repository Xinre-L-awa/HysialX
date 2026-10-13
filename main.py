"""
@FrameWorkName: HysialX
@FrameWorkAuthor: Rainch_<ancdngding@qq.com>
@FrameWorkLicense: MIT
@FrameWorkAddress: https://github.com/Xinre-L-awa/HysialX
"""
import re
import sys
import signal
import asyncio
import inspect
import datetime
from pydantic import ValidationError
from api import (
    Bot,
    NoticeEvent,
    RequestEvent,
    MessageEvent,
    WaitingEvent,
    await_run_func,
    get_func_pool,
    get_notice_func_pool,
    get_waiting_task_pool,
    get_request_func_pool,
    get_scheduled_task_pool,
    getExpectedFuncs,
    func_accepts_event,
    is_shutdown_requested,
    set_connection,
)
from pool import WaitingTask
from script import (
    init,
    logger,
    load_plugins,
    check_whether_func
)
from plugins.manager import WaitingFuncMeta

from snowluma import OneBotConnection

loopFuncs = None
customFuncs = None
onstartupFuncs = None

def refresh_funcs() -> None:
    """插件加载/重载后刷新常用函数池"""
    global loopFuncs, customFuncs, onstartupFuncs
    loopFuncs = getExpectedFuncs(get_func_pool(), "RunInLoop")
    customFuncs = getExpectedFuncs(get_func_pool(), "custom")
    onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")

async def message_preprocessor(bot: Bot, event: MessageEvent) -> None:
    sender_message = event.get_message          # CQ 串：用于日志与"回显"
    plain_text = event.get_plain_text           # 纯文本：custom 匹配用（保留原始前导空格语义）
    command_text = plain_text.lstrip()          # 命令/关键字匹配用：@机器人 后面通常跟一个空格

    if event.is_group:
        name = event.get_display_name
        logger.info(f"收到群 {event.get_group_id} 中来自 {name}({event.get_user_id}) 的消息: {sender_message}")
    else:
        logger.info(f"收到来自好友 {event.get_user_name} 的消息：{sender_message}")

    # 1.RunInLoop
    for func in loopFuncs:
        if func_accepts_event(func, event):
            await await_run_func(func, bot, event)

    # 2.custom
    for func in customFuncs:
        try:
            matcher = func.custom_response_method
            if matcher and matcher(plain_text) and func_accepts_event(func, event):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(sender_message)
                await await_run_func(func, bot, event)
        except Exception as exc:
            logger.exception(f"custom 响应器 {func.name} 判断失败: {exc}")

    # 3.WaitingTask
    to_be_removed = []
    for task in list(get_waiting_task_pool()):
        # id 一律归一化成 str 再比：事件侧按 M6 契约就是 str，而插件可能传 int
        # （例如 bot.input_value(group_id=event.group_id) 拿到的是原始 int 属性）
        task_group = None if task.group_id is None else str(task.group_id)
        task_user = None if task.user_id is None else str(task.user_id)
        if event.get_group_id == task_group and event.get_user_id == task_user:
            to_be_removed.append(task)
            wevent = WaitingEvent(event)
            if task.response_method and "input" in task.response_method:   # ← 判空，别炸
                wevent.input_value = event.get_message
            await await_run_func(task.func, bot, wevent)
    if to_be_removed:
        get_waiting_task_pool().pop_tasks(to_be_removed)

    # 4.响应器
    # 粗筛只看纯文本（script.check_whether_func），所以 on_at 不在候选里——它的判据是 CQ 串。
    # 消息带了 @机器人 时把 on_at 响应器补进来，否则它们永远不会被触发。
    possible = check_whether_func(command_text, get_func_pool())
    if f"[CQ:at,qq={event.get_self_id}]" in sender_message:
        already = {id(func) for func in possible}
        possible = sorted(
            list(possible) + [func for func in get_func_pool()
                              if func.match_pattern == "on_at" and id(func) not in already],
            key=lambda func: func.priority,
        )
    for func in possible:
        if not func_accepts_event(func, event):
            continue
        bot.func = func
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")

        if func.match_pattern == "on_keyword":
            logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
            await await_run_func(func, bot, event)
            if func.block:
                break

        elif func.match_pattern == "on_at":
            target = func.at or event.get_self_id
            if f"[CQ:at,qq={target}]" in sender_message:            # 用 CQ 串判断"有没有 @"
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(event.get_message.replace(f"[CQ:at,qq={target}]", "", 1).strip())
                await await_run_func(func, bot, event)
                if func.block:
                    break

        elif func.match_pattern == "on_regex":
            match = re.search(func.regex, command_text) if func.regex else None
            if match:
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                if match.groups():
                    event.set_message(match.group(1))
                await await_run_func(func, bot, event)
                if func.block:
                    break

        elif func.match_pattern == "on_command":
            if command_text in func.cmd:
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                await await_run_func(func, bot, event)
                if func.block:
                    break

        elif func.match_pattern == "on_waiting":
            if (func.cmd == "JUSTCHILD"):
                continue
            matcher = func.custom_response_method
            if command_text == func.cmd or (matcher and matcher(plain_text)):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                bot.func = func
                if func.child_func is None:
                    logger.warning(f"响应器 {func.name} 没有子函数（add_child_func 没配），跳过等待任务")
                else:
                    get_waiting_task_pool().add_task(WaitingTask(
                        func.child_func, user_id=event.get_user_id, group_id=event.get_group_id))
                await await_run_func(func, bot, event)
                if func.block:
                    break
    
async def notice_preprocessor(bot: Bot, event: NoticeEvent) -> None:
    logger.info(f"收到通知 {event.notice_type}"
                + (f"/{event.sub_type}" if event.sub_type else "")
                + f"，来自 {event.group_id or event.user_id}")
    for func in list(get_notice_func_pool()):       # list() 快照：池子提前 break 不会留下半截游标
        if func.notice_type is not None and func.notice_type != event.get_notice_int_type:
            continue
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")
        logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
        await await_run_func(func, bot, event)
        if func.block:
            break

async def request_preprocessor(bot: Bot, event: RequestEvent) -> None:
    logger.info(f"收到请求 {event.request_type}"
                + (f"/{event.sub_type}" if event.sub_type else "")
                + f"，来自 {event.user_id}，备注: {event.get_comment}")
    for func in list(get_request_func_pool()):      # 同上：快照迭代
        if func.request_type is not None and func.request_type != event.get_request_int_type:
            continue
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")
        logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
        await await_run_func(func, bot, event)
        if func.block:
            break

def _due(task, now: datetime.datetime, stamp: str) -> bool:
    fixed = (task.fixed_execute_time or "").strip()
    if fixed:
        # 支持 "YYYY-MM-DD HH:MM:SS" / "HH:MM:SS" / "HH:MM"；同一秒不重复
        return (stamp == fixed or stamp.endswith(fixed)) and task.last_execution_time != stamp
    frequency = float(task.frequency or 0) or 1.0     # 0 当 1 秒，避免"每秒狂跑"的旧行为
    if not task.last_execution_time:
        return True
    try:
        last = datetime.datetime.strptime(task.last_execution_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (now - last).total_seconds() >= frequency

async def scheduled_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        now = datetime.datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        to_be_removed = []
        for task in list(get_scheduled_task_pool()):
            try:
                if not _due(task, now, stamp):
                    continue
                task.last_execution_time = stamp
                result = task.execute()
                if inspect.isawaitable(result):         # 计划任务也可以是 async def
                    await result
                if task.disposable:
                    to_be_removed.append(task)
            except Exception as exc:
                logger.exception(exc)
        if to_be_removed:
            get_scheduled_task_pool().pop_tasks(to_be_removed)
        await asyncio.sleep(1)          # ← 必须 await：少了它这个循环不让出事件循环，会把整个进程卡死

async def event_loop(connection: OneBotConnection) -> None:
    semaphore = asyncio.Semaphore(max(1, connection.config.event_workers))
    running: set[asyncio.Task] = set()

    async def worker(payload: dict) -> None:
        async with semaphore:
            try:
                await handle_event(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(exc)

    try:
        while True:
            payload = await connection.event_queue.get()
            task = asyncio.create_task(worker(payload), name=f"event-{payload.get('post_type')}")
            running.add(task)
            task.add_done_callback(running.discard)
    except asyncio.CancelledError:
        raise
    finally:
        if running:
            # 必须 await：否则在途 handler 没跑完就直接去关连接了
            await asyncio.gather(*running, return_exceptions=True)

async def handle_event(payload: dict) -> None:
    """解析一条 OneBot 事件并分发（连接层与调试台共用）"""
    if not isinstance(payload, dict):
        return

    post_type = payload.get("post_type")
    if post_type == "meta_event":                # 连接层已消化，理论上不会进来
        return

    bot = Bot()
    try:
        match post_type:
            case "message" | "message_sent":
                await message_preprocessor(bot, MessageEvent.from_payload(payload))
            case "notice":
                await notice_preprocessor(bot, NoticeEvent.model_validate(payload))
            case "request":
                await request_preprocessor(bot, RequestEvent.model_validate(payload))
            case _:
                logger.debug(f"忽略未知事件类型: {post_type}")
    except ValidationError as exc:                # pydantic v2：字段不合规只警告，别炸分发
        logger.warning(f"事件字段不符合 OneBot 协议（post_type={post_type}）: {exc}")

async def shutdown_watcher(stop_event: asyncio.Event) -> None:
    """插件调 `api.shutdown()` 请求退出时，置位 stop_event 走正常关闭流程。

    必须用 `is_shutdown_requested()`：`from api import to_shutdown` 拿到的是导入那一刻的
    布尔副本，之后再调 shutdown() 也永远是 False（旧代码就是这么"退出无效"的）。
    """
    while not stop_event.is_set():
        if is_shutdown_requested():
            logger.opt(colors=True).info("收到插件退出请求，正在关闭 HysialX...")
            stop_event.set()
            return
        await asyncio.sleep(0.5)

async def main_async() -> None:
    config = init()
    load_plugins()
    refresh_funcs()

    for func in onstartupFuncs:
        await await_run_func(func)

    connection = OneBotConnection(config)
    set_connection(connection)
    await connection.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal(signum, frame):
        logger.opt(colors=True).info(f"收到信号 <y>{signum}</y>，正在关闭 HysialX...")
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass                                 # 非主线程等场景

    tasks = [
        asyncio.create_task(event_loop(connection), name="event-loop"),
        asyncio.create_task(scheduled_loop(stop_event), name="scheduled-loop"),
        asyncio.create_task(shutdown_watcher(stop_event), name="shutdown-watcher")   # name 必须用关键字传
    ]

    if connection.connected:
        logger.opt(colors=True).success("已连接到 SnowLuma")
    else:
        # connection.start() 只是"把连接任务起起来"，这里通常还没连上，别急着下结论
        logger.info("HysialX 已启动，正在与 SnowLuma 建立连接（连上后会自动开始收事件）...")

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await connection.stop()
        set_connection(None)
        logger.opt(colors=True).info("Closed")

def main() -> int:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.opt(colors=True).info("Closed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
else:
    refresh_funcs()                              # 被当模块导入（调试台/测试）时也要有池子
