"""
@FrameWorkName: HysialX
@FrameWorkAuthor: Xinre<ancdngding@qq.com>
@FrameWorkLicense: MIT
@FrameWorkAddress: https://github.com/Xinre-L-awa/HysialX
"""
import re
import json
import asyncio
import websocket
from script import *

init(False)
from api import Bot, Event
from plugins import func_dicts as func_dict


autorunFuncs = getExpectedFuncs(func_dict, "AutoRun")
onstartupFuncs = getExpectedFuncs(func_dict, "on_startup")


for func in onstartupFuncs:
    func[0]()


@logger.catch
def handle(ws, message):
    _ = json.loads(message)
    message_type = _.get('message_type')
    
    bot = Bot(func_dict)
    event = Event(_)
    
    if message_type == "group":
        group_id = str(_['group_id'])
        sender_name = _['sender']['nickname'].encode('utf-8').decode('utf-8')
        logger.debug(sender_name)
        sender_id = str(_['sender']['user_id'])
        sender_message = _['message']
        logger.info(f"收到群 {group_id} 中来自 {sender_name}({sender_id}) 的消息: {sender_message}")

        for func in autorunFuncs:
            func[0](bot, event)
        
        possible_func_name = sender_message.split()[0]
        if possible_func_name in func_dict:
            mode = func_dict[possible_func_name][1]
            if mode == "on_keyword":
                asyncio.run(
                    func_dict[possible_func_name][0](
                        bot,
                        event
                    )
                )
            elif mode == "on_regex":
                event.set_message(re.search(func_dict[possible_func_name][2], sender_message).group(1))
                asyncio.run(
                    func_dict[possible_func_name][0](
                        bot,
                        event
                    )
                )
            elif mode == "on_command" and sender_message == possible_func_name:
                asyncio.run(
                    func_dict[sender_message][0](
                        bot,
                        event
                    )
                )


if __name__ == "__main__":
    logger.opt(colors=True).info("Trying to connect go-cqhttp...")
    try:
        ws = websocket.WebSocketApp(
                "ws://39.107.60.77:8081/event",
                on_message=handle
            )
        logger.opt(colors=True).success("Connected successfully!")
        ws.run_forever()
    except Exception as e:
        logger.opt(colors=True).error(e)
    logger.opt(colors=True).info("Closed")
