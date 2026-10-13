from mock_snowluma import group_message, private_message, CaseRunner, _seg
from api.event import MessageEvent, GroupMessageEvent, PrivateMessageEvent, WaitingEvent, NoticeEvent, RequestEvent

SELF_ID = 999
GROUP_ARRAY = {                                   # A-1~A-7 / C-1~C-4
    "post_type": "message", "message_type": "group", "sub_type": "normal",
    "time": 1699108463, "self_id": SELF_ID, "message_id": 12345,
    "group_id": 123456, "user_id": 169699201, "font": 0,
    "message": [
        {"type": "text", "data": {"text": "echo hi"}},
        {"type": "at", "data": {"qq": "3592797817"}},
    ],
    "raw_message": "echo hi[CQ:at,qq=3592797817]",
    "sender": {"user_id": 169699201, "nickname": "雨弈", "card": "群名片",
               "role": "owner", "level": "", "title": ""},
    "anonymous": None,
}
GROUP_STRING = {**GROUP_ARRAY, "message": "echo hi[CQ:at,qq=3592797817]"}     # S-1~S-3
GROUP_STRING_MALFORMED = {**GROUP_ARRAY, "message": "[CQ:at,qq=123 没闭合"}     # S-2
PRIVATE = {                                       # B-1
    "post_type": "message", "message_type": "private", "sub_type": "friend",
    "time": 1699108463, "self_id": SELF_ID, "message_id": 54321,
    "user_id": 169699201, "message": "hi", "raw_message": "hi",
    "sender": {"user_id": 169699201, "nickname": "雨弈", "sex": "unknown", "age": 24},
}                                                  # 注意：没有 group_id
PRIVATE_TEMP = {**PRIVATE, "sub_type": "group", "group_id": 123456}            # B-2
NOTICE = {                                        # D-1~D-4
    "post_type": "notice", "notice_type": "group_increase", "sub_type": "approve",
    "time": 1699108463, "self_id": SELF_ID, "group_id": 123456,
    "user_id": 88888, "operator_id": SELF_ID,
}
REQUEST = {                                       # D-5~D-6
    "post_type": "request", "request_type": "group", "sub_type": "add",
    "time": 1699108463, "self_id": SELF_ID, "group_id": 123456,
    "user_id": 77777, "comment": "求进群", "flag": "flag-1",
}


def test_red_private_should_not_raise():
    ev = PrivateMessageEvent(SELF_ID, private_message("hi"))
    assert ev.get_group_id is None
    assert ev.get_message_type == "private"

def test_red_waiting_event_ids():
    we = WaitingEvent(GroupMessageEvent(SELF_ID, group_message("hi")))
    assert we.get_group_id == "123456"        # 现在 → "169699201"（错位）
    assert we.get_user_id == "169699201"      # 现在 → None
    assert we.get_message_id == 12345         # 现在 → None（reply() 会坏）

    assert MessageEvent(999, GROUP_ARRAY).get_message == "echo hi[CQ:at,qq=3592797817]"

def test_notice_event():
    assert NoticeEvent.model_validate({"notice_type": "group_recall"}).get_notice_int_type == 7
    assert NoticeEvent.model_validate({"notice_type": "not_implemented_yet"}).get_notice_int_type is None
    assert RequestEvent.model_validate({"request_type": "group", "comment": "求进群"}).get_comment == "求进群"
    assert RequestEvent.model_validate(REQUEST).get_request_int_type == 2

def test_message_array():
    runner = CaseRunner()
    ev = MessageEvent(SELF_ID, group_message(
        "echo hi",
        segments=[_seg("text", text="echo hi"), _seg("at", qq="3592797817")],
    ))
    runner.check("A-1 get_message 是 CQ 串",
                 ev.get_message == "echo hi[CQ:at,qq=3592797817]", repr(ev.get_message))
    runner.check("A-2 段视图", [s.type for s in ev.get_message_segments] == ["text", "at"])
    runner.check("A-4 get_user_id 是 str", ev.get_user_id == "169699201", repr(ev.get_user_id))
    assert runner.finish() == 0          # 与你 test_connection.py:245-247 的收尾方式一致


def test_private_without_group_id():
    runner = CaseRunner()
    ev = PrivateMessageEvent(SELF_ID, private_message("hi"))   # 这条没有 group_id
    runner.check("B-1 私聊不炸", ev.get_group_id is None)
    runner.check("B-1 message_type 正确", ev.get_message_type == "private")
    assert runner.finish() == 0
