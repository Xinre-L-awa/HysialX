from api import (
    Bot,
    Event,
    OnWaitingEvent,
    custom,
    on_regex,
    on_command,
    on_waiting,
    get_func_pool,
    add_child_func
)


@on_regex("echo(.*)")
async def echo(
    bot: Bot,
    event: Event
) -> None:
    await bot.send(event.get_group_id, event.get_message.strip())


@custom(lambda x: x[1:] if x[0] == ' ' else '')
async def echo_(
    bot: Bot,
    event: Event
) -> None:
    await bot.send(event.get_group_id, event.get_message.strip())


@on_command("菜单")
async def DisplayAllFunc(
    bot: Bot,
    event: Event
):
    msg = []
    for func in get_func_pool():
        if func.x:
            msg.append("{}".format(func.cmd if func.cmd != None else func.regex))
    await bot.send(event.get_group_id, '\n'.join(msg))


@on_waiting("input")
async def Input(
    bot: Bot,
    event: Event
) -> None:
    await bot.send(event.get_group_id, "请回复一个值：")
    await bot.input_value()


async def get_value(
    bot: Bot,
    event: OnWaitingEvent
) -> None:
    await bot.send(event.get_group_id, event.input_value)

add_child_func(Input, get_value)
