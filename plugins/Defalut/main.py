from api import (
    Bot,
    Event,
    custom,
    on_regex,
    on_command,
    get_func_pool
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
            msg.append("{}".format(func.cmd if func.cmd != "占位符占位符占位符占位符" else func.regex))
    await bot.send(event.get_group_id, '\n'.join(msg))
