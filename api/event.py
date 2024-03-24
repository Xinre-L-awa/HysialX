from pydantic import BaseModel
from typing import Optional, Dict

class MessageEvent:
    _time: Optional[int] = None
    _self_id: int
    _user_id: Optional[str] = None
    _user_name: Optional[str] = None
    _user_group_name: Optional[str] = None
    _group_id: Optional[str] = None
    _message: Optional[str] = None
    _raw_message: Optional[str] = None
    _message_id: Optional[str] = None
    _message_type: Optional[str] = None

    def __init__(
        self, 
        self_id: int,
        msg: dict
    ) -> None:
        self._self_id = self_id

        if msg["post_type"] != "message": return

        self._message = msg["message"]
        self._message_id = msg["message_id"]
        self._raw_message = msg["raw_message"]
        self._user_id = str(msg["sender"]["user_id"])
        self._user_name = msg["sender"]["nickname"]
        self._time = msg["time"]

        if msg["message_type"] == "group":
            self._user_group_name = msg["sender"]["card"]
            self._group_id = str(msg["group_id"])
            self._message_type = "group"
        else:
            self._message_type = "private"

    def reply(self, content: str):
        return f"[CQ:reply,id={self._message_id}] {content}"
    
    def ToGroupMessageEvent(self) -> "GroupMessageEvent":
        gme = GroupMessageEvent(self._self_id, {"post_type": None})
        gme.set_message(self._message)
        gme.set_raw_message(self._raw_message)
        gme._group_id = self._group_id
        gme._message_type = "group"
        gme._time = self._time
        gme._self_id = self._self_id
        gme._user_id = self._user_id
        gme._user_name = self._user_name
        gme._user_group_name = self._user_group_name
        
        return gme
    
    def ToPrivateMessageEvent(self) -> "PrivateMessageEvent":
        pme = PrivateMessageEvent(self._self_id, {"post_type": None})
        pme.set_message(self._message)
        pme.set_raw_message(self._raw_message)
        pme._group_id = self._group_id
        pme._message_type = "private"
        pme._time = self._time
        pme._self_id = self._self_id
        pme._user_id = self._user_id
        pme._user_name = self._user_name
        
        return pme

    @property
    def get_time(self):
        return self._time

    @property
    def get_self_id(self):
        return self._self_id

    @property
    def get_user_id(self):
        return self._user_id

    @property
    def get_user_name(self):
        return self._user_name

    @property
    def get_user_group_name(self):
        return self._user_group_name
    
    @property
    def get_message(self):
        return self._message
    
    def set_message(self, value):
        self._message = value
    
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


class GroupMessageEvent:
    def __init__(self, self_id: int, msg: dict) -> None:
        if msg["post_type"] == None: return

        self._self_id = self_id
        self._time = msg["time"]
        self._user_id = str(msg["sender"]["user_id"])
        self._user_name = msg["sender"]["nickname"]
        self._user_group_name = msg["sender"]["card"]
        self._message = msg["message"]
        self._raw_message = msg["raw_message"]
        self._group_id = str(msg["group_id"])
        self._message_type = "group"
    
    @property
    def get_time(self):
        return self._time

    @property
    def get_self_id(self):
        return self._self_id

    @property
    def get_user_id(self):
        return self._user_id

    @property
    def get_user_name(self):
        return self._user_name
    
    @property
    def get_user_group_name(self):
        return self._user_group_name
    
    @property
    def get_message(self):
        return self._message
    
    def set_message(self, value):
        self._message = value
    
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

class PrivateMessageEvent:
    def __init__(self, self_id: int, msg: dict) -> None:
        if msg["post_type"] == None: return

        self._self_id = self_id
        self._time = msg["time"]
        self._user_id = str(msg["sender"]["user_id"])
        self._user_name = msg["sender"]["nickname"]
        self._message = msg["message"]
        self._raw_message = msg["raw_message"]
        self._group_id = str(msg["group_id"])
        self._message_type = "group"
    
    @property
    def get_time(self):
        return self._time

    @property
    def get_self_id(self):
        return self._self_id

    @property
    def get_user_id(self):
        return self._user_id

    @property
    def get_user_name(self):
        return self._user_name
    
    @property
    def get_message(self):
        return self._message
    
    def set_message(self, value):
        self._message = value
    
    @property
    def get_message_type(self):
        return self._message_type
    
    @property
    def get_raw_message(self):
        return self._raw_message
    
    def set_raw_message(self, value):
        self._raw_message = value

class OnWaitingEvent(MessageEvent):
    input_value: Optional[str]

    def __init__(self, event: MessageEvent | GroupMessageEvent | PrivateMessageEvent) -> None:
        self._time = event.get_time
        self._message = event.get_message
        self._message_type = event.get_message_type

        if self._message_type == "group":
            self._group_id = event.get_user_id
            self._user_group_name = event._user_group_name
        else:
            self._user_id = event.get_user_id
            self._user_name = event.get_user_name

    
    def add_value(self, name, value):
        self.__dict__[name] = value


class NoticeEvent(BaseModel):
    time: int
    self_id: int
    post_type: str
    notice_type: str
    file: Optional[Dict] = None
    sub_type: Optional[str] = None
    duration: Optional[int] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    message_id: Optional[int] = None
    operator_id: Optional[int] = None

    @property
    def get_notice_int_type(self):
        return {
            "group_upload": 1,
            "group_admin": 2,
            "group_decrease": 3,
            "group_increase": 4
        }[self.notice_type]
