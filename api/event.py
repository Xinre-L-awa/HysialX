from script import logger


class Event:
    _time: int
    _user_id: str
    _user_name: str
    _group_id: str
    _message: str
    _message_type: str

    def __init__(
        self, 
        msg: dict
    ) -> None:
        if msg["post_type"] != "message": return

        if msg["message_type"] == "group":
            self._time = msg["time"]
            self._user_id = str(msg["sender"]["user_id"])
            self._user_name = msg["sender"]["nickname"]
            self._message = msg["message"]
            self._group_id = str(msg["group_id"])
            self._message_type = "group"
        else:
            self._time = msg["time"]
            self._user_id = str(msg["sender"]["user_id"])
            self._user_name = msg["sender"]["nickname"]
            self._message = msg["message"]
            self._message_type = "private"

    @property
    def get_time(self):
        return self._time

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
    def get_group_id(self):
        return self._group_id
    
    @property
    def get_message_type(self):
        return self._message_type
    