import json
import asyncio
import websocket
from flask import Flask
from script import *

import plugins

app = Flask(__name__)


@logger.catch
def GroupMessageStatistics(group_id, sender_id, sender_name):
    try:
        with open("GroupStatistics.json", encoding="utf-8", mode='r') as f:
            data = json.load(f)

        if group_id not in data:
            data[group_id] = {
                sender_id: {
                    "user_name": sender_name,
                    "count": 1
                }
            }
        if sender_id not in data[group_id]:
            data[group_id][sender_id] = {
                "user_name": sender_name,
                "count": 1
            }
        else:
            data[group_id][sender_id]["count"] += 1

        with open("GroupStatistics.json", encoding="utf-8", mode='w') as f:
            json.dump(data, f)
    except:
        data = {
            group_id: {
                sender_id: {
                    "user_name": sender_name,
                    "count": 1
                }
            }
        }

        with open("GroupStatistics.json", encoding="utf-8", mode='w') as f:
            json.dump(data, f)


@logger.catch
def PhimosisRanking(send_func: Callable = None, group_id=None, sender_id=None, sender_name=None, message=None):
    with open("GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)

    data = data[group_id]
    i = 1
    s = []
    for k, v in data.items():
        s.append(f"{i}. {v['user_name']}共发送消息 {v['count']} 条")
        i += 1
    s = '\n'.join(s)
    logger.debug(s)
    asyncio.run(sends(group_id, s))


func_dict = {
    "话痨排行榜": PhimosisRanking
}
func_dict.update(plugins.func_dicts)


@logger.catch
def on_message(ws, message):
    _ = json.loads(message)
    post_type = _.get('post_type')
    message_type = _.get('message_type')
    if message_type == "group":
        group_id = str(_['group_id'])
        sender_name = _['sender']['nickname'].encode('utf-8').decode('utf-8')
        logger.debug(sender_name)
        sender_id = str(_['sender']['user_id'])
        sender_message = _['message']
        logger.info(f"收到群 {group_id} 中来自 {sender_name}({sender_id}) 的消息: {sender_message}")

        GroupMessageStatistics(group_id, sender_id, sender_name)
        if sender_message in func_dict: asyncio.run(func_dict[sender_message](sends,
                                                                              group_id,
                                                                              sender_id,
                                                                              sender_name,
                                                                              sender_message))


if __name__ == "__main__":

    logger.opt(colors=True).info("Trying to connect go-cqhttp...")
    try:
        def on_open():
            logger.opt(colors=True).info("Connected successfully!")


        ws = websocket.WebSocketApp("ws://localhost:8080/event",
                                    on_open=on_open,
                                    on_message=on_message)
        logger.opt(colors=True).success("Connected successfully!")
        ws.run_forever()
    except Exception as e:
        logger.opt(colors=True).error(e)
    logger.opt(colors=True).info("Closed")

else:
    logger.debug(func_dict)
