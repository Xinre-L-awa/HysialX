from typing import Callable


async def test(send_func: Callable, group_id, sender_id, sender_name, message):
    await send_func(group_id, message)


func_dict = {"test": test}
