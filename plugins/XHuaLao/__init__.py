from .app import *
from .main import *


func_dict = {
    "话痨排行榜": [
        PhimosisRanking, 
        "on_command"
    ],
    "话痨排行榜 -a": [
        DisplayCompleteRanking, 
        "on_command"
    ],
    "GMS": [
        GroupMessageStatistics,
        "AutoRun"
    ],
    "startHuaWeb": [
        startHuaWeb,
        "on_startup"
    ]
}
