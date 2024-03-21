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
    Event,
    OnWaitingEvent,
    run_func,
    set_device,
    await_run_func,
    get_func_pool,
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
from plugins.manager import WaitingFuncMeta


@logger.catch
def group_message_preprocessor(bot: Bot, event: Event):
    sender_message = event.get_message
    logger.info(f"收到群 {event.get_group_id} 中来自 {event.get_group_name if event.get_group_name != '' else event.get_user_name}({event.get_user_id}) 的消息: {sender_message}")

    

    for func in loopFuncs:
        func(bot, event)
        
    for func in customFuncs:
        try:
            if msg := func.custom_response_method(sender_message):
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
                print(event.get_message)
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
            bot.func = func
            if func.match_pattern == "on_keyword":
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
            elif func.match_pattern == "on_regex":
                event.set_message(re.search(func.regex, sender_message).group(1))
                print(event.get_message)
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
            elif func.match_pattern == "on_command" and sender_message == func.cmd:
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )
            elif func.match_pattern == "on_waiting" and (sender_message == func.cmd or func.custom_response_method(sender_message)):
                func: WaitingFuncMeta
                get_waiting_task_pool().add_task(WaitingTask(func.child_func, user_id=event.get_user_id, group_id=event.get_group_id))
                # print(func.child_func)
                # print(get_waiting_task_pool().waiting_tasks)
                # get_waiting_pool().add_task(WaitingTask(func, user_id=event.get_user_id, group_id=event.get_group_id, response_method=["get_value"]))
                bot.func = func
                asyncio.run(
                    await_run_func(
                        func,
                        bot, event
                    )
                )


def notice_preprocessor(bot: Bot, event: Event): ...
def private_message_preprocessor(bot: Bot, event: Event): ...


def switch_type(type_: str):
    return {
        "notice":  notice_preprocessor,
        "group":   group_message_preprocessor,
        "private": private_message_preprocessor
    }.get(type_, lambda *_: ...)


@logger.catch
def handle(ws, message):
    _ = json.loads(message)
    if _.get("meta_event_type") == "lifecycle":
        logger.opt(colors=True).success("Connected successfully!")
        logger.info(f"The current bot account is {_.get('self_id')}")
        asyncio.run(set_device("114514 大粪手机"))
        return

    message_type = _.get('message_type')
    
    bot = Bot()
    event = Event(_)
    
    switch_type(message_type)(bot, event)


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
    GOCQWSURL = "ws://127.0.0.1:8080/hysialx/event"
    loopFuncs = getExpectedFuncs(get_func_pool(), "RunInLoop")
    customFuncs = getExpectedFuncs(get_func_pool(), "custom")
    onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")

    [run_func(func) for func in onstartupFuncs]

    func: WaitingFuncMeta
    for func in get_func_pool():
        if isinstance(func, WaitingFuncMeta) and func.isChildFunc:
            func()

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
