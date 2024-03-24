"""
@FrameWorkName: HysialX
@FrameWorkAuthor: Rainch_<ancdngding@qq.com>
@FrameWorkLicense: MIT
@FrameWorkAddress: https://github.com/Xinre-L-awa/HysialX
"""
import re
import sys
import json
import signal
import asyncio
import websocket
from threading import Thread
from api import (
    Bot,
    NoticeEvent,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    OnWaitingEvent,
    run_func,
    set_device,
    await_run_func,
    get_func_pool,
    get_notice_func_pool,
    get_waiting_task_pool,
    getExpectedFuncs
)
from pool import WaitingTask
from script import (
    init,
    logger,
    load_plugins,
    check_whether_func
)
from htyping import NoticeEvents
from plugins.manager import WaitingFuncMeta


@logger.catch
def message_preprocessor(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    sender_message = event.get_message
    if isinstance(event, GroupMessageEvent):
        logger.info(f"收到群 {event.get_group_id} 中来自 {event.get_user_group_name if event.get_user_group_name != '' else event.get_user_name}({event.get_user_id}) 的消息: {sender_message}")
    else:
        logger.info(f"收到来自好友 {event.get_user_name} 的消息：{sender_message}")

    for func in loopFuncs:
        if isinstance(event, func._func.__annotations__["event"]):
            func(bot, event)
        
        
    for func in customFuncs:
        try:
            if msg := func.custom_response_method(sender_message) and isinstance(event, func._func.__annotations__["event"]):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(msg)
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
        except:
            ...
    
    toBeRemoved = []
    for task in get_waiting_task_pool():
        # bot.func = WaitingFuncMeta(func)
        if event.get_group_id == task.group_id and event.get_user_id == task.user_id:
            toBeRemoved.append(task)
            wevent = OnWaitingEvent(event)
            if "input" in task.response_method:
                wevent.input_value = event.get_message
            asyncio.run(
                await_run_func(
                    task.func,
                    bot, wevent
                )
            )
    else:
        get_waiting_task_pool().pop_tasks(toBeRemoved)
        
    if possible_funcs := check_whether_func(sender_message, get_func_pool()):
        for func in possible_funcs:
            if not isinstance(event, func._func.__annotations__["event"]): continue
            bot.func = func
            logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")
            if func.match_pattern == "on_keyword":
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
                if func.block: break
            elif func.match_pattern == "on_at" and f"[CQ:at,qq={func.at if func.at else event.get_self_id}]" in sender_message:
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(event.get_message.replace(f"[CQ:at,qq={func.at}]", ''))
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
                if func.block: break
            elif func.match_pattern == "on_regex" and re.search(func.regex, sender_message):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                event.set_message(re.search(func.regex, sender_message).group(1))
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
                if func.block: break
            elif func.match_pattern == "on_command" and sender_message == func.cmd:
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
                if func.block: break
            elif func.match_pattern == "on_waiting" and (sender_message == func.cmd or func.custom_response_method(sender_message)):
                logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
                func: WaitingFuncMeta
                get_waiting_task_pool().add_task(WaitingTask(func.child_func, user_id=event.get_user_id, group_id=event.get_group_id))
                # get_waiting_pool().add_task(WaitingTask(func, user_id=event.get_user_id, group_id=event.get_group_id, response_method=["get_value"]))
                bot.func = func
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
                if func.block: break


@logger.catch
def notice_preprocessor(bot: Bot, event: NoticeEvent):
    notices = {
        "group_increase": "群成员增加",
        "group_decrease": "群成员减少"
    }
    if event.notice_type in ("group_increase", "group_decrease"):
        logger.info(f"收到来自 {event.group_id} 的通知 {notices[event.notice_type]}")
    
    for func in get_notice_func_pool():
        logger.opt(colors=True).info(f"Checking priority <b>{func.priority}</b>...")
        if func.notice_type == event.get_notice_int_type:
            logger.opt(colors=True).info(f"触发 <y>{func.name}</y>")
            asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
            if func.block: break


def switch_type(type_: str):
    return {
        "notice":  notice_preprocessor,
        "message": message_preprocessor
    }.get(type_, lambda *_: ...)


BOT_ID: int = None

@logger.catch
def handle(ws, message):
    _ = json.loads(message)
    if _.get("meta_event_type") == "lifecycle":
        global BOT_ID
        BOT_ID = int(_.get("self_id"))
        logger.opt(colors=True).success("Connected successfully!")
        logger.info(f"The current bot account is {BOT_ID}")
        asyncio.run(set_device("114514 大粪手机"))
        return

    post_type = _.get('post_type')
    
    bot = Bot()
    event = None
    if post_type == "message":
        event = MessageEvent(BOT_ID, _)

        if event.get_message_type == "group":
            event = event.ToGroupMessageEvent()
        elif event.get_message_type == "private":
            event = event.ToPrivateMessageEvent()
    elif post_type == "notice":
        print(_)
        event = NoticeEvent.model_validate(_)
    
    switch_type(post_type)(bot, event)


def start():
    ws = websocket.WebSocketApp(
        GOCQWSURL,
        on_message=handle
    )
    ws.run_forever()
    

def signal_handler(signal, frame):
    logger.opt(colors=True).info("Closed")
    sys.exit(0)


if __name__ == "__main__":
    init(False)
    load_plugins()
    is_InLoop = True
    GOCQWSURL = "ws://127.0.0.1:1696/event"
    loopFuncs = getExpectedFuncs(get_func_pool(), "RunInLoop")
    customFuncs = getExpectedFuncs(get_func_pool(), "custom")
    onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")

    [run_func(func) for func in onstartupFuncs]

    # func: WaitingFuncMeta
    # for func in get_func_pool():
    #     if isinstance(func, WaitingFuncMeta) and func.isChildFunc:
    #         func()

    logger.info("Trying to connect go-cqhttp...")
    try:
        t = Thread(target=start)
        t.daemon = True
        t.start()
    except Exception as e:
        logger.exception(e)
        logger.opt(colors=True).error(e)
        
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    while is_InLoop:
        pass
else:
    loopFuncs = getExpectedFuncs(get_func_pool(), "RunInLoop")
    customFuncs = getExpectedFuncs(get_func_pool(), "custom")
    onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")
