from api import (
    At,
    Bot,
    NoticeEvent,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    WaitingEvent,
    custom,
    on_regex,
    on_notice,
    on_command,
    on_waiting,
    on_startup,
    on_scheduled,
    get_func_pool,
    get_scheduled_task_pool,
    add_child_func,
    set_device
)
from htyping import NoticeEvents

import datetime
import psutil, time
# from get_device_runtime_information import getDetailedInfo, getCPUtemperature

@on_regex("echo(.*)")
async def echo(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
) -> None:
    # 用纯文本：get_message 是转义过的 CQ 串，回发会把用户的 CQ 码当文字吐出去
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, event.get_plain_text.strip())
    else:
        await bot.send(event.get_user_id, event.get_plain_text.strip(), "private")


# 匹配器收到的是 get_plain_text()（main.py 的 custom 分发），空文本不能 x[0] 索引
@custom(lambda x: x[1:] if x.startswith(' ') else '')
async def echo_(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
) -> None:
    # 私聊时 get_group_id 是 None，按"群"发等于发到 None → 消息静默丢失，这里分流
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, event.get_plain_text.strip())
    else:
        await bot.send(event.get_user_id, event.get_plain_text.strip(), "private")


@on_command("服务器状态")
async def get_server_status(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
):
    msg = f"CPU 占用: {psutil.cpu_percent()}\n内存占用:{psutil.virtual_memory().percent}"  
    # msg = getDetailedInfo() # 树莓派专用
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, msg)
    else:
        await bot.send(event.get_user_id, msg, "private")


@on_command(".about")
async def about(
    bot: Bot,
    event: GroupMessageEvent
):
    await bot.send(event.get_group_id, "项目名项目地址")


@on_command("菜单")
async def DisplayAllFunc(
    bot: Bot,
    event: GroupMessageEvent
):
    msg = []
    for func in get_func_pool():
        if func.x:
            msg.append("{}".format(func.name))
    await bot.send(event.get_group_id, '\n'.join(msg))


@on_waiting("input")
async def Input(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
) -> None:
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, "请回复一个值：")
        # 等待任务按会话过滤：群聊记 group_id、私聊只记 user_id。
        # 旧写法私聊也传 group_id=None，而 main.py 用 `event.get_group_id == task.group_id`
        # 判断，私聊事件的 group_id 也是 None → 任意私聊都会命中别人的等待任务。
        await bot.input_value(group_id=event.get_group_id)
    else:
        await bot.send(event.get_user_id, "请回复一个值：", "private")
        await bot.input_value(user_id=event.get_user_id)

# temp = ""
# @on_waiting("JUSTCHILD")
async def get_value(
    bot: Bot,
    event: WaitingEvent
) -> None:
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, f"你回复了：{event.input_value}请再次输入")
        await bot.input_value(group_id=event.get_group_id)
    else:
        await bot.send(event.get_user_id, f"你回复了：{event.input_value}请再次输入", "private")
        await bot.input_value(user_id=event.get_user_id)

add_child_func(Input, get_value)


# async def varified(
#     bot: Bot,
#     event: OnWaitingEvent
# ) -> None:
#     if event.get_message == temp:
#         await bot.finish(event.get_group_id, "前后回复一致，验证通过")
#     await bot.send(event.get_group_id, "前后回复不一致，验证失败")

# add_child_func(get_value, varified)


@on_notice(NoticeEvents.GroupIncrease)
async def welcome_new_member(
    bot: Bot,
    event: NoticeEvent
):
    await bot.send(event.group_id, f"{At(event.user_id)} 热烈欢迎~")


@on_notice(NoticeEvents.GroupDecrease)
async def member_leave(
    bot: Bot,
    event: NoticeEvent
):
    await bot.send(event.group_id, f"{event.user_id} 离开了我们")


@on_scheduled(frequency=2, disposable=True)
def test():
    print(f"计划任务 test 执行 - 当前时间为{time.time()}")

@on_scheduled(frequency=60)          # 每 60 秒触发一次
async def send_current_time():
    """每分钟向好友 169699201 发送当前时间，格式为 时:分:秒"""
    now = datetime.datetime.now().strftime("%H:%M:%S")
    await Bot().send_user(169699201, now)



@on_command("114514")
async def set_model(bot: Bot, event: MessageEvent):
    await set_device("114514 大粪手机")
