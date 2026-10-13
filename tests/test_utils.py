"""api/utils.py 的单元测试：纯内存，不连网络、不加载插件、不写 DataForXPlugin。"""

from api.event import GroupMessageEvent, MessageEvent, PrivateMessageEvent
from api.utils import (
    AnalyseCQCode,
    At,
    ImageSegment,
    Message,
    Text,
    func_accepts_event,
)
from plugins.manager import FuncMeta

from mock_snowluma import group_message, private_message   # pytest 会把 tests/ 加进 sys.path

SELF_ID = 999


def _group() -> GroupMessageEvent:
    """真事件实例——func_accepts_event 要的是实例，不是类"""
    return GroupMessageEvent(SELF_ID, group_message("hi"))


def _private() -> PrivateMessageEvent:
    return PrivateMessageEvent(SELF_ID, private_message("hi"))


# ------------------------------------------------------------ func_accepts_event
def test_func_accepts_event():
    def f(bot, event: GroupMessageEvent): ...
    assert func_accepts_event(FuncMeta(f, "on"), _group()) is True


def test_rejects_other_event_type():
    """群注解不该收私聊事件（负例才是这个函数存在的意义）"""
    def f(bot, event: GroupMessageEvent): ...
    assert func_accepts_event(FuncMeta(f, "on"), _private()) is False


def test_accepts_base_class_annotation():
    """MessageEvent 家族改成继承后，注解基类的处理器也能收到群/私聊事件"""
    def f(bot, event: MessageEvent): ...
    meta = FuncMeta(f, "on")
    assert func_accepts_event(meta, _group()) is True
    assert func_accepts_event(meta, _private()) is True


def test_accepts_union_annotation():
    """插件里最常见的写法：GroupMessageEvent | PrivateMessageEvent"""
    def f(bot, event: GroupMessageEvent | PrivateMessageEvent): ...
    meta = FuncMeta(f, "on")
    assert func_accepts_event(meta, _group()) is True
    assert func_accepts_event(meta, _private()) is True


def test_missing_annotation_passes():
    def f(bot, event): ...
    assert func_accepts_event(FuncMeta(f, "on"), _group()) is True


def test_string_annotation_passes():
    """插件若用了 from __future__ import annotations，注解会变成字符串：
    无法 isinstance，按约定保守放行，不要打断分发"""
    def f(bot, event): ...
    f.__annotations__["event"] = "GroupMessageEvent"
    assert func_accepts_event(FuncMeta(f, "on"), _group()) is True


def test_bare_function_supported():
    """不裹 FuncMeta 的裸函数也能判定（task.func 有时就是裸函数）"""
    def f(bot, event: GroupMessageEvent): ...
    assert func_accepts_event(f, _group()) is True


# ------------------------------------------------------------------ CQ 码工具
def test_cq_helpers():
    assert At(169699201) == "[CQ:at,qq=169699201]"
    assert ImageSegment("https://a/b.png") == "[CQ:image,file=https://a/b.png]"   # 旧实现是 [CQ:img]
    assert Message([{"type": "text", "data": {"text": "hi"}}]) == "hi"


def test_text_escapes_user_content():
    """ADR-0001 D5 的安全出口：用户内容要拼进 CQ 串前必须过 Text()"""
    assert Text("[CQ:at,qq=all]") == "&#91;CQ:at&#44;qq=all&#93;"


def test_analyse_cq_code():
    assert AnalyseCQCode("hi[CQ:at,qq=1]") == [
        {"type": "text", "content": "hi"},
        {"type": "at", "qq": "1"},
    ]
