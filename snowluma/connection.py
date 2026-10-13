"""
SnowLuma(OneBot v11) 连接层
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
import uuid
from typing import Any, Awaitable, Dict, List, Optional, Set, Union
from urllib.parse import parse_qs, urlsplit

import hmac
import httpx
import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus
from websockets.asyncio.client import ClientConnection      # 反向模式用
from websockets.asyncio.server import ServerConnection      # 正向服务端
from websockets.http11 import Request

from loguru import logger

from .config import SnowLumaConfig
from .segment import MessageLike, message_format_of, message_to_payload, normalize_cq
from .exception import ActionFailed, ConnectionUnavailable

__all__ = ["Channel", "OneBotConnection", "LocalEchoConnection"]

_MAX_MESSAGE_SIZE = 16 * 1024 * 1024    # 消息中可能包含base64图片
_EVENT_QUEUE_SIZE = 1024
_CONNECTION_ERRORS = (OSError, InvalidStatus, InvalidHandshake, ConnectionClosed, asyncio.TimeoutError)


def _coerce_id(value: Any) -> Union[int, str]:
    """OneBot 的 id 是数字，但插件历史代码传的是字符串"""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.lstrip("-").isdigit() else text

def _interval(value: Optional[float], default: Optional[float]) -> Optional[float]:
    """心跳参数: None → 用默认值; <=0 → None(关闭心跳)。"""
    if value is None:
        return default
    return None if float(value) <= 0 else float(value)

def _extract_token(path: str, headers: Dict[str, Any]) -> Optional[str]:
    try:
        query = parse_qs(urlsplit(path).query)
    except ValueError:
        query = {}

    if token := query.get("access_token"):
        return token[0]
    if headers is not None:
        auth = headers.get("Authorization") or headers.get("authorization")
        if auth:
            scheme, _, token = str(auth).partition(" ")
            return token.strip() if scheme.lower() == "bearer" and token else str(auth).strip()
        direct = headers.get("X-Access-Token")
        if direct:
            return str(direct).strip()
    return None


class Channel:
    def __init__(
        self, 
        raw: Union[ClientConnection, ServerConnection], 
        mode: str, 
        url: str, 
        channel_id: int,
        *,
        role: str = "universal",
        self_id: Union[int, None] = None        
):
        self.raw = raw                 # websockets 的 ClientConnection / ServerConnection
        self.mode = mode               # "forward" | "reverse"
        self.url = url               # 正向=url，反向=客户端地址
        self.id = channel_id
        self.role = role
        self.self_id = self_id         # 机器人账号
        self.created_at = time.time()
        self.last_seen = time.time()   # 最近收到报文的时间（排障用）
        self._send_lock = asyncio.Lock()

    @property
    def remote(self) -> str:
        address = self.raw.remote_address
        if isinstance(address, tuple) and len(address) >= 2:
            return f"{address[0]}:{address[1]}"
        return self.url

    async def send_json(self, payload: Dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        async with self._send_lock:
            await self.raw.send(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        try:
            await self.raw.close(code, reason)
        except Exception:
            pass

class OneBotConnection:
    """SnowLuma(OneBot v11) 连接管理器(M4: 正向 WS + 动作调用)"""

    def __init__(self, config: SnowLumaConfig, *, event_queue_size: int = _EVENT_QUEUE_SIZE) -> None:
        self.config = config
        self.event_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=event_queue_size)

        self.self_id: Optional[int] = None
        self.login_info: Optional[Dict[str, Any]] = None
        self.version_info: Optional[Dict[str, Any]] = None
        self.message_format_detected: Optional[str] = None

        self._channels: Dict[int, Channel] = {}
        self._channel_seq = itertools.count(1)
        self._pending: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}
        self._tasks: Set["asyncio.Task[Any]"] = set()
        self._closing = False
        self._connected = asyncio.Event()
        self._probe_task: Optional["asyncio.Task[Any]"] = None
        self._http: Optional[httpx.AsyncClient] = None       # M5 才创建

    # ---------------------------------------------------------------- 生命周期
    async def start(self) -> None:
        self._closing = False
        # ① HTTP 客户端只在这里建一次
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.request_timeout),
            headers=self.config.auth_headers(self.config.http_token),
        )
        # ② 反向优先起（先能收，再谈发）
        if self.config.reverse_enabled:
            self._spawn(self._reverse_server_loop(), name="reverse-ws")
        if self.config.forward_enabled:
            self._spawn(self._forward_loop(), name="forward-ws")
        if not (self.config.forward_enabled or self.config.reverse_enabled):
            logger.warning("正向与反向 WebSocket 都没开，只能靠 HTTP 发送（收不到事件）")


    async def stop(self) -> None:
        """取消后台任务、关闭通道、唤醒所有等待者"""
        self._closing = True
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for channel in self._channels.values():
            await channel.close(1001, "HysialX shutting down")
        self._channels.clear()
        self._connected.clear()
        self._fail_pending(ConnectionUnavailable("连接已关闭"))

        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _spawn(self, coro: Awaitable[Any], name: Optional[str] = None) -> "asyncio.Task[Any]":
        """创建后台任务并登记，方便 stop() 统一取消"""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ---------------------------------------------------------------- 状态查询
    @property
    def connected(self) -> bool:
        return bool(self._channels)

    @property
    def channels(self) -> List[Channel]:
        return list(self._channels.values())

    @property
    def pending_actions(self) -> int:
        """在途动作数（排障与测试用）"""
        return len(self._pending)

    async def wait_until_connected(self, timeout: Optional[float] = None) -> bool:
        if self.connected:
            return True
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _outgoing_format(self) -> str:
        """发出去的 message 用哪种形态：配置写死 > 跟随对端 > 默认 array"""
        configured = (self.config.message_format or "auto").lower()
        if configured in ("array", "string"):
            return configured
        return self.message_format_detected or "array"

    def _pick_channel(self, preferred: Optional[str] = None) -> Optional[Channel]:
        """挑一条通道发动作；正向优先（反向是 M5 的事，这里先把顺序定好）"""
        if not self._channels:
            return None
        for mode in ([preferred] if preferred else []) + ["forward", "reverse"]:
            for channel in self._channels.values():
                if channel.mode == mode:
                    return channel
        return next(iter(self._channels.values()))

    # ---------------------------------------------------------------- 通道登记
    def _register(self, raw: Any, mode: str, url: str, **kwargs) -> Channel:
        channel = Channel(raw, mode, url, next(self._channel_seq), **kwargs)
        self._channels[channel.id] = channel
        self._connected.set()
        return channel

    def _unregister(self, channel: Channel) -> None:
        self._channels.pop(channel.id, None)
        if not self._channels:
            # 最后一条通道没了：所有在途请求立即失败，不要让调用方干等到超时
            self._connected.clear()
            self._fail_pending(ConnectionUnavailable("所有 WebSocket 通道都已断开"))

    def _fail_pending(self, exc: BaseException) -> None:
        for echo, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(exc)
            self._pending.pop(echo, None)

    # ------------------------------------------------------------------ 读循环
    async def _pump(self, channel: Channel) -> None:
        """一条通道上唯一的读循环；它只负责「投递」，不做任何业务"""
        try:
            async for raw in channel.raw:
                channel.last_seen = time.time()
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"收到无法解析的报文 ({channel.mode}): {str(raw)[:200]}")
                    continue
                if isinstance(payload, dict):
                    self._handle_payload(channel, payload)
        except ConnectionClosed:
            pass

    # ------------------------------------------------------------------ 分发
    def _handle_payload(self, channel: Channel, payload: Dict[str, Any]) -> None:
        echo = payload.get("echo")
        if echo is not None and echo in self._pending:
            future = self._pending.pop(echo)
            if not future.done():
                future.set_result(payload)
            return

        # 容错：极少数实现不回填 echo。只有「在途请求恰好 1 个」时才敢认领
        if echo is None and "post_type" not in payload and ("retcode" in payload or "status" in payload):
            if len(self._pending) == 1:
                only_echo, future = next(iter(self._pending.items()))
                self._pending.pop(only_echo)
                logger.debug("收到没有 echo 的动作应答，按唯一在途请求匹配")
                if not future.done():
                    future.set_result(payload)
                return

        post_type = payload.get("post_type")
        match post_type:
            case None:
                logger.debug(f"忽略无法识别的报文: {str(payload)[:200]}")
                return
            case "meta_event":
                self._handle_meta_event(payload)          # meta 不进事件队列
                return
            case "message" | "message_sent":
                detected = message_format_of(payload.get("message"))
                if detected and detected != self.message_format_detected:
                    self.message_format_detected = detected
                    logger.debug(f"检测到对端 messageFormat = {detected}")

        if self.self_id is None and (self_id := payload.get("self_id")):
            self.self_id = int(self_id)

        self._emit(payload)

    def _emit(self, payload: Dict[str, Any]) -> None:
        """入队；队列满时丢最旧的，别把读循环堵死（堵住会让心跳和应答全超时）"""
        try:
            self.event_queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                dropped = self.event_queue.get_nowait()
                logger.warning(f"事件队列已满，丢弃最旧事件: {dropped.get('post_type')}")
            except asyncio.QueueEmpty:
                pass
            try:
                self.event_queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.error("事件队列仍然写满，事件被丢弃")

    def _handle_meta_event(self, payload: Dict[str, Any]):
        meta_type = payload.get("meta_event_type")
        match meta_type:
            case "lifecycle":
                if payload.get("self_id"):
                    self.self_id = int(payload["self_id"])
                logger.opt(colors=True).success(
                    f"SnowLuma 上报生命周期事件 <y>{payload.get('sub_type')}</y>，"
                    f"当前机器人账号 <y>{self.self_id}</y>"
                )
                self._schedule_probe()
            case "heartbeat":
                status = payload.get("status") or {}
                logger.debug(
                    f"心跳: online={status.get('online')} good={status.get('good')} "
                    f"interval={payload.get('interval')}ms"
                )
            case _:
                logger.debug(f"收到 meta 事件: {meta_type}")

    # ------------------------------------------------------------------ 动作调用
    async def call_action(
        self,
        action: str,
        *,
        transport: Optional[str] = None,
        timeout: Optional[float] = None,
        **params
    ) -> Any:
        """调用一个 OneBot 动作，返回应答信封里的 data

        通道策略见 §5: 只有「完全没有 WS 通道」才退到 HTTP;
        WS 已发出但超时**绝不**回退，避免同一条消息发两遍
        """
        transport = (transport or self.config.api_transport or "auto").lower()
        timeout = self.config.request_timeout if timeout is None else timeout
        channel = self._pick_channel() if transport in ("auto", "ws") else None

        if channel is not None:
            try:
                return await self._call_ws(channel, action, params, timeout)
            except (ConnectionClosed, OSError) as exc:
                raise ConnectionUnavailable(f"动作 {action} 发送失败: {exc}") from exc
        if transport == "ws":
            raise ConnectionUnavailable("没有可用的 WebSocket 通道")
        return await self._call_http(action, params, timeout)

    async def _call_ws(
        self,
        channel: Channel,
        action: str,
        params: Dict[str, Any],
        timeout: float
    ) -> Any:
        loop = asyncio.get_running_loop()
        echo = uuid.uuid4().hex
        future: "asyncio.Future[Dict[str, Any]]" = loop.create_future()
        self._pending[echo] = future
        started = time.perf_counter()
        try:
            await channel.send_json({"action": action, "params": params, "echo": echo})
            payload = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectionUnavailable(f"动作 {action} 等待应答超时({timeout}s)") from exc
        finally:
            # 无论成功/超时/发送失败，都要把这一条从在途表里摘掉
            self._pending.pop(echo, None)
            if not future.done():
                future.cancel()      # 取消掉，避免 set_exception 之后没人取 → "never retrieved" 警告
        logger.debug(f"动作 {action} 完成，用时 {time.perf_counter() - started:.3f}s")
        return self._unwrap(action, payload)

    @staticmethod
    def _unwrap(action: str, payload: Any) -> Any:
        """校验应答信封: retcode == 0 才算成功(HTTP 200 也可能是业务失败)"""
        if not isinstance(payload, dict):
            raise ActionFailed(action, message=f"应答格式异常: {payload!r}")
        
        status = payload.get("status")
        retcode = payload.get("retcode")
        ok = retcode == 0 or (retcode is None and status in ("ok", "async", "accepted", None))
        if not ok:
            raise ActionFailed(
                action,
                status=status,
                retcode=retcode,
                message=str(payload.get("message") or ""),
                wording=str(payload.get("wording") or ""),
                data=payload.get("data")
            )

        return payload.get("data")

    async def _call_http(self, action: str, params: Dict[str, Any], timeout: float) -> Any:
        """HTTP 兜底 —— M5 实现(POST {http_base}{http_path}/{action}, Bearer 鉴权)"""
        if self._http is None:
            raise ConnectionUnavailable("HTTP 客户端未初始化(连接层还没 start())")
        try:
            response = await self._http.post(
                self.config.http_url(action), json=params, timeout=timeout
            )
        except httpx.HTTPError as exc:
            raise ConnectionUnavailable(f"HTTP 调用 {action} 失败: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            # 非 JSON（网关 502 / 空 body 等）：按 HTTP 状态报错
            raise ActionFailed(action, status=str(response.status_code),
                            retcode=response.status_code, message=response.text[:200]) from None
        return self._unwrap(action, payload)        # 复用 M4：retcode != 0 → ActionFailed

    # ------------------------------------------------------------------ 登录探测
    def _schedule_probe(self) -> None:
        """连接建立 / lifecycle 时拉一次登录信息；同一时刻只允许一个在途"""
        if self._probe_task is not None and not self._probe_task.done():
            return
        self._probe_task = self._spawn(self._probe_login_info(), name="login-probe")

    async def _probe_login_info(self) -> None:
        try:
            info = await self.call_action("get_login_info")
            self.login_info = info if isinstance(info, dict) else {}
            user_id = (self.login_info or {}).get("user_id")
            if user_id is not None:
                self.self_id = int(user_id)
            nickname = (self.login_info or {}).get("nickname", "")
            logger.opt(colors=True).success(
                f"Connected successfully! 当前机器人账号 <y>{self.self_id}</y>"
                + (f"({nickname})" if nickname else "")
            )
        except Exception as exc:
            logger.warning(f"获取登录信息失败: {exc}")

        try:
            version = await self.call_action("get_version_info")
            self.version_info = version if isinstance(version, dict) else {}
            if self.version_info:
                logger.info(
                    "协议端: {app} {ver} / OneBot {proto}".format(
                        app=self.version_info.get("app_name", "SnowLuma"),
                        ver=self.version_info.get("app_version", "?"),
                        proto=self.version_info.get("protocol_version", "v11"),
                    )
                )
        except Exception as exc:
            logger.debug(f"获取版本信息失败: {exc}")

        await self._apply_device_name()

    async def _apply_device_name(self) -> None:
        name = (self.config.device_name or "").strip()
        if not name:
            return
        try:
            await self.call_action("_set_model_show", model=name, model_show=name)
            logger.opt(colors=True).success(f"设置机型 <y>{name}</y> 成功!")
        except Exception as exc:
            logger.warning(f"设置机型 {name} 失败: {exc}")

    # ------------------------------------------------------------------ 发送消息
    async def send_message(
        self,
        message: MessageLike,
        *,
        message_type: Optional[str] = None,
        user_id: Optional[Union[str, int]] = None,
        group_id: Optional[Union[str, int]] = None,
        auto_escape: bool = False
    ) -> Dict[str, Any]:
        """调用 SnowLuma 的 send_msg(按群号/好友号自动路由)"""
        if message_type is None:
            message_type = "group" if group_id is not None else "private"

        params: Dict[str, Any] = {
            "message_type": message_type,
            # 关键：按对端 messageFormat 决定发段数组还是 CQ 字符串
            "message": message_to_payload(message, self._outgoing_format(), auto_escape=auto_escape),
            "auto_escape": auto_escape
        }
        if message_type == "group":
            if group_id is None:
                raise ValueError("群消息必须提供 group_id")
            params["group_id"] = _coerce_id(group_id)
        else:
            if user_id is None:
                raise ValueError("私聊消息必须提供 user_id")
            params["user_id"] = _coerce_id(user_id)

        data = await self.call_action("send_msg", **params)
        return data if isinstance(data, dict) else {}

    async def send_group_message(self, message: MessageLike, group_id: Union[int, str], **kwargs: Any) -> Dict[str, Any]:
        return await self.send_message(message, message_type="group", group_id=group_id, **kwargs)

    async def send_private_message(self, message: MessageLike, user_id: Union[int, str], **kwargs: Any) -> Dict[str, Any]:
        return await self.send_message(message, message_type="private", user_id=user_id, **kwargs)

    # ------------------------------------------------------------ 正向 WS 客户端
    async def _forward_loop(self) -> None:
        backoff = max(1.0, self.config.reconnect_interval)
        while not self._closing:
            uri = self.config.ws_uri()
            headers = self.config.auth_headers(self.config.forward_token)
            try:
                async with websockets.connect(
                    uri,
                    additional_headers=headers or None,
                    max_size=_MAX_MESSAGE_SIZE,
                    open_timeout=10,
                    ping_interval=_interval(self.config.ping_interval, 30.0),
                    ping_timeout=_interval(self.config.ping_timeout, 30.0),
                    close_timeout=5,
                    proxy=None
                ) as raw:
                    channel = self._register(raw, "forward", self.config.forward_url)
                    backoff = max(1.0, self.config.reconnect_interval)
                    logger.opt(colors=True).success(
                        f"已连接 SnowLuma 正向 WebSocket: <y>{self.config.ws_uri(mask=True)}</y>"
                    )
                    self._schedule_probe()
                    try:
                        await self._pump(channel)              # ← 缺的就是这两行
                    finally:
                        self._unregister(channel)
                        logger.warning("与 SnowLuma 的 WebSocket 连接已断开")
            except asyncio.CancelledError:
                raise
            except _CONNECTION_ERRORS as exc:
                logger.opt(colors=True).warning(
                    f"连接 SnowLuma 失败({type(exc).__name__}: {exc}), {backoff:.0f}s 后重试"
                )
            except Exception as exc:
                logger.exception(exc)

            if self._closing:
                break

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)                  # 1s → 2s → … → 60s 封顶

    # ------------------------------------------------------------ 反向 WS 服务端
    async def _reverse_server_loop(self) -> None:
        reverse = self.config.reverse
        retry = max(1.0, self.config.reconnect_interval)
        while not self._closing:
            try:
                # 必须用 async with（§3）；内部不要 await serve_forever()
                async with websockets.serve(
                    self._reverse_handler,
                    reverse.host,
                    reverse.port,
                    process_request=self._process_reverse_request,
                    max_size=_MAX_MESSAGE_SIZE,
                    ping_interval=_interval(self.config.ping_interval, 30.0),
                    ping_timeout=_interval(self.config.ping_timeout, 30.0),
                    close_timeout=5
                ):
                    retry = max(1.0, self.config.reconnect_interval)
                    logger.opt(colors=True).success(
                        f"反向 WebSocket 已监听 <y>ws://{reverse.host}:{reverse.port}{reverse.path}</y>"
                        "(等待 SnowLuma 的 wsClients 接入)"
                    )
                    await asyncio.Future()
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                logger.error(f"反向 WebSocket 监听 ws://{reverse.host}:{reverse.port} 失败: {exc}，{retry:.0f}s 后重试")
            except Exception as exc:
                logger.exception(exc)

            if self._closing:
                break
            await asyncio.sleep(retry)
            retry = min(retry * 2, 60.0)

    def _process_reverse_request(self, connection: ServerConnection, request: Request):
        """握手鉴权: SnowLuma 的 wsClients 带着 accessToken 连过来"""
        expected = self.config.reverse.access_token
        if not expected:
            return None             # 没配 token 就不校验（与 SnowLuma 默认一致）
        provided = _extract_token(request.path, request.headers)
        if provided and hmac.compare_digest(provided, expected):
            return None
        logger.warning(f"拒绝反向 WebSocket 连接(来自 {connection.remote_address}): access token 不匹配")
        return connection.respond(401, "Unauthorized\n")           # 回 401，客户端会拿到 InvalidStatus
    
    async def _reverse_handler(self, connection: ServerConnection) -> None:
        request = connection.request
        headers = request.headers if request is not None else {}
        role = str(headers.get("X-Client-Role") or "universal").lower()
        remote_id = headers.get("X-Self-ID")

        channel = self._register(connection, "reverse", str(remote_id) or "reverse", role=role, self_id=self.self_id)
        logger.opt(colors=True).success(
            f"SnowLuma 反向 WebSocket 已接入: <y>{channel.remote}</y>(role={role})"
        )
        self._schedule_probe()

        try:
            await self._pump(channel)
        finally:
            self._unregister(channel)
            logger.warning(f"反向 WebSocket 连接已断开: {channel.remote}")

class LocalEchoConnection:
    """离线调试用：所有动作只打印日志，不产生网络请求"""

    def __init__(self, self_id: int = 10000, nickname: str = "DebugBot",
                 message_format: str = "array") -> None:
        self.self_id = self_id
        self.nickname = nickname
        self.message_format_detected = message_format
        self.login_info = {"user_id": self_id, "nickname": nickname}
        self.connected = True
        self.calls: list[tuple[str, dict]] = []

    async def call_action(self, action, *, transport=None, timeout=None, **params):
        self.calls.append((action, params))
        logger.opt(colors=True).info(f"[调试] 动作 <y>{action}</y> 参数 {params}")
        return {"get_login_info": {"user_id": self.self_id, "nickname": self.nickname},
                "get_version_info": {"app_name": "SnowLuma(Debug)", "protocol_version": "v11"},
                "get_status": {"online": True, "good": True}}.get(action, {})

    async def send_message(self, message, *, message_type=None, user_id=None,
                           group_id=None, auto_escape=False):
        target = group_id if message_type == "group" else user_id
        logger.opt(colors=True).success(f"[调试] 发送到 {target}: {normalize_cq(message)}")
        return {"message_id": 0}

