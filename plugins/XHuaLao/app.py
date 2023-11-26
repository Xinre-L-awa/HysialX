import os
import json
import time
from gevent import pywsgi
from threading import Thread
from flask import Flask, request, render_template

from log import logger
from api import on_startup, DEFAULT_PLUGINS_DATA_PATH


app = Flask(__name__)
address = "127.0.0.1"
port = 1145


def AddVisit():
    visitor_ip = request.remote_addr
    
    logger.info(f"{visitor_ip} visited XHuaLao Web Service")
    
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/visits.json") as f:
        data = json.load(f)

        if visitor_ip not in data:
            data.update({visitor_ip: 1})
        else:
            data[visitor_ip] += 1
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/visits.json", 'w') as f:
        json.dump(data, f)
    
    if not os.path.exists(f"{DEFAULT_PLUGINS_DATA_PATH}/visitor_address.json"):
        with open(f"{DEFAULT_PLUGINS_DATA_PATH}/visitor_address.json", 'w') as f:
            f.write("{}")
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/visitor_address.json") as f:
        data_ = json.load(f)
        
        now_time = time.strftime('%Y.%m.%d',time.localtime(time.time()))
        if visitor_ip not in data_:
            data_[visitor_ip] = [now_time]
        elif now_time not in data_[visitor_ip]:
            data_[visitor_ip].append(now_time)
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/visitor_address.json", 'w') as f:
        json.dump(data_, f)
    
    return data


@app.route('/')
def index():
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json") as f:
        data = json.load(f)

    groups = []
    for k, _ in data.items():
        groups.append(k)
    
    return render_template(
        "index.html",
        groups=groups,
        visits_num=sum([v for _, v in AddVisit().items()])
    )


@app.route("/<group_id>")
def display(group_id: str):
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupStatistics.json") as f:
        data = json.load(f)
    
    if group_id not in data: return "<h1>未查询到相关数据！</h1>"
    
    with open(f"{DEFAULT_PLUGINS_DATA_PATH}/GroupRecordingTime.json") as f:
        record_time = json.load(f)[group_id]
    data = dict(sorted(data[group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    
    i = 1
    data_ = []
    for _, v in data.items():
        if " " in v["user_name"]:
            v["user_name"].replace(" ", "&nbsp;")
        data_.append(
            {
                "rank": i,
                "name": v["user_name"],
                "count": v["count"]
            }
        )
        i += 1
    
    AddVisit()

    return render_template(
        "detail.html",
        data=data_,
        title=group_id,
        record_time=record_time,
        count=sum([v["count"] for _, v in data.items()])
    )

@on_startup
def startHuaWeb():
    def _():
        pywsgi.WSGIServer(('', 1145), app, log=None).serve_forever()
    try:
        p = Thread(target=_)
        p.setDaemon(True)
        p.start()
        logger.opt(colors=True).success(f'Succeeded to start Web Sevice on <c>http://{address}:{port}</c>!')
    except Exception as e:
        logger.warning(e)
        logger.warning('<r>Failed to start Web Sevice!</r>')
