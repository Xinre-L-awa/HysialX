from typing import TYPE_CHECKING, Any, Dict, Optional, Union, NoReturn

if TYPE_CHECKING:
    from .event import MessageEvent
    from snowluma.connection import OneBotConnection

from log import logger
from .utils import (
    CreateOnWaitingTask,
    get_connection,
    require_connection
)
from .exception import FinishException
from plugins.manager import WaitingFuncMeta

from snowluma.exception import ActionFailed, ConnectionUnavailable
from snowluma.segment import MessageLike, normalize_cq

class Bot:
    func: WaitingFuncMeta | None = None       # 当前触发的响应器（M8 分发时设置；等待任务要用）

    def __init__(self, connection: "OneBotConnection | None" = None) -> None:
        self.connection = connection          # 显式注入（测试 / 多账号）；None 时回落到全局 holder
        self.func = None                      # 实例属性，别用类属性（否则并发事件会互相串）

    def _connection(self) -> "OneBotConnection | None":
        return self.connection or get_connection()

    @property
    def self_id(self) -> int | None:
        return getattr(self._connection(), "self_id", None)

    @property
    def is_connected(self) -> bool:
        return bool(getattr(self._connection(), "connected", False))

    async def send(
        self,
        uid: Union[int, str],
        message: MessageLike,
        mode: str = "group",
        *,
        auto_escape: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        发消息：`mode` 不是 "group" 就按私聊处理（兼容旧的 "user"/"private" 传法）。

        返回 `send_msg` 应答里的 `data`（含 message_id）; 任何失败都只记日志并返回 None。
        """
        connection = self._connection()
        message_type = "group" if str(mode).lower() == "group" else "private"
        where = "群" if message_type == "group" else "好友"

        if connection is None:
            logger.warning(f'发送消息到{where} {uid} 失败：尚未建立 SnowLuma 连接')
            return None
        if not normalize_cq(message):
            logger.warning(f"消息为空，跳过发送（目标 {uid}）")
            return None

        try:
            data = await connection.send_message(
                message,
                message_type=message_type,
                group_id=uid if message_type == "group" else None,
                user_id=None if message_type == "group" else uid,
                auto_escape=auto_escape
            )
        except (ActionFailed, ConnectionUnavailable, ValueError) as exc:
            logger.opt(colors=True).warning(f'发送消息到{where} {uid} 失败: {exc}')
            return None
        except Exception as exc:
            logger.exception(exc)
            return None
        
        logger.opt(colors=True).success(f'发送消息到{where} <y>{uid}</y> 成功')
        return data
    
    async def send_group(self, group_id, message, **kwargs):
        return await self.send(group_id, message, "group", **kwargs)

    async def send_user(self, user_id, message, **kwargs):
        """旧名，插件里可能已经在用——保留，行为等于私聊"""
        return await self.send(user_id, message, "private", **kwargs)

    async def send_private(self, user_id, message, **kwargs):
        """新名（与 OneBot 的 message_type=private 对齐）"""
        return await self.send(user_id, message, "private", **kwargs)

    async def reply(self, event: "MessageEvent", message, **kwargs):
        """引用回复：群里回群、私聊回人，并带上 [CQ:reply,id=...] 前缀"""
        content = normalize_cq(message)
        if event.get_message_id is not None:
            content = event.reply(content)        # MessageEvent.reply 生成前缀（M6 已提供）
        if event.is_group and event.get_group_id is not None:
            return await self.send(event.get_group_id, content, "group", **kwargs)
        return await self.send(event.get_user_id, content, "private", **kwargs)

    async def finish(self, uid, message, mode: str = "group", **kwargs) -> NoReturn:
        """发完消息就终止当前插件函数（抛 FinishException）"""
        try:
            await self.send(uid, message, mode, **kwargs)
        finally:
            raise FinishException

    async def delete_msg(self, message_id):
        params = {
            "message_id": message_id
        }
        return await self.call_api("delete_msg", **params)

    async def call_api(self, action: str, *, transport=None, timeout=None, **kwargs) -> Any:
        """调任意 OneBot 动作，返回应答信封里的 data。

        与 send 相反：拿不到数据就抛（插件主动要数据，静默返回 None 会更难查）。
        """
        return await require_connection().call_action(
            action, transport=transport, timeout=timeout, **kwargs
        )

    call_action = call_api        # 别名：你现在写的名字，保留以免教程/代码漂移
    
    async def input_value(self, user_id=None, group_id=None, type_=None) -> None:
        """注册等待任务：同一会话里这个人的下一条消息会触发等待事件的子函数"""
        if self.func is None:
            logger.warning("Bot.func 未设置，无法创建等待任务")
            return
        callback = getattr(self.func, "child_func", None) or getattr(self.func, "_func", None)
        if callback is None:
            logger.warning("当前等待事件没有子函数，等待任务不会被创建")
            return
        CreateOnWaitingTask(callback, user_id, group_id, type_)
        logger.info("A OnWaiting Task has been successfully created.")
