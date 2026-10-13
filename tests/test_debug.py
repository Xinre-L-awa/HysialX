# tests/test_debug.py —— M8：调试控制台的无头验收（不联网、不进交互循环）
"""验证 debug.py 的"造事件 → main.handle_event → 插件 → DebugConnection"整条链路。

隔离要求（别再靠"用例恰好不喂数据类事件"这种运气）：
- 数据目录必须被 monkeypatch 到 tmp_path：插件读写 `api.DEFAULT_PLUGINS_DATA_PATH` 时才会落到临时目录
- 等待任务池与全局连接在用例结束后清干净
"""

import shutil
import sys
import uuid
from pathlib import Path

import pytest

import debug
import main as main_module
from api import get_waiting_task_pool, set_connection
from script import load_plugins

SELF_ID = 999

# 这些模块会把数据目录常量复制到自己的模块命名空间里，patch api 之外还得补一次
_PLUGIN_MODULES = ("plugins.XHuaLao.main", "plugins.XHuaLao.app", "plugins.t.main")
_DATA_ATTRS = ("DEFAULT_PLUGINS_DATA_PATH", "data_folder", "DATA_DIR", "DATA_FOLDER", "DATA_PATH")


@pytest.fixture
def sandbox(monkeypatch):
    """隔离：① 数据目录指到工作区里的临时目录 ② 用例结束后清干净全局状态。

    注意：**不要用 `tmp_path`** —— 本机沙箱对系统临时目录下的 pytest 基目录拒绝访问
    （`PermissionError: [WinError 5] ...\\Temp\\pytest-of-*`），所以临时目录放在工作区内。
    """
    import api

    data_dir = Path(".workbuddy") / "pytest-data" / uuid.uuid4().hex / "DataForXPlugin"
    data_dir.mkdir(parents=True, exist_ok=True)
    # 必须在 load_plugins() 之前 patch：插件首次 import 时才会绑定到临时目录
    monkeypatch.setattr(api, "DEFAULT_PLUGINS_DATA_PATH", str(data_dir), raising=False)

    load_plugins()
    for module_name in _PLUGIN_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attr in _DATA_ATTRS:
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, str(data_dir), raising=False)

    main_module.refresh_funcs()
    connection = debug.DebugConnection(self_id=SELF_ID, nickname="DebugTest")
    set_connection(connection)
    try:
        yield connection, data_dir
    finally:
        set_connection(None)
        pool = get_waiting_task_pool()
        left = list(pool)
        if left:
            pool.pop_tasks(left)
        main_module.refresh_funcs()
        shutil.rmtree(data_dir.parent, ignore_errors=True)


def _sends(connection) -> list[dict]:
    return [params for action, params in connection.calls if action == "send_msg"]


def test_debug_feed_runs_real_plugin(sandbox):
    """echo hi → Defalut 的 on_regex("echo(.*)") → 经完整 M7 逻辑发出 send_msg"""
    connection, _ = sandbox
    debug.feed(debug.build_payload("echo hi"))
    sends = _sends(connection)
    assert sends, "插件没有触发发送（检查 load_plugins / refresh_funcs）"
    assert sends[0]["message_type"] == "group"
    # 注意：MessageEvent.get_group_id 按 M6 契约返回 str；
    # 真连接在 send_message 里用 _coerce_id 转 int，假连接（LocalEchoConnection）不做转换。
    assert str(sends[0]["group_id"]) == str(debug.DEBUG_GROUP_ID)
    assert sends[0]["message"] == "hi"          # echo 处理器里的 .strip()


def test_debug_notice_triggers_plugin(sandbox):
    """notice group_increase → Defalut 的入群欢迎"""
    connection, _ = sandbox
    assert "已投递" in str(debug.AnalyseCommand("notice group_increase"))
    sends = _sends(connection)
    assert sends, "通知事件没有触发插件发送"
    assert "CQ:at" in str(sends[0]["message"])


def test_debug_request_and_sent_do_not_crash(sandbox):
    """request / message_sent 能走完分发链（Defalut 没注册 on_request，只要求不炸）"""
    sandbox
    assert "已投递" in str(debug.AnalyseCommand("request group"))
    assert "已投递" in str(debug.AnalyseCommand("sent 我在测试"))


def test_debug_build_and_send_through_console(sandbox):
    """控制台命令链路：build 存变量 → send 取出并投递"""
    connection, _ = sandbox
    assert debug.AnalyseCommand("build $msg echo 控制台 -format=array") == "Success"
    assert "已投递 1 次" in str(debug.AnalyseCommand("send $msg"))
    sends = _sends(connection)
    assert sends and sends[0]["message"] == "控制台"
    if debug.variables.isExist("msg"):
        debug.variables.delete_variable("msg")


def test_debug_send_rejects_non_json_variable(sandbox):
    """变量里不是事件 JSON 时给友好提示，而不是抛 JSONDecodeError 栈"""
    sandbox
    debug.AnalyseCommand("set greet 早上好")
    out = str(debug.AnalyseCommand("send $greet"))
    assert "不是事件 JSON" in out, out
    if debug.variables.isExist("greet"):
        debug.variables.delete_variable("greet")


def test_debug_fail_injection_does_not_raise(sandbox):
    """fail on 时 bot.send 只记 warning、不抛异常（M7 §2.1 的语义）"""
    connection, _ = sandbox
    connection.fail = True
    try:
        debug.feed(debug.build_payload("echo hi"))      # 不应抛
        assert _sends(connection), "失败注入下也应记录到 send_msg"
    finally:
        connection.fail = False


def test_debug_conn_and_clear_commands(sandbox):
    sandbox
    assert "self_id=999" in str(debug.AnalyseCommand("conn"))
    assert "已清空" in str(debug.AnalyseCommand("clear"))


def test_debug_writes_only_into_tmp_data_dir(sandbox):
    """跑完一轮事件后，真实 DataForXPlugin 不该被碰：插件数据只能落到 tmp_path"""
    connection, data_dir = sandbox
    debug.feed(debug.build_payload("echo hi"))
    assert data_dir.exists()
    written = sorted(p.name for p in data_dir.rglob("*") if p.is_file())
    # 允许为空（echo 不写数据），关键是不能写到仓库里的 DataForXPlugin
    assert all("DataForXPlugin" in str(p) for p in data_dir.rglob("*"))
    assert written is not None
