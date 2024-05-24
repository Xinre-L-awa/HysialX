from api import (
    At,
    Bot,
    NoticeEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
    OnWaitingEvent,
    custom,
    on_regex,
    on_notice,
    on_command,
    on_waiting,
    on_scheduled,
    get_func_pool,
    add_child_func
)
from htyping import NoticeEvents

from get_device_runtime_information import getDetailedInfo, getCPUtemperature

@on_regex("echo(.*)")
async def echo(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
) -> None:
    if event.get_message_type == "group":
        await bot.send(event.get_group_id, event.get_message.strip())
    else:
        await bot.send(event.get_user_id, event.get_message.strip(), "private")


@custom(lambda x: x[1:] if x[0] == ' ' else '')
async def echo_(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
) -> None:
    await bot.send(event.get_group_id, event.get_message.strip())


@on_command("服务器状态")
async def get_server_status(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent
):
    # msg = f"CPU 占用: {psutil.cpu_percent()}\n内存占用:{psutil.virtual_memory().percent}"  
    msg = getDetailedInfo() # 树莓派专用
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
    await bot.send(event.get_group_id, "请回复一个值：")
    await bot.input_value(group_id=event.get_group_id)

# temp = ""
# @on_waiting("JUSTCHILD")
async def get_value(
    bot: Bot,
    event: OnWaitingEvent
) -> None:
    await bot.send(event.get_group_id, f"你回复了：{event.input_value}请再次输入")
    # global temp
    # temp = event.input_value
    await bot.input_value(group_id=event.get_group_id)

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
    if float(getCPUtemperature()) >= 70.0:
        pass
