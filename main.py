"""
@FrameWorkName: HysialX
@FrameWorkAuthor: Xinre<ancdngding@qq.com>
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

from script import *; init(False)
from plugins import func_dicts as func_dict
from api import (
    Bot,
    Event,
    set_device,
    get_func_pool,
    getExpectedFuncs
)


is_InLoop = True

loopFuncs = getExpectedFuncs(get_func_pool(), "RunInLoop")
customFuncs = getExpectedFuncs(get_func_pool(), "custom")
onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")

[func() for func in onstartupFuncs]


def group_message_preprocessor(bot: Bot, event: Event):
    sender_message = event.get_message
    logger.info(f"收到群 {event.get_group_id} 中来自 {event.get_user_group_name if event.get_user_group_name != '' else event.get_user_name}({event.get_user_id}) 的消息: {sender_message}")

    for func in loopFuncs:
        func(bot, event)
        
    for func in customFuncs:
        try:
            if msg := func.custom_response_method(sender_message):
                event.set_message(msg)
                asyncio.run(
                    func(
                        bot,
                        event
                    )
                )
        except:
            ...
        
    if possible_funcs := check_whether_func(sender_message, get_func_pool()):
        for func in possible_funcs:
            print(func)
            if func.match_pattern == "on_keyword":
                asyncio.run(
                    func(
                        bot,
                        event
                    )
                )
            elif func.match_pattern == "on_regex":
                event.set_message(re.search(func.regex, sender_message).group(1))
                print(event.get_message)
                asyncio.run(
                    func(
                        bot,
                        event
                    )
                )
            elif func.match_pattern == "on_command" and sender_message == func.cmd:
                asyncio.run(
                    func(
                        bot,
                        event
                    )
                )


@logger.catch
def handle(ws, message):
    _ = json.loads(message)
    message_type = _.get('message_type')
    
    bot = Bot()
    event = Event(_)
    
    if message_type == "group":
        group_message_preprocessor(bot, event)


def start():
    ws = websocket.WebSocketApp(
            "ws://127.0.0.1:8080/event",
            on_message=handle
        )
    ws.run_forever()


def signal_handler(signal, frame):
    logger.opt(colors=True).info("Closed")
    sys.exit(0)


if __name__ == "__main__":
    logger.opt(colors=True).info("Trying to connect go-cqhttp...")
    try:
        t = Thread(target=start)
        t.daemon = True
        t.start()
        logger.opt(colors=True).success("Connected successfully!")
        asyncio.run(set_device("114514 大粪手机"))
    except Exception as e:
        logger.exception(e)
        logger.opt(colors=True).error(e)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    while is_InLoop:
        pass
