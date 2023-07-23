"""
@FrameWorkName: HysialX
@FrameWorkAuthor: Xinre<ancdngding@qq.com>
@FrameWorkLicense: MIT
@FrameWorkAddress: https://github.com/Xinre-L-awa/HysialX
"""
import re
import json
import time
import asyncio
import websocket
from script import *
from flask import Flask

init()
import plugins

app = Flask(__name__)


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


async def PhimosisRanking(
    send_func: Callable, 
    group_id, 
    *args
):
    t1 = time.time()
    with open("GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)
    t2 = time.time()

    data_ = dict(sorted(data[group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    i = 1
    s = [f"看看你们多能聊！查个聊天记录都用了{t2 - t1}秒！"]
    for k, v in data_.items():
        s.append(f"{i}. {v['user_name']}共发送消息 {v['count']} 条")
        i += 1
    s = '\n'.join(s[:10])
    logger.debug(s)
    await send_func(group_id, s)


async def DisplayCompleteRanking(
    send_func: Callable, 
    group_id, 
    *args
):
    t1 = time.time()
    with open("GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)
    t2 = time.time()

    data_ = dict(sorted(data[group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    i = 1
    s = [f"看看你们多能聊！查个聊天记录都用了{t2 - t1}秒！"]
    for k, v in data_.items():
        s.append(f"{i}. {v['user_name']}共发送消息 {v['count']} 条")
        i += 1
    s = '\n'.join(s)
    logger.debug(s)
    await send_func(group_id, s)


func_dict = {
    "话痨排行榜": [
        PhimosisRanking, 
        "on_command"
    ],
    "话痨排行榜 -a": [
        DisplayCompleteRanking, 
        "on_command"
    ]
}
func_dict.update(plugins.func_dicts)


async def DisplayAllFunc(
    send_func: Callable, 
    group_id, 
    *args
):
    mes = []
    for func_name, _ in func_dict.items():
        mes.append(f"{func_name}")
    await send_func(group_id, '\n'.join(mes))

func_dict.update(
    {
        "菜单": [
            DisplayAllFunc,
            "on_command"
        ]
    }
)


@logger.catch
def handle(ws, message):
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

        GroupMessageStatistics(
            group_id, 
            sender_id, 
            sender_name
        )
        
        message_ = sender_message.split()[0]
        if message_ in func_dict:
            if func_dict[message_][1] == "on_keyword":
                para_message = re.search(f"{message_}(.*)", sender_message).group(1)
                logger.debug(para_message)
                logger.info(len(para_message))
                asyncio.run(func_dict[message_][0](
                        sends,
                        group_id,
                        sender_id,
                        sender_name,
                        para_message
                    )
                )
            else:
                asyncio.run(func_dict[sender_message][0](
                        sends,
                        group_id,
                        sender_id,
                        sender_name,
                    )
                )


if __name__ == "__main__":

    logger.opt(colors=True).info("Trying to connect go-cqhttp...")
    try:
        ws = websocket.WebSocketApp(
                "ws://127.0.0.1:8081/event",
                on_message=handle
            )
        logger.opt(colors=True).success("Connected successfully!")
        ws.run_forever()
    except Exception as e:
        logger.opt(colors=True).error(e)
    logger.opt(colors=True).info("Closed")

else:
    logger.debug(func_dict)
