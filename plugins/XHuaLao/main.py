import json
import time

from api import (
    Bot,
    Event,
    RunInLoop,
    on_command,
    DEFAULT_PLUGINS_DATA_PATH
)


@RunInLoop
def GroupMessageStatistics(
    bot: Bot,
    event: Event
):
        group_id = event.get_group_id
        sender_id = event.get_user_id
        sender_name = event.get_user_name if event.get_user_name != '' else event.get_user_name
    
        with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json", encoding="utf-8", mode='r') as f:
            data = json.load(f)

        if group_id not in data:
            data.update(
                {
                    group_id: {
                        sender_id: {
                            "user_name": sender_name,
                            "count": 1
                        }
                    }
                }
            )
            
            with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupRecordingTime.json") as f:
                data_ = json.load(f)
                data_.update({
                    group_id: time.strftime('%Y.%m.%d',time.localtime(time.time()))
                })
            with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupRecordingTime.json", mode='w') as f:
                json.dump(data_, f)
        if sender_id not in data[group_id]:
            data[group_id].update(
                {
                    sender_id: {
                        "user_name": sender_name,
                        "count": 1
                    }
                }
            )
        else:
            data[group_id][sender_id]["user_name"] = sender_name
            data[group_id][sender_id]["count"] += 1
            
        with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json", encoding="utf-8", mode='w') as f:
            json.dump(data, f)


@on_command("话痨排行榜")
async def PhimosisRanking(
    bot: Bot,
    event: Event
):
    t1 = time.time()
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)
    t2 = time.time()

    data_ = dict(sorted(data[event.get_group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    i = 1
    s = [f"看看你们多能聊！查个聊天记录都用了{t2 - t1}秒！"]
    for k, v in data_.items():
        s.append(f"{i}. {v['user_name']}共发送消息 {v['count']} 条")
        i += 1
    s = '\n'.join(s[:10])
    # s = '\n'.join(s[:10]) + f"\n更多信息请访问 http://{requests.get('https://checkip.amazonaws.com').text.strip()} ~"
    
    await bot.send(event.get_group_id, s)


@on_command("话痨排行榜 -a")
async def DisplayCompleteRanking(
    bot: Bot,
    event: Event
):
    t1 = time.time()
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)
    t2 = time.time()

    data_ = dict(sorted(data[event.get_group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    i = 1
    s = [f"看看你们多能聊！查个聊天记录都用了{t2 - t1}秒！"]
    for k, v in data_.items():
        s.append(f"{i}. {v['user_name']}共发送消息 {v['count']} 条")
        i += 1
    s = '\n'.join(s)
    
    await bot.send(event.get_group_id, s)



