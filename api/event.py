from typing import Optional

class Event:
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

        self._message_id = msg["message_id"]
        if msg["message_type"] == "group":
            self._time = msg["time"]
            self._user_id = str(msg["sender"]["user_id"])
            self._user_name = msg["sender"]["nickname"]
            self._user_group_name = msg["sender"]["card"]
            self._message = msg["message"]
            self._raw_message = msg["raw_message"]
            self._group_id = str(msg["group_id"])
            self._message_type = "group"
        else:
            self._time = msg["time"]
            self._user_id = str(msg["sender"]["user_id"])
            self._user_name = msg["sender"]["nickname"]
            self._message = msg["message"]
            self._message_type = "private"
            self._raw_message = msg["raw_message"]

    def reply(self, content: str):
        return f"[CQ:reply,id={self._message_id}] {content}"

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


class OnWaitingEvent(Event):
    input_value: Optional[str]

    def __init__(self, event: Event) -> None:
        self._time = event.get_time
        self._group_id = event.get_group_id
        self._group_name = event._group_name
        self._user_id = event.get_user_id
        self._user_name = event.get_user_name
        self._message = event.get_message
        self._message_type = event.get_message_type
    
    def add_value(self, name, value):
        self.__dict__[name] = value
