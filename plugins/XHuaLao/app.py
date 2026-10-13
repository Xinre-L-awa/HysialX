import os
import json
import time
from pathlib import Path
from threading import Lock, Thread
from flask import Flask, request, render_template

from log import logger
from api import on_startup, DEFAULT_PLUGINS_DATA_PATH

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
port = 1145

# 访问统计的 read-modify-write 锁：Flask 默认多线程处理请求，
# 两个请求同时进门会互相覆盖计数
_VISITS_LOCK = Lock()


def _data_dir() -> Path:
    """数据目录：**调用时**取框架常量（测试/部署可重定向），相对路径按仓库根解析，不依赖 cwd"""
    import api                                     # 每次重新读，monkeypatch 才能生效
    base = Path(api.DEFAULT_PLUGINS_DATA_PATH)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[2] / base
    base.mkdir(parents=True, exist_ok=True)        # 用到时才建，不在 import 期建
    return base


def _read_json_file(path) -> dict:
    """读 JSON：文件缺失 / 内容损坏 / 不是 JSON 对象 一律回退空字典（原来缺失会直接 500）"""
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
    """取值兜底：缺 count 或类型不对都当 0"""
    if not isinstance(entry, dict):
        return 0
    count = entry.get("count", 0)
    return count if isinstance(count, int) else 0


def AddVisit() -> dict:
    visitor_ip = request.remote_addr

    logger.info(f"{visitor_ip} visited XHuaLao Web Service")

    visits_file = _data_dir() / "visits.json"
    visitor_address_file = _data_dir() / "visitor_address.json"

    with _VISITS_LOCK:
        data = _read_json_file(visits_file)

        count = data.get(visitor_ip, 0)
        if not isinstance(count, int):
            count = 0
        data[visitor_ip] = count + 1
        # 计数确实变了才写盘（新访客必然写；老访客也是 +1，只是不做多余的空写）
        _write_json_file(visits_file, data)

        # 访问日期表只在"真的新增了一次访问日期"时才写盘：
        # 旧代码不管有没有新日期都会把这个文件整个重写一遍
        data_ = _read_json_file(visitor_address_file)

        now_time = time.strftime('%Y.%m.%d', time.localtime(time.time()))
        dates = data_.get(visitor_ip)
        if not isinstance(dates, list):
            dates = []
            data_[visitor_ip] = dates
        if now_time not in dates:
            dates.append(now_time)
            _write_json_file(visitor_address_file, data_)

    return data


@app.route('/')
def index():
    data = _read_json_file(_data_dir() / "GroupStatistics.json")

    groups = []
    for k, _ in data.items():
        groups.append(k)

    visits = AddVisit() or {}
    return render_template(
        "index.html",
        groups=groups,
        visits_num=sum(v for v in visits.values() if isinstance(v, int))
    )


@app.route("/<group_id>")
def display(group_id: str):
    data = _read_json_file(_data_dir() / "GroupStatistics.json")

    if group_id not in data: return "<h1>未查询到相关数据！</h1>"

    group_data = data.get(group_id)
    if not isinstance(group_data, dict): return "<h1>未查询到相关数据！</h1>"

    # 缺键兜底：GroupRecordingTime.json 少一条记录时不再 KeyError → 500
    record_time = _read_json_file(_data_dir() / "GroupRecordingTime.json").get(group_id, "未知")
    data = dict(sorted(group_data.items(), key=lambda x: _count_of(x[1]), reverse=True))

    i = 1
    data_ = []
    for _, v in data.items():
        name = v.get("user_name", "") if isinstance(v, dict) else ""
        if " " in name:
            # 保持原行为：模板不改（真替换得配合 |safe，否则 Jinja 会渲染成 &amp;nbsp;）
            name.replace(" ", "&nbsp;")
        data_.append(
            {
                "rank": i,
                "name": name,
                "count": _count_of(v)
            }
        )
        i += 1

    AddVisit()

    return render_template(
        "detail.html",
        data=data_,
        title=group_id,
        record_time=record_time,
        count=sum(_count_of(v) for _, v in data.items())
    )


@on_startup
def startHuaWeb():
    host = "127.0.0.1"                  # app.run 默认也是它，写出来是为了日志和监听地址一致

    def _():
        try:
            app.run(host=host, port=port)
        except Exception as exc:
            # 端口占用 / 权限不足等发生在子线程里的异常，必须自己记下来，否则没人看得见
            logger.exception(f"XHuaLao Web Service 启动失败: {exc}")

    try:
        p = Thread(target=_, name="XHuaLao-WebService", daemon=True)
        p.start()
        logger.opt(colors=True).success(f'Succeeded to start Web Sevice on <c>http://{host}:{port}</c>!')
    except Exception as e:
        logger.warning(e)
        logger.warning('<r>Failed to start Web Sevice!</r>')
