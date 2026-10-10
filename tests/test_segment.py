from snowluma.segment import MessageSegment, parse_cq_to_segments, message_to_payload, normalize_segments

def test_segment():
    
    assert message_to_payload("hi[CQ:at,qq=1]") == [
        {"type": "text", "data": {"text": "hi"}}, {"type": "at", "data": {"qq": "1"}}]
    assert message_to_payload("hi[CQ:at,qq=1]", "string") == "hi[CQ:at,qq=1]"

    # array：文本原样存真值；string：文本被转义
    assert message_to_payload("a[b],c") == [{"type": "text", "data": {"text": "a[b],c"}}]
    assert message_to_payload("a[b],c", "string") == "a&#91;b&#93;&#44;c"
    assert message_to_payload(MessageSegment.text("[CQ:at,qq=1]"), "string") == "&#91;CQ:at&#44;qq=1&#93;"

    # auto_escape 短路
    assert message_to_payload("[CQ:at,qq=1]", auto_escape=True) == "[CQ:at,qq=1]"

    # 空消息不兜底（交给 bot.send 打 warning 决定跳不跳）
    assert message_to_payload("") == [] and message_to_payload("", "string") == ""
    assert message_to_payload(None) == []
    assert message_to_payload(MessageSegment.text("x"), "auto") == [{"type": "text", "data": {"text": "x"}}]


    assert parse_cq_to_segments("") == []
    assert parse_cq_to_segments("hello") == [MessageSegment("text", {"text": "hello"})]
    assert parse_cq_to_segments("[CQ:at,qq=123]") == [MessageSegment("at", {"qq": "123"})]
    assert parse_cq_to_segments("a[CQ:at,qq=1]b") == [
        MessageSegment("text", {"text": "a"}),
        MessageSegment("at", {"qq": "1"}),
        MessageSegment("text", {"text": "b"}),
    ]
    assert parse_cq_to_segments("[CQ:face,id=1][CQ:face,id=2]") == [
        MessageSegment("face", {"id": "1"}),
        MessageSegment("face", {"id": "2"}),
    ]
    assert parse_cq_to_segments("[CQ:image,file=base64://AAA==]") == [
        MessageSegment("image", {"file": "base64://AAA=="})
    ]
    assert parse_cq_to_segments("[CQ:at,qq=123") == [MessageSegment("text", {"text": "[CQ:at,qq=123"})]
    assert parse_cq_to_segments("[CQ:shake]") == [MessageSegment("shake", {})]
    assert parse_cq_to_segments("看这个 &#91;CQ:at,qq=1&#93; 好玩吧&#44; 真的") == [
        MessageSegment("text", {"text": "看这个 [CQ:at,qq=1] 好玩吧, 真的"})
    ]
    assert parse_cq_to_segments("字面量 &amp;#91; 实体") == [
        MessageSegment("text", {"text": "字面量 &#91; 实体"})
    ]

    # ① round-trip：结构合法的 CQ 串进出一致
    for cq in ["[CQ:at,qq=1]", "[CQ:shake]", "[CQ:face,id=1]", "[CQ:reply,id=100]",
            "[CQ:image,file=https://a/b.png?x=1&amp;y=2]", "hi"]:
        assert MessageSegment.from_cq(cq).to_cq() == cq, cq

    # ② 值渲染
    assert MessageSegment("at",    {"qq": 123}).to_cq()                    == "[CQ:at,qq=123]"
    assert MessageSegment("image", {"file": "x", "cache": False}).to_cq()  == "[CQ:image,file=x,cache=false]"
    assert MessageSegment("json",  {"data": {"a": 1}}).to_cq()             == '[CQ:json,data={"a":1}]'
    assert MessageSegment("shake", {}).to_cq()                             == "[CQ:shake]"
    assert MessageSegment("text",  {}).to_cq()                             == ""

    # ③ 注入防线：文本里的 CQ 码被转义，且往返三趟不变成结构
    t = MessageSegment.text("[CQ:at,qq=123] 大家好")
    assert t.to_cq() == "&#91;CQ:at&#44;qq=123&#93; 大家好"
    assert MessageSegment.from_cq(t.to_cq()).data["text"] == "[CQ:at,qq=123] 大家好"

    # ④ json 里的逗号靠转义活着（这一对必须一起过）
    j = MessageSegment("json", {"data": {"a": 1, "b": 2}})
    assert j.to_cq() == '[CQ:json,data={"a":1&#44;"b":2}]'
    assert MessageSegment.from_cq(j.to_cq()).data["data"] == '{"a":1,"b":2}'

    # ⑤ data 不漏引用
    seg = MessageSegment("at", {"qq": "1"})
    seg.to_dict()["data"]["qq"] = "hacked"
    assert seg.data["qq"] == "1"

    assert MessageSegment.text("hi").to_cq() == "hi"
    assert MessageSegment.text("[CQ:at,qq=1]").to_cq() == "&#91;CQ:at&#44;qq=1&#93;"
    assert MessageSegment.text(None).data == {"text": ""}
    assert MessageSegment.at(123).to_dict() == {"type": "at", "data": {"qq": "123"}}
    assert MessageSegment.from_cq("普通文本") == MessageSegment.text("普通文本")   # 兜底分支走的就是它


    S = MessageSegment

    assert normalize_segments(None) == []
    assert normalize_segments("") == []
    assert normalize_segments("hello") == [S("text", {"text": "hello"})]
    assert normalize_segments("[CQ:at,qq=1]") == [S("at", {"qq": "1"})]
    assert normalize_segments(S("at", {"qq": "1"})) == [S("at", {"qq": "1"})]

    # 标准 / 扁平 / json 字符串 data
    assert normalize_segments({"type": "at", "data": {"qq": "1"}}) == [S("at", {"qq": "1"})]
    assert normalize_segments({"type": "at", "qq": "1"}) == [S("at", {"qq": "1"})]
    assert normalize_segments({"type": "json", "data": '{"a":1}'}) == [S("json", {"data": '{"a":1}'})]

    # 混合列表 + 嵌套展平
    assert normalize_segments(["hi", {"type": "at", "data": {"qq": "1"}}]) == [
        S("text", {"text": "hi"}), S("at", {"qq": "1"})]
    assert normalize_segments([S("at", {"qq": "1"}), [S("face", {"id": "2"})]]) == [
        S("at", {"qq": "1"}), S("face", {"id": "2"})]

    # 列表里的字符串按 CQ 解析（决策点 1）
    assert normalize_segments(["hi[CQ:at,qq=1]"]) == [S("text", {"text": "hi"}), S("at", {"qq": "1"})]

    # 幂等 + 新列表 + 不共享引用
    once = normalize_segments("a[CQ:at,qq=1]")
    assert normalize_segments(once) == once
    assert normalize_segments(once) is not once
    payload = {"type": "at", "data": {"qq": "1"}}
    seg = normalize_segments(payload)[0]
    seg.data["qq"] = "hacked"
    assert payload["data"]["qq"] == "1"

    # 快速失败
    import pytest
    for bad in (123, b"x", [{"qq": "1"}], {"data": {}}):
        with pytest.raises(TypeError):
            normalize_segments(bad)