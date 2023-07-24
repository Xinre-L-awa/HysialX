import json, os
from gevent import pywsgi
from threading import Thread
from flask import Flask, request, render_template

from api import logger

app = Flask(__name__)

def AddVisit():
    with open("./visits.json") as f:
        data = json.load(f)
        print(data)
        visitor_ip = request.remote_addr
        if visitor_ip not in data:
            data[visitor_ip] = 1
        else:
            data[visitor_ip] += 1
    with open("./visits.json", 'w') as f:
        json.dump(data, f)
    
    return data


@app.route('/')
def index():
    with open("./GroupStatistics.json") as f:
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
    print(os.getcwd())
    with open("./GroupStatistics.json") as f:
        data = json.load(f)
    
    if group_id not in data: return "<h1>未查询到相关数据！</h1>"
    
    with open("./DataForXPlugin/GroupRecordingTime.json") as f:
        record_time = json.load(f)[group_id]
    data = dict(sorted(data[group_id].items(), key=lambda x: x[1]['count'], reverse=True))
    
    i = 1
    data_ = []
    for _, v in data.items():
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

def startHuaWeb():
    def _():
        pywsgi.WSGIServer(('', 5000), app, log=None).serve_forever()
    try:
        p = Thread(target=_)
        p.setDaemon(True)
        p.start()
        logger.success('Succeeded to start Web Sevice!')
    except Exception as e:
        logger.warning(e)
        logger.warning('<r>Failed to start Web Sevice!</r>')
