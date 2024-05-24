import json
import time
import base64
# from io import BytesIO
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService

from api import (
    Bot,
    GroupMessageEvent,
    RunInLoop,
    on_command,
    DEFAULT_PLUGINS_DATA_PATH
)


@RunInLoop
def GroupMessageStatistics(
    bot: Bot,
    event: GroupMessageEvent
):
        group_id = event.get_group_id
        sender_id = event.get_user_id
        sender_name = event.get_user_group_name if event.get_user_group_name != '' else event.get_user_name
    
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
async def PhimosisRankingInPhoto(
    bot: Bot,
    event: GroupMessageEvent
):
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--remote-debugging-port=9222')
    options.add_argument('--single-process')

    driver = webdriver.Chrome(service=ChromeService(executable_path="chromedriver"))


    driver.get(f"http://127.0.0.1:1145/{event.get_group_id}")
    # driver.save_screenshot("sc.png")

    screenshot = driver.get_screenshot_as_png()
    driver.quit()

    # screenshot_buffer = BytesIO(screenshot)

    # 将图片转换为base64字符串
    img_str = base64.b64encode(screenshot).decode('utf-8')

    await bot.send(event.get_group_id, f"[CQ:image,file=base64://{img_str}]")


@on_command("话痨排行榜 -t")
async def PhimosisRanking(
    bot: Bot,
    event: GroupMessageEvent
):
    t1 = time.time()
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)
    t2 = time.time()

    data_ = dict(sorted(data[event.get_group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    i = 1
    s = [f"看看你们多能聊！查个聊天记录都用了{t2 - t1}秒！"]
    for _, v in data_.items():
        s.append(f"{i}. {v['user_name']}共发送消息 {v['count']} 条")
        i += 1
        if i == 11: break
    s = '\n'.join(s)
    # s = '\n'.join(s[:10]) + f"\n更多信息请访问 http://{requests.get('https://checkip.amazonaws.com').text.strip()} ~"
    
    await bot.send(event.get_group_id, s)


@on_command("话痨排行榜 -m")
async def DisplayCompleteRanking(
    bot: Bot,
    event: GroupMessageEvent
):
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json", encoding="utf-8", mode='r') as f:
        data = json.load(f)

    data_ = dict(sorted(data[event.get_group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    i = 1
    res = ""
    for _, v in data_.items():
        if v['user_name'] == event.get_user_group_name if event.get_user_group_name != '' else event.get_user_name:
            res = f"{i}. {v['user_name']}共发送消息 {v['count']} 条"
        i += 1
    
    await bot.send(event.get_group_id, res)
