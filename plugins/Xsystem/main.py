import psutil


async def get_server_info(
    send_func, 
    group_id, 
    *args
):
    psutil.cpu_percent(None)

    await send_func(
        group_id,
        f"当前服务器CPU使用率: {psutil.cpu_percent()} 内存占用率: {psutil.virtual_memory().percent}"
    )
