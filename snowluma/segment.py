"""
SnowLuma (OneBot v11) 消息段转换
"""
import re
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Iterable, TypeAlias


_ESC = (("&", "&amp;"), ("[", "&#91;"), ("]", "&#93;"), (",", "&#44;"))
_CQ_PATTERN = re.compile(r"\[CQ:(?P<type>[A-Za-z0-9_.\-]+)(?P<params>(?:,[^\[\]]*)?)\]")

def escape_cq(text: str) -> str:
    for raw, esc in _ESC:          # 顺序即上表顺序，& 在前
        text = text.replace(raw, esc)
    return text

def unescape_cq(text: str) -> str:
    for raw, esc in reversed(_ESC):  # 反转后 &amp; 在最后
        text = text.replace(esc, raw)
    return text

def _stringify(value: Any) -> str:
    """把参数值渲染成 CQ 码字符串里的形态（只用于渲染，data 里仍存原值）。"""
    if isinstance(value, bool):          # 必须在 int 之前判断，bool 是 int 的子类
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

@dataclass(slots=True)
class MessageSegment:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_cq(cls, cq: str) -> "MessageSegment":
        """把**单个** CQ 码解析成消息段；不含 CQ 码时视为纯文本段。"""
        raw = "" if cq is None else str(cq)
        match = _CQ_PATTERN.fullmatch(raw)
        if match is None:
            return cls.text(unescape_cq(raw))
        return cls(match.group("type"), _parse_params(match.group("params").lstrip(",")))

    @classmethod
    def from_dict(cls, raw: Any) -> "MessageSegment":
        """从消息段字典构造；兼容 {"type","data"} 与扁平 {"type":"at","qq":"1"}"""
        if not isinstance(raw, Mapping):
            raise TypeError(f"无法解析的消息段: {raw!r}")

        seg_type = raw.get("type")
        if not seg_type:
            raise TypeError(f"消息段缺少 type 字段: {raw!r}")

        data = raw.get("data")
        if not isinstance(data, Mapping):
            # 扁平写法：非 data 的键全部抬进 data
            # （json 段的 data 可能是字符串，也会走到这里被当值收进去）
            data = {k: v for k, v in raw.items() if k != "type"}
        return cls(str(seg_type), dict(data))   # dict(...) 浅拷贝，切断与入参的引用共享

    @classmethod
    def text(cls, content: Any) -> "MessageSegment":
        """构造 text 段"""
        if isinstance(content, MessageSegment):
            raise TypeError("text 段的内容必须是字符串；要拼多个段请直接用列表")
        return cls("text", {"text": "" if content is None else str(content)})

    @classmethod
    def at(cls, qq: int) -> "MessageSegment":
        return cls("at", {"qq": str(qq)})

    def to_cq(self) -> str:
        """转成 CQ 码字符串"""
        if self.type == "text":
            # text 是唯一不套 [CQ:...] 外壳的段
            return escape_cq(str(self.data.get("text", "")))

        params = ",".join(
            f"{key}={escape_cq(_stringify(value))}"
            for key, value in self.data.items()
        )
        # 无参数时不留尾逗号：'[CQ:shake]'，不是 '[CQ:shake,]'
        return f"[CQ:{self.type}{',' + params if params else ''}]"

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def to_dict(self) -> dict:
        """转成 OneBot array 格式"""
        return {"type": self.type, "data": dict(self.data)}

    def __str__(self) -> str:          # 日志里一眼看出是段还是 CQ 串
        return self.to_cq()
    

def _parse_params(raw_params: str) -> dict[str, str]:
    """解析 '[CQ:type,k=v,k2=v2]' 里的参数部分。

    用 partition 而不是 split: base64 的 file=xxx== 里有多个 '=', split 会切碎。
    """
    data: dict[str, str] = {}
    for chunk in raw_params.split(","):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        # 没有 '=' 时 value 就是 ""，与 [CQ:at,qq] 这种写法一致
        data[unescape_cq(key)] = unescape_cq(value)
    return data

