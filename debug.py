"""
HysialX 调试控制台（M8 版）。

**不联网**：用 DebugConnection（继承 snowluma 的 LocalEchoConnection）假装是协议端。
插件的 ``await bot.send(...)`` / ``await bot.call_api(...)`` 走的是**完整的 M7 逻辑**
（格式转换、失败语义、日志、``bot.finish`` 的 FinishException），只是最终落到本地日志与
``conn.calls``，不会真的发消息。

**不再 monkeypatch `Bot.send`**：那会绕过整条发送链；而且旧实现是同步函数，
会让每个插件的 ``await bot.send(...)`` 直接抛 TypeError（2 参数 → await None；
3 参数 → 参数个数不匹配）。

用法::

    python debug.py                 # 执行 on_startup（XHuaLao 会占 1145 端口）
    python debug.py --no-startup    # 跳过 on_startup

命令示例::

    >>> build $msg echo 你好 -type=group -to=859874709 -format=array
    >>> send $msg
    >>> notice group_increase
    >>> fail on
    >>> conn
"""

import asyncio
import importlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from termcolor import colored

import main as main_module
from api import (
    get_connection,
    get_func_pool,
    get_notice_func_pool,
    get_plugin_pool,
    get_request_func_pool,
    get_waiting_task_pool,
    getExpectedFuncs,
    run_func,
    set_connection,
)
from log import logger
from snowluma import LocalEchoConnection
from snowluma.exception import ActionFailed
from snowluma.segment import parse_cq_to_segments, segments_to_dicts

DEBUG_SELF_ID = 3592797817
DEBUG_GROUP_ID = 859874709
DEBUG_USER_ID = 169699201
DEBUG_USER_NAME = "Rainch"


