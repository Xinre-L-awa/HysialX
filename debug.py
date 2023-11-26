import signal
from time import time
from typing import List, Dict
from termcolor import colored

from api import (
    At,
    ImageSegment,
    AnalyseCQCode,
    get_plugin_pool
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


def new_send(_, _uid, msg: str) -> None:
    try:
        logger.info(msg)
    except Exception as e:
        logger.error(e)

Bot.send = new_send

COMMANDS = {
    "set": lambda *args, **kwargs: set_(*args),
    "send": lambda msg, *_, **__: send(msg, *_, **__),
    "exit": lambda *_, **__: exit(),
    "help": lambda *args, **kwargs: help(),
    "build": lambda varible, content, *_, **__: buildMessage(varible, content),
    "reload": lambda *args, **kwargs: reload_plugins(),
    "plugins": lambda *args, **kwargs: {plugin.PluginName: plugin.__class__ for plugin in get_plugin_pool()},
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
    user_id: int=None,
    msg_type: str="group",
    to_what_id: int=123456789,
    sender: Sender=Sender(100, "Unknown", 169699201, "Rainch_"),
    time_stamp: int=time()
) -> str:
    template = '{"post_type":"message","message_type":"{}","time":{},"self_id":{},"sub_type":"normal","anonymous":null,"message_id":-1763953745,"font":0,"{}_id":{},"message":"{}","message_seq":1346,"raw_message":"{}","sender":{"age":0,"area":"","card":"","level":"","nickname":"{}","role":"owner","sex":"unknown","title":"","user_id":{}},"user_id":{}}'
    
    set_(
        varible, 
        template.format(
            msg_type,
            time_stamp,
            sender.user_id,
            msg_type,
            to_what_id,
            content,
            content,
            sender.nickname,
            user_id,
            user_id
        )
    )

    return "Success"

def reload_plugins():
    get_plugin_pool().dispose_all()
    load_plugins()

def send(to_be_sent_msg: str, *args, **kwargs):
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

def AnalyseCommand(cmd: str):
    try:
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

        return COMMANDS[main_cmd](*cmd[1:], **paras)
    except Exception as e:
        return e


def signal_handler(signal: int, frame):
    signals = {
        2: "\nCtrl-C cancelled the process"
    }
    print(signals[signal])
    # print(f"Signal {signal} detected")
    exit(0)


def loop():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print(colored("HysialX Debug Console", 'blue', 'on_black', ['bold', 'blink']))
    while True:
        if x := AnalyseCommand(input(colored(">>> ", "cyan"))): print(x)


try:
    logger.info(f'{colored("HysialX Debug Console", "blue", "on_black", ["bold", "blink"])} is starting...')
    load_plugins()
    loop()
except Exception as e:
    logger.error(e)
    logger.info("HysialX Debug Console is closing...")