def parse_cq_to_segments(message: str) -> list[MessageSegment]:
    """
    把 CQ 码字符串切成消息段列表

    - `[CQ:type,k=v]` 变成 `MessageSegment(type, {k: v})`，参数值做反转义
    - 段与段之间的**非空**文本变成 `text` 段，内容做反转义
    - 空串返回 `[]`（而不是一个空 text 段）
    - 畸形输入（`[CQ:at,qq=1` 没有闭合）原样当作文本
    """
    message = "" if message is None else str(message)
    if not message:
        return []

    segments: list[MessageSegment] = []
    cursor = 0

    for match in _CQ_PATTERN.finditer(message):
        # 1) 段之前的文本
        if match.start() > cursor:
            text = unescape_cq(message[cursor:match.start()])
            if text:                     # 只在非空时产出，避免相邻 CQ 之间冒出空 text 段
                segments.append(MessageSegment("text", {"text": text}))
        # 2) 段本身
        segments.append(
            MessageSegment(
                match.group("type"),
                _parse_params(match.group("params").lstrip(",")),
            )
        )
        cursor = match.end()

    # 3) 最后一段文本
    if cursor < len(message):
        text = unescape_cq(message[cursor:])
        if text:
            segments.append(MessageSegment("text", {"text": text}))

    return segments

def segments_to_cq(segments: List[MessageSegment]) -> str:
    return "".join([seg.to_cq() for seg in segments])

def segments_to_dicts(segments: List[MessageSegment]) -> List[Dict[str, Any]]:
    return [seg.to_dict() for seg in segments]


SegmentLike: TypeAlias = str | Mapping[str, Any] | MessageSegment
MessageLike: TypeAlias = SegmentLike | Iterable[Any]
def normalize_segments(message: MessageLike) -> list[MessageSegment]:
    """把任意形态的消息归一成消息段列表

    - str            ->   按 CQ 语法解析（不是纯文本）
    - Mapping        ->   按消息段字典解析（兼容 {"type","data"} 与扁平写法）
    - MessageSegment ->   转换为单元素列表
    - Iterable       ->   逐项归一后展平（嵌套列表也会展平）
    """
    if message is None:
        return []
    if isinstance(message, MessageSegment):
        return [message]
    if isinstance(message, str):
        return parse_cq_to_segments(message)
    if isinstance(message, Mapping):
        return [MessageSegment.from_dict(message)]
    if isinstance(message, Iterable):          # list / tuple / 生成器
        segments: list[MessageSegment] = []
        for item in message:
            if isinstance(item, MessageSegment):
                segments.append(item)
            elif isinstance(item, str):
                segments.extend(parse_cq_to_segments(item))
            elif isinstance(item, Mapping):
                segments.append(MessageSegment.from_dict(item))
            elif isinstance(item, Iterable):
                segments.extend(normalize_segments(item))     # 展平嵌套
            else:
                raise TypeError(f"无法识别的消息段: {item!r}")
        return segments
    raise TypeError(f"无法识别的消息类型: {type(message)!r}")

def normalize_cq(message: MessageLike) -> str:
    if isinstance(message, str):
        return message
    return segments_to_cq(normalize_segments(message))


def message_format_of(message: MessageLike) -> str | None:
    """推断消息类型"""
    if isinstance(message, str):
        return "string"
    if isinstance(message, (MessageSegment, Mapping)):
        return "array"
    if isinstance(message, Iterable):
        return "array"
    return None

def message_to_payload(
    message: MessageLike,
    message_format: str = "array",
    auto_escape: bool = False,
) -> str | List[Dict[str, Any]]:
    """把消息转换成发给 SnowLuma 的 message 载荷"""
    if auto_escape and isinstance(message, str):
        return message                       # 协议端不解析 CQ 码，原样发

    segments = normalize_segments(message)
    if message_format.lower() == "string":
        return segments_to_cq(segments)      # 重新序列化 = 顺带转义，防注入
    return segments_to_dicts(segments)
