from api import Bot, Event

async def echo(
    bot: Bot,
    event: Event
) -> None:
    await bot.send(event.get_group_id, event.get_message)

async def DisplayAllFunc(
    bot: Bot,
    event: Event
):
    msg = []
    for func_name, _ in bot.func_dict.items():
        msg.append(f"{func_name}")
    await bot.send(event.get_group_id, '\n'.join(msg))
