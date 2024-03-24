from enum import Enum

class NoticeEvents(Enum):
    GroupUpload = 1
    GroupAdmin = 2
    GroupDecrease = 3
    GroupIncrease = 4
    GroupBan = 5
    FriendAdd = 6
    GroupRecall = 7
    FriendRecall = 8
    GroupCard = 9
    OfflineFile = 10
    ClientStatus = 11
    Essence = 12
    Notify = 13