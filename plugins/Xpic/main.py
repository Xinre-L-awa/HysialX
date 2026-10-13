import asyncio
import os
import re

from loguru import logger
from random import choice

import wallhavenapi
from wallhavenapi import Purity
from api import (
    At,
    Bot,
    GroupMessageEvent,
    on_regex
)

# 密钥从环境变量读，不再硬编码在源码里。
# 注意：旧版这里写死过一个真实 key（已进 git 历史，需要去 wallhaven 后台吊销）。
api_key = os.environ.get("WALLHAVEN_API_KEY")
if not api_key:
    api_key = "PUT_YOUR_WALLHAVEN_API_KEY_HERE"      # 占位串：只为了让请求走到 API 并被拒，不泄露任何真实密钥
    logger.warning(
        "未配置环境变量 WALLHAVEN_API_KEY，搜图功能将不可用。"
        "请在 wallhaven.cc 的账号设置里生成 API Key，然后设置环境变量后重启，例如："
        "setx WALLHAVEN_API_KEY \"你的key\"（Windows，需重开终端）"
    )


def _split_page(text: str):
    """把文本末尾的页码拆出来：'cat 2' / 'cat,2' → ('cat', 2)；没有页码则 page=None（用 API 默认）"""
    match = re.search(r"^(?P<q>.*?)[\s,]+(?P<page>\d+)$", text.strip())
    if match and match.group("q").strip():
        return match.group("q").strip(), int(match.group("page"))
    return text.strip(), None


@on_regex(r"搜图(.*)")
async def get_pic(
    bot: Bot,
    event: GroupMessageEvent
):
    para = event.get_message

    for ch in para:
        if u'\u4e00' <= ch <= u'\u9fff':
            await bot.send(
                event.get_group_id,
                f"[CQ:at,qq={event.get_user_id}] 暂不支持中文搜索!"
            )
            return

    if api_key == "PUT_YOUR_WALLHAVEN_API_KEY_HERE":
        await bot.send(
            event.get_group_id,
            f"{At(event.get_user_id)} 搜图未配置：请先设置环境变量 WALLHAVEN_API_KEY 后重启"
        )
        return

    query, page = _split_page(para)
    wallhaven_api = wallhavenapi.WallhavenApiV1(api_key=api_key, timeout=4.0)

    try:
        # wallhavenapi 内部是同步 requests（429 时还有 time.sleep），
        # 直接在 async 里调用会卡住整个事件循环 → 丢进线程池执行。
        # purities 必须传 Purity 枚举成员：Purity 不是 str 枚举，
        # 旧代码传字符串 "sfw" 会让 `Purity.sfw in ["sfw"]` 为 False → 生成 purity="000" 被 API 拒。
        data = await asyncio.to_thread(
            wallhaven_api.search,
            query,
            purities=[Purity.sfw],
            page=page          # None 时 API 用默认页；不再硬编码 page=3
        )
    except wallhavenapi.ApiKeyError as exc:
        logger.exception(f"搜图失败[ApiKeyError]: {exc} WALLHAVEN_API_KEY 可能无效或已吊销")
        await bot.finish(event.get_group_id, f"{At(event.get_user_id)} 搜图 API Key 无效，请联系管理员检查 WALLHAVEN_API_KEY")
    except wallhavenapi.RequestsLimitError as exc:
        logger.exception(f"搜图失败[RequestsLimitError]: {exc} 已超出 wallhaven 请求限额，请稍后再试")
        await bot.finish(event.get_group_id, f"{At(event.get_user_id)} 搜图请求过于频繁，请稍后再试")
    except Exception as exc:
        # 至少把异常类型带进日志，别再一律说成"连接超时"
        logger.exception(f"搜图失败[{type(exc).__name__}]: {exc}")
        await bot.finish(event.get_group_id, f"{At(event.get_user_id)} 连接超时")

    if not len(data['data']):
        logger.info(f"查询图片{para} 失败: 查无此图，请尝试使用对应英文重试")

        await bot.send(
            event.get_group_id,
            f"{At(event.get_user_id)}\n"
            "查无此图！"
        )
        return

    await bot.send(
        event.get_group_id,
        f"{At(event.get_user_id)}\n"
        f"[CQ:image,file={choice(data['data'])['path']}]"
    )
