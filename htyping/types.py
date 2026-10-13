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
    
class RequestEvents(Enum):
    Friend = 1
    Group = 2

# OneBot v11 的 notice_type 字符串 → 枚举值
NOTICE_TYPE_IDS = {
    "group_upload"  :  NoticeEvents.GroupUpload.value,
    "group_admin"   :  NoticeEvents.GroupAdmin.value,
    "group_decrease":  NoticeEvents.GroupDecrease.value,
    "group_increase":  NoticeEvents.GroupIncrease.value,
    "group_ban"     :  NoticeEvents.GroupBan.value,
    "friend_add"    :  NoticeEvents.FriendAdd.value,
    "group_recall"  :  NoticeEvents.GroupRecall.value,
    "friend_recall" :  NoticeEvents.FriendRecall.value,
    "group_card"    :  NoticeEvents.GroupCard.value,
    "offline_file"  :  NoticeEvents.OfflineFile.value,
    "client_status" :  NoticeEvents.ClientStatus.value,
    "essence"       :  NoticeEvents.Essence.value,
    "notify"        :  NoticeEvents.Notify.value,
}
REQUEST_TYPE_IDS = {"friend": RequestEvents.Friend.value, "group": RequestEvents.Group.value}
