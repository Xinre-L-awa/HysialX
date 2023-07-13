import json
from loguru import logger
from random import randint
from typing import Callable
from datetime import datetime
from os import path, mkdir, chdir


data_folder = "./DataForXPlugin"

chdir("..")
if not path.exists(data_folder):
    mkdir(data_folder)
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


async def DisplayUserPanel(
    send_func: Callable,
    group_id: str,
    sender_id: str,
    sender_name: str
):
    with open(f"{data_folder}/wealth.json", 'r') as f:
        data = json.load(f)

    await send_func(group_id, f"[CQ:at,qq={sender_id}]\n"
                              f"[CQ:image,file=https://q1.qlogo.cn/g?b=qq&nk={sender_id}&s=100]\n"
                              f"金钱: {data[group_id][sender_id]['money']}")


async def qian_dao(
    send_func: Callable,
    group_id: str,
    sender_id: str,
    sender_name: str
):
    with open(f"{data_folder}/qian_dao_.json", 'r') as f:
        qian_dao_ = json.load(f)
        
    today = getDate()

    if group_id in qian_dao_ and sender_id in qian_dao_[group_id] and qian_dao_[group_id][sender_id][-1] == today:
        await send_func(group_id, f"[CQ:at,qq={sender_id}]您今天已签到！")
        return

    with open(f"{data_folder}/all.json", 'r') as f:
        wealth_data = json.load(f)

    money = randint(200, 400)
    if group_id not in wealth_data:
        wealth_data[group_id] = {
            sender_id: {
                "user_name": sender_name,
                "money":     money
            }
        }
    else:
        wealth_data[group_id][sender_id]["money"] += money

    with open(f"{data_folder}/wealth.json", 'w') as f:
        json.dump(wealth_data, f)

    if group_id not in qian_dao_:
        qian_dao_[group_id] = {}
    if sender_id not in qian_dao_[group_id]:
        qian_dao_[group_id][sender_id] = [today]
    else:
        qian_dao_[group_id][sender_id].append(today)

    with open(f"{data_folder}/qian_dao_.json", 'w') as f:
        json.dump(qian_dao_, f)

    await send_func(
        group_id, 
        f"[CQ:at,qq={sender_id}]\n"
        f"[CQ:image,file=https://q1.qlogo.cn/g?b=qq&nk={sender_id}&s=100]\n"
        f"今日签到获取了 {money} 金钱"
    )


func_dict = {
    "签到": [
        qian_dao,
        "on_command"
    ],
    "个人信息": [
        DisplayUserPanel,
        "on_command"
    ]
}
