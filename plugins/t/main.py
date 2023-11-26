import json
from loguru import logger
from random import randint
from datetime import datetime
from os import path, mkdir, chdir

from api import (
    Bot,
    Event,
    on_command,
    DEFAULT_PLUGINS_DATA_PATH as data_folder
)

chdir("..")
l = [path.exists(f"{data_folder}/all.json"), path.exists(f"{data_folder}/qian_dao_.json")]
if False in l:
    logger.warning("数据文件不存在, 即将创建")
    if not l[0]:
        with open(f"{data_folder}/all.json", 'r+') as f:
            f.write("{}")
    if not l[1]:
        with open(f"{data_folder}/qian_dao_.json", 'r+') as f:
            f.write("{}")
    logger.success("数据文件创建成功!")
chdir("plugins")


def getDate():
    now = datetime.now()
    return f"{now.year}-{now.month}-{now.day}"


@on_command("个人信息")
async def DisplayUserPanel(
    bot: Bot,
    event: Event
):
    user_id = event.get_user_id
    group_id = event.get_group_id
    
    with open(f"{data_folder}/wealth.json", 'r') as f:
        data = json.load(f)

    if group_id not in data or user_id not in data[group_id]:
        await bot.send(
            group_id,
            f"[CQ:at,qq={user_id}] 查无数据！"
        )

    await bot.send(
        group_id, 
        f"[CQ:at,qq={user_id}]\n"
        f"[CQ:image,file=https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100]\n"
        f"金钱: {data[group_id][user_id]['money']}"
    )


@on_command("签到")
async def qian_dao(
    bot: Bot,
    event: Event
):
    user_id = event.get_user_id
    group_id = event.get_group_id
    
    with open(f"{data_folder}/qian_dao_.json", 'r') as f:
        qian_dao_ = json.load(f)
        
    today = getDate()

    if group_id in qian_dao_ and user_id in qian_dao_[group_id] and qian_dao_[group_id][user_id][-1] == today:
        await bot.send(group_id, f"[CQ:at,qq={user_id}]您今天已签到！")

    with open(f"{data_folder}/all.json", 'r') as f:
        wealth_data = json.load(f)

    money = randint(200, 400)
    if group_id not in wealth_data:
        wealth_data[group_id] = {
            user_id: {
                "user_name": event.get_user_name,
                "money":     money
            }
        }
    else:
        wealth_data[group_id][user_id]["money"] += money

    with open(f"{data_folder}/wealth.json", 'w') as f:
        json.dump(wealth_data, f)

    if group_id not in qian_dao_:
        qian_dao_[group_id] = {}
    if user_id not in qian_dao_[group_id]:
        qian_dao_[group_id][user_id] = [today]
    else:
        qian_dao_[group_id][user_id].append(today)

    with open(f"{data_folder}/qian_dao_.json", 'w') as f:
        json.dump(qian_dao_, f)

    await bot.send(
        group_id, 
        f"[CQ:at,qq={user_id}]\n"
        f"[CQ:image,file=https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100]\n"
        f"今日签到获取了 {money} 金钱"
    )



