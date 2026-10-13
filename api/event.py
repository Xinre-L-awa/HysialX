from pydantic import BaseModel, ConfigDict
from typing import Any, Optional, Dict, List

from snowluma.segment import (
    MessageSegment, parse_cq_to_segments, segments_to_cq, normalize_segments,
)
from htyping import NOTICE_TYPE_IDS, REQUEST_TYPE_IDS


def _as_int(value: Any, default: Optional[int]) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

class SenderInfo:
    def __init__(self, raw: Dict[str, Any] | None):
        self._raw = raw or {}

    @property
    def user_id(self) -> int | None:
        return _as_int(self.get("user_id"), None)

    @property
    def nickname(self) -> str:
        return self.get("nickname", '')
    
    @property
    def card(self) -> str: 
        return self.get("card", '')
    
    @property
    def role(self) -> str | None:
        return self.get("role")
    
    @property
    def level(self) -> str | None:
        return self.get("level")
    
    @property
    def title(self) -> str | None:
        return self.get("title")
    
    @property
    def sex(self) -> str | None:
        return self.get("sex")
    
    @property
    def age(self) -> int | None: 
        return _as_int(self.get("age"), None)
    
    @property
    def display_name(self) -> str:        # card or nickname or str(user_id)
        if card := self.card:
            return card
        elif nickname := self.nickname:
            return nickname
        else:
            return str(self.get("user_id") or "")
    
    def get(self, key, default=None): 
        return self._raw.get(key, default)
    
    def to_dict(self) -> dict: 
        return dict(self._raw)


class MessageEvent:
    _self_id: Optional[int] = None        # ← 原来是 _self_id: int
    _post_type: str = "message"
    _time: Optional[int]
    _message_type: Optional[str]
    _sub_type: Optional[str] = None
    _message_id: Any                      # 保持原值(可能是负数)，reply() 直接拼
    _font: Optional[int] = None
    _target_id: Optional[str] = None
    _anonymous: Any = None
    _group_id: Optional[str]              # str：插件拼串、等待任务 == 比较都用它
    _payload: dict                                        # __init__ 一定会赋值，别用类级可变默认值
    _segments: List[MessageSegment]
    _sender: Optional[SenderInfo] = None
    _user_id: Optional[str]               # str，见 M6 教程 §2 兼容性契约
    _user_name: str
    _user_group_name: str
    _message: str
    _raw_message: str

    def __init__(
        self,
        self_id: Optional[int] = None,
        payload: Optional[dict] = None,
    ) -> None:
        # 兼容 MessageEvent(payload) 的写法；不想要这层兼容就删掉下面两行
        if payload is None and isinstance(self_id, dict):
            self_id, payload = None, self_id
        payload = dict(payload or {})          # 浅拷贝，切断与调用方 dict 的引用共享

        self._payload = payload                # To* shim / WaitingEvent 整份复制用
        self._self_id = _as_int(
            self_id if self_id is not None else payload.get("self_id"), None
        )
        self._post_type = str(payload.get("post_type") or "message")   # message_sent 也从这里来
        self._time = _as_int(payload.get("time"), None)
        self._message_type = payload.get("message_type")
        self._sub_type = payload.get("sub_type")
        self._message_id = payload.get("message_id")     # 保持原值，reply() 要拼
        self._font = _as_int(payload.get("font"), None)
        self._anonymous = payload.get("anonymous")

        # 会话 id 一律存 str：插件在拼 f-string / CQ 码，等待任务也在用它做 == 比较
        group_id = payload.get("group_id")
        self._group_id = None if group_id is None else str(group_id)
        target_id = payload.get("target_id")
        self._target_id = None if target_id is None else str(target_id)

        # sender 缺失(私聊精简 payload / 通知)也要能构造
        self._sender = SenderInfo(payload.get("sender"))
        user_id = self._sender.user_id
        if user_id is None:                              # 少数实现把 user_id 放在顶层
            user_id = _as_int(payload.get("user_id"), None)
        self._user_id = None if user_id is None else str(user_id)
        self._user_name = self._sender.nickname          # 别丢：t 插件 / 日志在用
        self._user_group_name = self._sender.card        # 无名片时是 ""，不是 KeyError

        raw_message = payload.get("raw_message")
        message = payload.get("message")
        if message is None:                              # 有的实现只在 raw_message 里给消息
            message = raw_message if raw_message is not None else ""

        if isinstance(message, str):
            self._message = message                      # string 格式：原样保留(教程 §2.1)
            self._segments = parse_cq_to_segments(message)
        else:
            self._segments = normalize_segments(message)  # array / 单个 dict / MessageSegment
            self._message = segments_to_cq(self._segments)

        self._raw_message = (
            raw_message if isinstance(raw_message, str)
            else segments_to_cq(self._segments)
        )

    def reply(self, content: str) -> str:
        """引用回复前缀；`_message_id` 可能是负数，直接插值不要 int() 加工"""
        return f"[CQ:reply,id={self._message_id}] {content}"
    
    def ToGroupMessageEvent(self) -> "GroupMessageEvent":
        return GroupMessageEvent(self._self_id, self._payload)
    
    def ToPrivateMessageEvent(self) -> "PrivateMessageEvent":
        return PrivateMessageEvent(self._self_id, self._payload)

    @property
    def get_time(self):
        return self._time

    @property
    def get_self_id(self):
        return self._self_id

    @property
    def get_post_type(self):
        return self._post_type

    @property
    def get_sub_type(self):
        return self._sub_type

    @property
    def get_font(self):
        return self._font

    @property
    def get_sender(self):
        return self._sender

    @property
    def get_user_id(self) -> Optional[str]:
        """
        **永远是 str**：插件拼 CQ 码、等待任务做 `==` 比较都依赖它。
        别返回 `self._sender.user_id`(int)——sender 缺失时还要能回退到顶层 user_id
        """
        return self._user_id

    @property
    def get_user_name(self) -> str:
        return self._user_name

    @property
    def get_user_group_name(self) -> str:
        """群名片；无名片时是 ""，不是 None(main.py 在跟 '' 比较)"""
        return self._user_group_name

    @property
    def get_user_role(self) -> Optional[str]:
        return self._sender.role

    @property
    def get_display_name(self) -> str:
        """群名片 > 昵称 > QQ 号；日志用，跟 get_user_id 同一套回退顺序"""
        return self._user_group_name or self._user_name or (self._user_id or "")

    @property
    def get_target_id(self) -> Optional[str]:
        return self._target_id
    
    @property
    def get_message(self) -> str:
        """CQ 码字符串(已转义)——可直接回发、可打日志，见 ADR-0001 D2"""
        return self._message

    @property
    def get_message_id(self) -> Any:
        """可能为负数，保持原值"""
        return self._message_id

    @property
    def get_message_segments(self) -> list[MessageSegment]:
        """段视图(副本，避免调用方就地 mutate 污染事件)"""
        return list(self._segments)

    @property
    def get_plain_text(self) -> str:
        """只拼 text 段，**未转义**：只能用于命令/关键词/正则匹配，禁止直接回发(ADR-0001 D4)"""
        return "".join(
            str(seg.get("text", "")) for seg in self._segments if seg.type == "text"
        )
    
    def set_message(self, value: str | MessageSegment):
        if isinstance(value, str):
            self._message = value
            self._segments = parse_cq_to_segments(value)
        else:
            self._segments = normalize_segments(value)
            self._message = segments_to_cq(self._segments)
    
    @property
    def get_raw_message(self):
        return self._raw_message
    
    def set_raw_message(self, value):
        self._raw_message = value

    @property
    def get_group_id(self):
        return self._group_id
    
    @property
    def get_message_type(self):
        return self._message_type

    # ------------------------------------------------------------ 只读：类型判定
    @property
    def is_group(self) -> bool:
        return self._message_type == "group"

    @property
    def is_private(self) -> bool:
        return self._message_type == "private"

    @property
    def is_self_message(self) -> bool:
        """机器人自己发的消息(SnowLuma 打开 reportSelfMessage 时的 post_type=message_sent)"""
        return self._post_type == "message_sent"

    def get_payload(self) -> dict:
        """
        原始事件字典(浅拷贝)

        浅拷贝的边界：嵌套的 sender / message 结构仍与原始 dict 共享。
        """
        return dict(self._payload)

    @classmethod
    def from_payload(cls, payload: dict) -> "MessageEvent":
        """按 message_type 分派到具体子类（M8 分发器唯一入口）"""
        message_type = (payload or {}).get("message_type")
        if message_type == "group":
            return GroupMessageEvent(payload.get("self_id"), payload)
        if message_type == "private":
            return PrivateMessageEvent(payload.get("self_id"), payload)
        return MessageEvent(payload.get("self_id"), payload)


    def __repr__(self) -> str:            # 日志里一眼看清是哪条事件
        return (
            f"<{type(self).__name__} user={self._user_id} group={self._group_id} "
            f"message={self._message!r}>"
        )

