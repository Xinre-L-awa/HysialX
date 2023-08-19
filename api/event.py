class Event:
    _time: int = None
    _user_id: str = None
    _user_name: str = None
    _user_group_name: str = None
    _group_id: str = None
    _message: str = None
    _message_type: str = None

    def __init__(
        self, 
        msg: dict
    ) -> None:
        if msg["post_type"] != "message": return

        if msg["message_type"] == "group":
            self._time = msg["time"]
            self._user_id = str(msg["sender"]["user_id"])
            self._user_name = msg["sender"]["nickname"]
            self._user_group_name = msg["sender"]["card"]
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
    def get_user_group_name(self):
        return self._user_group_name
    
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
    