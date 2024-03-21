import signal
from time import time
from typing import List
# from colorama import Fore
from termcolor import colored
from api import (
    run_func,
    get_func_pool,
    get_plugin_pool,
    get_waiting_task_pool,
    getExpectedFuncs
)
from main import (
    Bot,
    logger,
    handle,
    load_plugins
)

separate_paras = lambda x: {
    i[0][1:]: i[1]
    for i in [
        tuple([v, None])
        if '=' not in v
        else tuple(v.split('='))
        for v in filter(lambda ele: ele.startswith('-'), x)
    ]
}

class Sender:
    def __init__(self,
        age: int=None, 
        sex: str=None, 
        user_id: int=None,
        nick_name: str=None
    ) -> None:
        self.age = age
        self.sex = sex
        self.user_id = user_id
        self.nickname = nick_name


class BaseEvent:
    time: int
    self_id: int
    post_type: str
    message_type: str
    sub_type: str
    message_id: int
    sender: Sender
    user_id: int
    message: str


class GroupMessage:
    anonymous = None


class Variables:
    def set_variable(self, variable_name: str, value, type_=None):
        self.__dict__[variable_name] = [value, type_ if type_ else type(value)]
    
    def delete_variable(self, variable_name):
        del self.__dict__[variable_name]
    
    def isExist(self, variable_name):
        return variable_name in self.__dict__
    
    def getValue(self, variable_name):
        return self.__dict__[variable_name][0] if self.isExist(variable_name) else None

variables = Variables()


@logger.catch
def new_send(_, _uid, msg: str) -> None:
    logger.info(f"发送消息 {msg} 到群 {_uid} 成功")

Bot.send = new_send

COMMANDS = {
    "set": lambda *args, **kwargs: set_(*args),
    "send": lambda msg, *_, **__: send(msg, *_, **__),
    "exit": lambda *_, **__: exit(),
    "help": lambda *args, **kwargs: help(),
    "build": lambda varible, content, *_, **__: buildMessage(varible, content),
    "reload": lambda *args, **kwargs: reload_plugins(),
    "plugins": lambda *args, **kwargs: {plugin.PluginName: plugin.__class__ for plugin in get_plugin_pool()},
    "get_waiting_pool": lambda *args, **kwargs: "\n".join([str(task) for task in get_waiting_task_pool()]),
    "test_send": lambda *_, **__: Bot.send(_, _,
        '{"post_type":"message",'
        '"message_type":"group","time":1699108463,"self_id":3592797817,'
        '"sub_type":"normal","anonymous":null,"message_id":-1763953745,'
        '"font":0,"group_id":859874709,"message":"echo test",'
        '"message_seq":1346,"raw_message":"echo test","sender":'
        '{"age":0,"area":"","card":"","level":"","nickname":"雨弈",'
        '"role":"owner","sex":"unknown","title":"","user_id":169699201},'
        '"user_id":169699201}'
    )
}
PARAMETERS = [
    "time_stamp",
    "self_id"
]

def set_(*args, **kwargs):
    if not len(args): return colored("ParaError: No args", "red")
    if len(args) == 1: return colored("ParaError: Missing one parameter", "red")
    if len(args) > 2: return colored("ParaError: Too many parameters", "red")
    variables.set_variable(args[0], args[1:])

def help():
    print("\n".join(COMMANDS))

def buildMessage(
    varible: str,
    content: str,
    self_id: int=123456789,
    msg_type: str="group",
    to_what_id: int=123456789,
    sender: Sender=Sender(100, "Unknown", 169699201, "Rainch_"),
    time_stamp: int=time()
) -> str:
    res = {
        "post_type": "message",
        "message_type": msg_type,
        "time": time_stamp,
        "self_id": self_id,
        "sub_type":"normal",
        "anonymous": None,
        "message_id":-1763953745,
        "font":0,
        "message":content,
        "message_seq":1346,"raw_message": content,
        "sender": {
            "age": sender.age,
            "area": "",
            "card": "",
            "level": "",
            "nickname": sender.nickname,
            "role": "owner",
            "sex": "unknown",
            "title": "",
            "user_id": sender.user_id
        },
        "user_id": sender.user_id
    }
    res[f"{msg_type}_id"] = to_what_id
    set_(
        varible, 
        str(res).replace("'", '"').replace("None", "null")
    )

    return "Success"

def reload_plugins():
    get_plugin_pool().dispose_all()
    load_plugins()

def send(to_be_sent_msg: str, count: int=1, *args, **kwargs):
    for _ in range(int(count)):
        handle(..., to_be_sent_msg + ''.join(args))

def isReplacable(cmd: str, index: int) -> bool:
    if cmd == "set" and index > 1: return True
    elif cmd == "send": return True
    return False

def split(target: str, delimiter=' ') -> List[str]:
    result = []
    stack = []
    current_item = ""
    for char in target:
        if char == '{':
            stack.append(char)
        elif char == '}':
            stack.pop()
        if char == delimiter and len(stack) == 0:
            result.append(current_item)
            current_item = ""
        else:
            current_item += char
    if current_item:
        result.append(current_item)
    return result

@logger.catch
def AnalyseCommand(cmd: str):
    if "==" in cmd:
        v1, v2 = cmd.replace(' ', '').strip().split("==")
        v1 = variables.getValue(v1) if variables.isExist(v1) else v1
        v2 = variables.getValue(v2) if variables.isExist(v2) else v2
        return str(v1 == v2)
    cmd = split(cmd)
    if not cmd: return
    main_cmd = cmd[0]
    paras = separate_paras(cmd)

    if main_cmd not in COMMANDS:
        if variables.isExist(main_cmd):
            return variables.getValue(main_cmd)[0]
        return f"\033[37mInvalid cmd\033[0m \033[31m{main_cmd}\033[0m"
    for para in paras:
        if para not in PARAMETERS:
            return colored(f"Invalid parameter {para}", "red")

    cmd = [
        variables.getValue(cmd_)[0] 
        if variables.isExist(cmd_) and isReplacable(main_cmd, cmd.index(cmd_)) 
        else cmd_ for cmd_ in cmd
    ]

    return run_func(COMMANDS[main_cmd], *cmd[1:], **paras, isDebug=True)


def signal_handler(signal: int, frame):
    signals = {
        2: "\nCtrl-C cancelled the process"
    }
    print(signals[signal])
    logger.info("HysialX Debug Console is closing...")
    exit(0)


def loop():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print(colored("HysialX Debug Console", 'blue', 'on_black', ['bold', 'blink']))
    while True:
        if x := AnalyseCommand(input(colored(">>> ", "cyan"))): print(x)


@logger.catch
def start():
    logger.info(f'{colored("HysialX Debug Console", "blue", "on_black", ["bold", "blink"])} is starting...')

    load_plugins()
    onstartupFuncs = getExpectedFuncs(get_func_pool(), "on_startup")
    [run_func(func, isDebug=True) for func in onstartupFuncs]


    # func: WaitingFuncMeta
    # for func in filter(
    #     lambda x: isinstance(x, WaitingFuncMeta),
    #     get_func_pool()
    # ):
    #     print(func.parrent_func)
    #     print(func.child_func)
    #     if func.isChildFunc:
    #         func()

    loop()

    logger.info("HysialX Debug Console is closing...")


if __name__ == "__main__":
    start()