class GroupMessageEvent(MessageEvent):
    def __init__(self, self_id = None, payload = None):
        super().__init__(self_id, payload)
        self._message_type = "group"

class PrivateMessageEvent(MessageEvent):
    def __init__(self, self_id = None, payload = None):
        super().__init__(self_id, payload)
        self._message_type = "private"

class WaitingEvent(MessageEvent):
    input_value: str | None = None

    def __init__(self, event: MessageEvent) -> None:
        super().__init__(event.get_self_id, event.get_payload())   # 全字段复制(get_payload 是方法，带括号)
        self._message = event.get_message                          # property，别加括号
        self._segments = event.get_message_segments                # 返回的是副本，正好归本事件所有
        self.input_value = None
    
    def add_value(self, name, value):
        self.__dict__[name] = value


class NoticeEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    post_type: str = "notice"
    notice_type: str | None = None         # 判别字段；协议端没给也别把整条事件丢掉
    time: int | None = None
    self_id: int | None = None
    sub_type: str | None = None
    group_id: int | None = None
    user_id: int | None = None
    operator_id: int | None = None
    target_id: int | None = None
    message_id: int | None = None
    duration: int | None = None
    file: dict | None = None
    honor_type: str | None = None
    anonymous: Any = None

    @property
    def get_notice_int_type(self) -> int | None: return NOTICE_TYPE_IDS.get(self.notice_type)
    @property
    def get_group_id(self) -> str | None: return None if self.group_id is None else str(self.group_id)
    @property
    def get_user_id(self) -> str | None: return None if self.user_id is None else str(self.user_id)
    @property
    def get_operator_id(self) -> str | None: return None if self.operator_id is None else str(self.operator_id)

class RequestEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    post_type: str = "request"
    request_type: str | None = None       # "friend" / "group"；缺字段时别丢整条事件
    time: int | None = None
    self_id: int | None = None
    sub_type: str | None = None           # "add" / "invite"
    comment: str | None = None
    flag: str | None = None
    user_id: int | None = None
    group_id: int | None = None

    @property
    def get_request_int_type(self) -> int | None: return REQUEST_TYPE_IDS.get(self.request_type)
    @property
    def get_comment(self) -> str: return self.comment or ""

