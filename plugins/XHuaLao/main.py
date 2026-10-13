import asyncio
import json
import os
import shutil
import time
import base64
from pathlib import Path
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
from log import logger


# 按文件粒度的串行锁：RunInLoop 会被 event_workers 个 worker 并发调度，
# 统计文件的 read-modify-write 必须串行，否则并发写会交错丢计数。
_STATISTICS_LOCK = asyncio.Lock()

# 群里还没有任何统计数据时的统一回复
_EMPTY_GROUP_HINT = "本群还没有统计数据，先去聊两句再来查吧~"


def _data_dir() -> Path:
    """数据目录：**调用时**取框架常量（测试/部署可重定向），相对路径按仓库根解析，不依赖 cwd"""
    import api                                     # 每次重新读，monkeypatch 才能生效
    base = Path(api.DEFAULT_PLUGINS_DATA_PATH)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[2] / base
    base.mkdir(parents=True, exist_ok=True)        # 用到时才建，不在 import 期建
    return base


def _read_json_file(path) -> dict:
    """读 JSON：文件缺失 / 内容损坏 / 不是 JSON 对象 时回退空字典，不向调用方抛异常"""
    try:
        with open(path, encoding="utf-8", mode="r") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:    # FileNotFoundError / UnicodeDecodeError / JSONDecodeError
        logger.warning(f"读取 {path} 失败，按空数据继续: {exc}")
        return {}
    if not isinstance(data, dict):
        logger.warning(f"{path} 的内容不是 JSON 对象，按空数据继续")
        return {}
    return data


def _write_json_file(path, data: dict) -> None:
    """原子写盘：先写同目录临时文件再 os.replace 覆盖，异常时不会留下半截 JSON"""
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, encoding="utf-8", mode="w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def _count_of(entry) -> int:
    """排序/求和用的取值兜底：缺 count 或类型不对都当 0，别让坏数据炸掉整条命令"""
    if not isinstance(entry, dict):
        return 0
    count = entry.get("count", 0)
    return count if isinstance(count, int) else 0


@RunInLoop
async def GroupMessageStatistics(
    bot: Bot,
    event: GroupMessageEvent
):
    group_id = event.get_group_id
    sender_id = event.get_user_id
    sender_name = event.get_user_group_name if event.get_user_group_name != '' else event.get_user_name

    statistics_file = _data_dir() / "GroupStatistics.json"
    recording_time_file = _data_dir() / "GroupRecordingTime.json"

    # 全量 read-modify-write 必须串行：并发交错会丢计数
    async with _STATISTICS_LOCK:
        data = _read_json_file(statistics_file)

        is_new_group = not isinstance(data.get(group_id), dict)
        if is_new_group:
            data[group_id] = {}
        group_data = data[group_id]

        # setdefault 一次到位：新群/新成员先补 count=0，最后统一 +1。
        # 原来的 if/else 会让"新群首条消息"既走 if 又走 else，被记成 2。
        user_data = group_data.setdefault(
            sender_id,
            {
                "user_name": sender_name,
                "count": 0
            }
        )
        if not isinstance(user_data, dict):
            user_data = {"user_name": sender_name, "count": 0}
            group_data[sender_id] = user_data

        current_count = user_data.get("count", 0)
        if not isinstance(current_count, int):
            current_count = 0         # 坏数据兜底，别在累加时抛 TypeError

        user_data["user_name"] = sender_name
        user_data["count"] = current_count + 1

        _write_json_file(statistics_file, data)

        if is_new_group:
            # 新群第一次出现时记下起始日期；文件缺失/损坏回退空表，缺键也不会 KeyError
            record_time = _read_json_file(recording_time_file)
            record_time[group_id] = time.strftime('%Y.%m.%d', time.localtime(time.time()))
            _write_json_file(recording_time_file, record_time)


def _take_ranking_screenshot(group_id: str, driver_path: str) -> bytes:
    """阻塞部分：起 Chrome → 打开页面 → 截图 → 退出（由 asyncio.to_thread 在线程里跑）"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--single-process')
    # 不再固定 --remote-debugging-port：并发第二次会撞端口

    driver = webdriver.Chrome(
        service=ChromeService(executable_path=driver_path),
        options=options
    )
    try:
        driver.get(f"http://127.0.0.1:1145/{group_id}")
        # driver.save_screenshot("sc.png")
        return driver.get_screenshot_as_png()
    finally:
        try:
            driver.quit()
        except Exception as exc:
            logger.warning(f"话痨排行榜: 关闭 Chrome 失败: {exc}")


@on_command("话痨排行榜")
async def PhimosisRankingInPhoto(
    bot: Bot,
    event: GroupMessageEvent
):
    # chromedriver 位置：环境变量优先，其次 PATH；都没有就明确报错并返回，不抛未捕获异常
    driver_path = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    if not driver_path:
        logger.error(
            "话痨排行榜: 找不到 chromedriver，"
            "请把它放进 PATH，或用环境变量 CHROMEDRIVER_PATH 指定完整路径"
        )
        return

    try:
        # 起浏览器/加载页面/截图全是阻塞调用，丢到线程里跑，别堵住事件循环
        screenshot = await asyncio.to_thread(
            _take_ranking_screenshot,
            event.get_group_id,
            driver_path
        )
        # 将图片转换为base64字符串
        img_str = base64.b64encode(screenshot).decode('utf-8')
    except Exception as exc:
        logger.exception(f"话痨排行榜: 生成排行榜截图失败: {exc}")
        return

    await bot.send(event.get_group_id, f"[CQ:image,file=base64://{img_str}]")


@on_command("话痨排行榜 -t")
async def PhimosisRanking(
    bot: Bot,
    event: GroupMessageEvent
):
    t1 = time.time()
    data = _read_json_file(_data_dir() / "GroupStatistics.json")
    t2 = time.time()

    group_data = data.get(event.get_group_id)
    if not isinstance(group_data, dict):
        group_data = {}
    if not group_data:
        await bot.send(event.get_group_id, _EMPTY_GROUP_HINT)
        return

    data_ = dict(sorted(group_data.items(), key=lambda x: _count_of(x[1]), reverse=True))
    i = 1
    s = [f"看看你们多能聊！查个聊天记录都用了{t2 - t1}秒！"]
    for _, v in data_.items():
        name = v.get("user_name", "") if isinstance(v, dict) else ""
        s.append(f"{i}. {name}共发送消息 {_count_of(v)} 条")
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
    data = _read_json_file(_data_dir() / "GroupStatistics.json")

    group_data = data.get(event.get_group_id)
    if not isinstance(group_data, dict):
        group_data = {}
    if not group_data:
        await bot.send(event.get_group_id, _EMPTY_GROUP_HINT)
        return

    data_ = dict(sorted(group_data.items(), key=lambda x: _count_of(x[1]), reverse=True))

    # 三目优先级坑：原来写成 `v['user_name'] == a if b != '' else c`，
    # 群名片为空时条件退化成 `user_name == 昵称`(恒真)，res 每轮被覆盖只剩最后一名。
    # 先把 name 算出来，再做相等比较。
    name = event.get_user_group_name if event.get_user_group_name != '' else event.get_user_name

    i = 1
    res = ""
    for _, v in data_.items():
        if isinstance(v, dict) and v.get("user_name") == name:
            res = f"{i}. {v.get('user_name', '')}共发送消息 {_count_of(v)} 条"
        i += 1

    if res == "":                    # 本群统计里没有这个人，别发空消息
        res = "还没有找到你在本群的发言记录哦~"

    await bot.send(event.get_group_id, res)