# ------------------------------------------------------------ 调试用假协议端
class DebugConnection(LocalEchoConnection):
    """在 LocalEchoConnection 之上补两点：

    1. 记录 ``send_msg``——父类只打印日志、不写 ``calls``，测试/``conn`` 命令没法断言；
    2. 失败注入 ``fail=True``：让 ``send_message`` 抛 ``ActionFailed``，
       用来验证 M7 §2.1 的「``send`` 吞异常、``call_api`` 抛异常」。
    """

    def __init__(self, *, fail: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.fail = fail

    async def send_message(self, message, *, message_type=None, user_id=None,
                           group_id=None, auto_escape=False):
        self.calls.append(("send_msg", {
            "message_type": message_type, "group_id": group_id, "user_id": user_id,
            "auto_escape": auto_escape, "message": message,
        }))
        if self.fail:
            raise ActionFailed("send_msg", status="failed", retcode=100,
                               wording="调试注入的失败（fail on）")
        return await super().send_message(
            message, message_type=message_type, user_id=user_id,
            group_id=group_id, auto_escape=auto_escape,
        )


# ------------------------------------------------------------------ 事件构造
def build_payload(content: str, *, msg_type: str = "group", to_what_id: int = DEBUG_GROUP_ID,
                  message_format: str = "array", self_id: int = DEBUG_SELF_ID) -> dict:
    """构造一条 OneBot v11 消息事件（与 tests/mock_snowluma 的工厂保持同形）"""
    message = (segments_to_dicts(parse_cq_to_segments(content))
               if message_format == "array" else content)
    payload = {
        "post_type": "message", "message_type": msg_type, "sub_type": "normal",
        "time": int(time.time()), "self_id": self_id, "message_id": 12345,
        "message": message, "raw_message": content, "font": 0,
        "sender": {"user_id": DEBUG_USER_ID, "nickname": DEBUG_USER_NAME,
                   "card": "群名片", "role": "owner"},
    }
    payload[f"{msg_type}_id"] = to_what_id
    return payload


def build_message_sent(content: str, *, msg_type: str = "group",
                       to_what_id: int = DEBUG_GROUP_ID) -> dict:
    """reportSelfMessage 打开时协议端会上报机器人自己发的消息（post_type=message_sent）"""
    payload = build_payload(content, msg_type=msg_type, to_what_id=to_what_id)
    payload["post_type"] = "message_sent"
    return payload


def build_notice(notice_type: str = "group_increase", *, sub_type: str = "approve",
                 group_id: int = DEBUG_GROUP_ID, user_id: int = 88888,
                 operator_id: int = DEBUG_SELF_ID) -> dict:
    return {
        "post_type": "notice", "notice_type": notice_type, "sub_type": sub_type,
        "time": int(time.time()), "self_id": DEBUG_SELF_ID,
        "group_id": group_id, "user_id": user_id, "operator_id": operator_id,
    }


def build_request(request_type: str = "group", *, sub_type: str = "add",
                  group_id: int = DEBUG_GROUP_ID, user_id: int = 77777,
                  comment: str = "求进群", flag: str = "flag-1") -> dict:
    payload = {
        "post_type": "request", "request_type": request_type, "sub_type": sub_type,
        "time": int(time.time()), "self_id": DEBUG_SELF_ID,
        "user_id": user_id, "comment": comment, "flag": flag,
    }
    if request_type == "group":
        payload["group_id"] = group_id
    return payload


# ------------------------------------------------------------------ 投递
def feed(payload: dict) -> None:
    """把事件喂给真实分发链（``main.handle_event``）。

    每条命令用一次 ``asyncio.run`` 是安全的：假连接不持有长连接、不注册后台任务，
    一次命令一个事件循环不会冲突。**副作用**：若某个插件在处理器里
    ``asyncio.create_task`` 起了后台任务，它会随命令结束被丢弃——
    需要那种用法时改成常驻循环 + ``loop.run_until_complete``。
    """
    asyncio.run(main_module.handle_event(payload))


def feed_json(raw: str) -> str:
    payload = json.loads(raw)
    feed(payload)
    kind = (payload.get("message_type") or payload.get("notice_type")
            or payload.get("request_type") or "")
    return f"已投递 {payload.get('post_type')}/{kind} 事件"


# ------------------------------------------------------------------ 变量与参数
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


def _key(variable_name: str) -> str:
    """变量名统一去掉可选的 ``$`` 前缀"""
    return variable_name[1:] if variable_name.startswith("$") else variable_name


def _stored(target: str):
    """取出变量里存的 JSON 字符串；不是变量就原样返回"""
    key = _key(target)
    if not variables.isExist(key):
        return target
    value = variables.getValue(key)
    return value[0] if isinstance(value, list) else value


separate_paras = lambda x: {
    i[0][1:]: i[1]
    for i in [
        tuple([v, None]) if '=' not in v else tuple(v.split('=', 1))
        for v in filter(lambda ele: ele.startswith('-'), x)
    ]
}

PARAMETERS = [
    "time_stamp", "self_id", "type", "to", "format", "body", "sub_type", "user",
]


def _para(paras: Dict[str, Any], key: str, default=None):
    value = paras.get(key, default)
    if value is None:
        return default
    return str(value).strip().strip('"').strip("'")


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ 命令实现
def cmd_help(*_args, **_kwargs):
    print(colored("HysialX Debug Console 命令", "cyan"))
    for name, desc in {
        "help": "显示本帮助",
        "build <$var> <内容> [-type=group|private] [-to=ID] [-format=array|string]": "构造消息事件并存入变量",
        "send <$var|JSON> [次数]": "把事件投递给真实分发链",
        "array <内容>": "用 array 格式构造并投递一条群消息",
        "notice [notice_type] [-sub_type=..] [-user=..]": "构造并投递通知事件",
        "request [friend|group]": "构造并投递请求事件",
        "sent <内容>": "构造并投递 message_sent（机器人自己发的消息）",
        "set <name> <value>": "设置变量（发送时可用 $name 引用）",
        "conn": "查看当前调试连接与已记录的动作",
        "fail on|off": "开关发送失败注入（验证 send 吞异常 / call_api 抛异常）",
        "pool": "查看等待任务池",
        "clear": "清空等待任务池",
        "plugins": "列出已加载插件",
        "reload": "重载插件模块并重建函数池",
        "exit": "退出",
    }.items():
        print(f"  {name:<64} {desc}")


def cmd_build(variable: str, content: str = "", *, msg_type: str = "group",
              to_what_id: int = DEBUG_GROUP_ID, message_format: str = "array",
              self_id: int = DEBUG_SELF_ID, **_):
    if not variable:
        return colored("ParaError: Missing variable name", "red")
    payload = build_payload(content, msg_type=msg_type, to_what_id=to_what_id,
                            message_format=message_format, self_id=self_id)
    variables.set_variable(_key(variable), [json.dumps(payload, ensure_ascii=False)])
    return "Success"


def cmd_send(target: str, count: int = 1, **_):
    if not target:
        return colored("ParaError: Missing target", "red")
    raw = _stored(target)
    if not str(raw).lstrip().startswith("{"):
        return colored(f"不是事件 JSON（先用 build 构造）：{str(raw)[:40]!r}", "red")
    times = max(1, _as_int(count, 1) or 1)
    for _ in range(times):
        feed_json(raw)
    return f"已投递 {times} 次"


def cmd_array(content: str = "", *, to_what_id: int = DEBUG_GROUP_ID,
              msg_type: str = "group", **_):
    feed(build_payload(content, msg_type=msg_type, to_what_id=to_what_id,
                       message_format="array"))
    return "已投递 1 条 array 事件"


def cmd_notice(notice_type: str = "group_increase", *, sub_type: str = "approve",
               group_id: int = DEBUG_GROUP_ID, user_id: int = 88888, **_):
    feed(build_notice(notice_type, sub_type=sub_type, group_id=group_id, user_id=user_id))
    return f"已投递 notice/{notice_type}"


def cmd_request(request_type: str = "group", *, group_id: int = DEBUG_GROUP_ID,
                user_id: int = 77777, comment: str = "求进群", **_):
    feed(build_request(request_type, group_id=group_id, user_id=user_id, comment=comment))
    return f"已投递 request/{request_type}"


def cmd_sent(content: str = "", **_):
    feed(build_message_sent(content))
    return "已投递 message_sent"


def cmd_set(*args, **_):
    if not len(args):
        return colored("ParaError: No args", "red")
    if len(args) == 1:
        return colored("ParaError: Missing one parameter", "red")
    variables.set_variable(_key(args[0]), list(args[1:]))
    return "Success"


def cmd_conn(*_args, **_):
    conn = get_connection()
    if conn is None:
        return colored("当前没有安装调试连接（先跑 start() 或 set_connection()）", "red")
    nickname = (getattr(conn, "login_info", None) or {}).get("nickname")
    return (
        f"调试连接: self_id={conn.self_id} nickname={nickname} "
        f"message_format={getattr(conn, 'message_format_detected', None)} "
        f"fail={getattr(conn, 'fail', False)} 已记录动作={len(getattr(conn, 'calls', []))}"
    )


def cmd_fail(switch: str = "", **_):
    conn = get_connection()
    if conn is None:
        return colored("没有调试连接，无法设置 fail", "red")
    if not hasattr(conn, "fail"):
        return colored("当前连接不支持 fail 注入（需要 DebugConnection）", "red")
    if switch.lower() in ("on", "1", "true"):
        conn.fail = True
    elif switch.lower() in ("off", "0", "false"):
        conn.fail = False
    else:
        return colored("用法: fail on|off", "red")
    return f"fail = {conn.fail}"


def cmd_pool(*_args, **_):
    tasks = list(get_waiting_task_pool())
    return "\n".join(str(task) for task in tasks) if tasks else "等待任务池为空"


def cmd_clear(*_args, **_):
    pool = get_waiting_task_pool()
    count = len(list(pool))
    if count:
        pool.pop_tasks(list(pool))
    return f"已清空 {count} 个等待任务"


def cmd_plugins(*_args, **_):
    return {plugin.PluginName: plugin.__class__ for plugin in get_plugin_pool()}


def _reload_plugin_modules() -> List[str]:
    """真正重新执行插件模块。

    只调 ``load_plugins()`` 没用：模块已在 ``sys.modules`` 里，importlib 直接返回缓存，
    装饰器不会重新跑。这里按 ``__file__`` 是否位于 ``plugins/`` 下挑出插件模块再 reload。

    ⚠️ reload 前必须把 cwd 切到 ``plugins/``：插件 import 时假设自己在 plugins 目录里
    （``plugins/t/main.py`` 开头就是 ``chdir("..")`` → 读根目录数据 → ``chdir("plugins")``），
    从项目根直接 reload 会让它逃到父目录，并把整个进程的 cwd 带跑偏。
    """
    plugins_dir = Path("plugins").resolve()
    if not plugins_dir.is_dir():
        logger.warning(f"未找到插件目录: {plugins_dir}")
        return []
    reloaded: List[str] = []
    cwd = os.getcwd()
    try:
        os.chdir(plugins_dir)
        for name, module in list(sys.modules.items()):
            file = getattr(module, "__file__", None)
            if not file:
                continue
            try:
                if plugins_dir in Path(file).resolve().parents:
                    importlib.reload(module)
                    reloaded.append(name)
            except Exception as exc:             # 单个插件 reload 失败不影响其它
                logger.warning(f"重载插件模块 {name} 失败: {exc}")
    finally:
        os.chdir(cwd)                            # 无论如何都要把 cwd 还回去
    return reloaded


def cmd_reload(*_args, **_):
    get_plugin_pool().dispose_all()
    # 重新执行插件会重新注册响应器，旧注册必须清掉，否则一个命令触发两次
    for pool in (get_func_pool(), get_notice_func_pool(), get_request_func_pool()):
        funcs = getattr(pool, "funcs", None)
        if funcs is not None:
            funcs.clear()

    reloaded = _reload_plugin_modules()
    main_module.load_plugins()
    main_module.refresh_funcs()
    cmd_clear()
    return f"已重载 {len(reloaded)} 个模块: {', '.join(sorted(reloaded)) or '无'}"


COMMANDS = {
    "help": cmd_help,
    "build": cmd_build,
    "send": cmd_send,
    "array": cmd_array,
    "notice": cmd_notice,
    "request": cmd_request,
    "sent": cmd_sent,
    "set": cmd_set,
    "conn": cmd_conn,
    "fail": cmd_fail,
    "pool": cmd_pool,
    "clear": cmd_clear,
    "plugins": cmd_plugins,
    "reload": cmd_reload,
    "exit": lambda *_, **__: sys.exit(0),
}


# ------------------------------------------------------------------ 命令解析
def split(target: str, delimiter=' ') -> List[str]:
    """按空格切分，但 ``{}`` 内的空格保留（用来塞 JSON）"""
    result, stack, current_item = [], [], ""
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


def isReplacable(cmd: str, index: int) -> bool:
    return cmd in ("send", "set")


def _build_kwargs(paras: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if msg_type := _para(paras, "type"):
        kwargs["msg_type"] = msg_type
    if to_what_id := _as_int(_para(paras, "to")):
        kwargs["to_what_id"] = to_what_id
    if message_format := _para(paras, "format"):
        kwargs["message_format"] = message_format
    if self_id := _as_int(_para(paras, "self_id")):
        kwargs["self_id"] = self_id
    return kwargs


@logger.catch
def AnalyseCommand(cmd: str):
    if "==" in cmd:
        v1, v2 = cmd.replace(' ', '').strip().split("==")
        v1 = variables.getValue(v1) if variables.isExist(v1) else v1
        v2 = variables.getValue(v2) if variables.isExist(v2) else v2
        return str(v1 == v2)

    tokens = split(cmd)
    if not tokens:
        return
    main_cmd = tokens[0]
    paras = separate_paras(tokens)

    if main_cmd not in COMMANDS:
        if variables.isExist(main_cmd):
            return _stored(main_cmd)
        return colored(f"Invalid cmd {main_cmd}", "red")
    for para in paras:
        if para not in PARAMETERS:
            return colored(f"Invalid parameter {para}", "red")

    if main_cmd == "build":                      # 内容 = 变量名之后、第一个 -param 之前
        positional = [t for t in tokens[2:] if not t.startswith("-")]
        content = _para(paras, "body") or " ".join(positional)
        return cmd_build(tokens[1] if len(tokens) > 1 else "", content, **_build_kwargs(paras))

    args = [
        _stored(t) if (variables.isExist(_key(t)) and isReplacable(main_cmd, i)) else t
        for i, t in enumerate(tokens[1:])
    ]
    extra = {k: v for k, v in paras.items() if v is not None}
    return run_func(COMMANDS[main_cmd], *args, **extra, isDebug=True)


# ------------------------------------------------------------------ 交互循环
def signal_handler(signum: int, frame):
    print({2: "\nCtrl-C cancelled the process"}.get(signum, f"\nSignal {signum}"))
    _cleanup()
    logger.info("HysialX Debug Console is closing...")
    sys.exit(0)


def _cleanup() -> None:
    try:
        cmd_clear()
    except Exception:
        pass
    set_connection(None)


def loop():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print(colored("HysialX Debug Console", 'blue', 'on_black', ['bold', 'blink']))
    print(colored("输入 help 查看命令；所有发送只打印日志，不联网。", "cyan"))
    while True:
        if x := AnalyseCommand(input(colored(">>> ", "cyan"))):
            print(x)


@logger.catch
def start(run_startup: bool = True):
    logger.info(f'{colored("HysialX Debug Console", "blue", "on_black", ["bold", "blink"])} is starting...')

    set_connection(DebugConnection(self_id=DEBUG_SELF_ID, nickname="HysialX-Debug"))
    main_module.load_plugins()
    main_module.refresh_funcs()

    if run_startup:
        for func in getExpectedFuncs(get_func_pool(), "on_startup"):
            run_func(func, isDebug=True)

    loop()

    _cleanup()
    logger.info("HysialX Debug Console is closing...")


if __name__ == "__main__":
    start(run_startup="--no-startup" not in sys.argv)
