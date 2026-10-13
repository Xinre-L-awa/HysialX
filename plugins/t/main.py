import asyncio
import json
import os
from pathlib import Path

from loguru import logger
from random import randint
from datetime import datetime

from api import (
    Bot,
    GroupMessageEvent,
    on_command
)

# 刻意 **不** 用 chdir：import 插件的进程不应改变工作目录。
# 也刻意 **不** 在 import 期解析/创建任何路径与文件，全部推迟到真正要读写的函数体里。


def _data_dir() -> Path:
    """数据目录：跟随框架常量（测试/部署可重定向），相对路径按仓库根解析，不依赖 cwd。

    `DEFAULT_PLUGINS_DATA_PATH` 默认是 "./DataForXPlugin"（框架给的是相对路径），
    这里按本文件位置（<仓库根>/plugins/t/main.py → parents[2] 是仓库根）解析成绝对路径，
    避免运行目录不同就跑到别处去。每次调用都重新 `import api` 取常量，
    这样测试 monkeypatch `api.DEFAULT_PLUGINS_DATA_PATH` 后立刻生效。
    """
    import api                          # 每次重新读，保证 monkeypatch 生效
    base = Path(api.DEFAULT_PLUGINS_DATA_PATH)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[2] / base
    base.mkdir(parents=True, exist_ok=True)     # 需要时再建，import 期不建
    return base


# 文件级读-改-写锁：同一进程里多个事件 worker 并发签到时串行化，
# 避免"读-改-写"交错导致落盘丢数据（asyncio.Lock 自 3.10 起不再绑定事件循环，可模块级创建）。
_DATA_LOCK = asyncio.Lock()


def _load_json(path: Path, default: dict) -> dict:
    """读 JSON：文件缺失 / 空 / 损坏 / 顶层不是对象 → 一律返回 default（不抛）"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning(f"读取数据文件 {path} 失败（将使用空数据）: {exc}")
        return default
    return data if isinstance(data, dict) else default


def _save_json(path: Path, data: dict) -> None:
    """先写同目录临时文件再 os.replace 原子替换，避免写到一半崩溃留下半个 JSON"""
    path = Path(path)
    # exist_ok：只在真的要落盘时创建数据目录，import 期不碰工作区
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _group_table(data: dict, group_id) -> dict:
    """取群字典；缺失或类型不对时给一个可写的新 dict（不会原地污染旧值）"""
    table = data.get(group_id)
    if not isinstance(table, dict):
        table = {}
        data[group_id] = table
    return table


def getDate():
    now = datetime.now()
    return f"{now.year}-{now.month}-{now.day}"


@on_command("个人信息")
async def DisplayUserPanel(
    bot: Bot,
    event: GroupMessageEvent
):
    user_id = event.get_user_id
    group_id = event.get_group_id

    data = _load_json(_data_dir() / "wealth.json", {})

    # 群不存在 / 人不存在都不能直接索引（真实财富存档里只有部分群和人）
    user_data = data.get(group_id, {}).get(user_id) if group_id else None
    if not isinstance(user_data, dict):
        await bot.send(
            group_id,
            f"[CQ:at,qq={user_id}] 查无数据！"
        )
        return

    await bot.send(
        group_id,
        f"[CQ:at,qq={user_id}]\n"
        f"[CQ:image,file=https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100]\n"
        f"金钱: {user_data.get('money', 0)}"
    )


@on_command("签到")
async def qian_dao(
    bot: Bot,
    event: GroupMessageEvent
):
    user_id = event.get_user_id
    group_id = event.get_group_id

    today = getDate()
    money = randint(200, 400)

    # 读-改-写整体在锁内完成：签到存档与财富存档一起更新，避免交错丢数据
    async with _DATA_LOCK:
        data_dir = _data_dir()
        wealth_file = data_dir / "wealth.json"
        qian_dao_file = data_dir / "qian_dao_.json"

        qian_dao_ = _load_json(qian_dao_file, {})

        signed_users = qian_dao_.get(group_id, {})
        dates = signed_users.get(user_id) if isinstance(signed_users, dict) else None
        if isinstance(dates, list) and dates and dates[-1] == today:
            await bot.send(group_id, f"[CQ:at,qq={user_id}]您今天已签到！")
            return          # ← 已签到必须结束：否则下面继续加钱/落盘，同日可无限刷钱

        # 财富存档：读写统一用 wealth.json（旧代码读 all.json 写 wealth.json，
        # 一次签到就会把整份财富存档覆盖成"当前群+当前人"）
        wealth_data = _load_json(wealth_file, {})
        group_table = _group_table(wealth_data, group_id)
        user_table = group_table.get(user_id)
        if not isinstance(user_table, dict):
            group_table[user_id] = {
                "user_name": event.get_user_name,
                "money": money
            }
        else:
            try:
                user_table["money"] = user_table.get("money", 0) + money
            except TypeError:       # 老数据里 money 可能是脏类型
                user_table["money"] = money

        if not isinstance(qian_dao_.get(group_id), dict):
            qian_dao_[group_id] = {}
        if not isinstance(qian_dao_[group_id].get(user_id), list):
            qian_dao_[group_id][user_id] = [today]
        else:
            qian_dao_[group_id][user_id].append(today)

        _save_json(wealth_file, wealth_data)
        _save_json(qian_dao_file, qian_dao_)

    await bot.send(
        group_id,
        f"[CQ:at,qq={user_id}]\n"
        f"[CQ:image,file=https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100]\n"
        f"今日签到获取了 {money} 金钱"
    )
