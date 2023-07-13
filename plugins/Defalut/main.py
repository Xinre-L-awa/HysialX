from typing import Callable


async def echo(
    send_func: Callable, 
    group_id, 
    sender_id, 
    sender_name, 
    para_message
):
    await send_func(group_id, para_message)
