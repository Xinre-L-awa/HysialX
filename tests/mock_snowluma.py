"""
tests/mock_snowluma.py —— 极简 SnowLuma(OneBot v11) 协议端替身

只依赖标准库 + websockets; 不对接 QQ, 也不 import 被测代码
既能当库用(`async with MockSnowLuma() as mock:`), 也能直接跑自检：
    python tests/mock_snowluma.py
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.client import ClientConnection      # 反向模式用
from websockets.asyncio.connection import Connection        # _pump 的公共标注
from websockets.asyncio.server import ServerConnection      # 正向服务端
from websockets.http11 import Request


HTTP_PORT     = 18080
WS_PORT       = 18081
REVERSE_PORT  = 18082
WS_TOKEN      = "testtoken"
HTTP_TOKEN    = "httptoken"
REVERSE_TOKEN = "revtoken"
SELF_ID       = 999
NICKNAME      = "Mock"

# ------------------------------------------------------------------ 信封
def envelope(
    request: Dict[str, Any],
    *,
    data: Any = None,
    status: str = "ok",
    retcode: int = 0,
    message: str = "",
    wording: str = ""
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": status,
        "retcode": retcode,
        "data": data,
        "message": message,
        "wording": wording,
    }
    if request.get("echo") is not None:
        payload["echo"] = request["echo"]
    return payload

def token_of(path: str, headers) -> Optional[str]:
    query = parse_qs(urlsplit(path).query)
    if at := query.get("access_token"):
        return at[0]
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth:
        prefix, _, value = str(auth).partition(' ')
        return value.strip() if prefix.lower() == "bearer" else str(auth).strip()

# ------------------------------------------------------------------ mock 本体
class MockSnowLuma:
    def __init__(
        self,
        ws_port: int = WS_PORT,
        http_port: int = HTTP_PORT,
        ws_token: str = WS_TOKEN,
        http_token: str = HTTP_TOKEN
    ):
        self.ws_port = ws_port
        self.http_port = http_port
        self.ws_token = ws_token
        self.http_token = http_token

        self.actions: List[dict] = []          # WS 收到的动作请求（含 params/echo）
        self.http_actions: list[dict] = []     # HTTP 收到的请求（含 action/params/auth/path）
        self.clients: List[ServerConnection] = []                # 活着的 WS 连接
        self.handlers: dict[str, Callable[[dict], dict]] = {}   # 动作名 -> 自定义应答
        self.slow_actions: dict[str, float] = {}                # 动作名 -> 延迟秒数
        self.auto_lifecycle = True

        self._ws_server = None
        self._http_server: Optional[ThreadingHTTPServer] = None

    async def start(self) -> "MockSnowLuma":
        self._ws_server = await websockets.serve(
            self._ws_handler,
            "127.0.0.1",
            self.ws_port,
            process_request=self._check_ws_token,
            max_size=None
        )
        self._start_http()
        ws_hint = f"?access_token={self.ws_token}" if self.ws_token else "（不校验 token）"
        http_hint = f"Bearer {self.http_token}" if self.http_token else "（不校验 token）"
        print(f"[mock] WS   ws://127.0.0.1:{self.ws_port}/{ws_hint}")
        print(f"[mock] HTTP http://127.0.0.1:{self.http_port}/  POST /{{动作名}}  鉴权: {http_hint}")
        return self

    async def stop(self) -> None:
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    def _check_ws_token(self, connection: ServerConnection, request: Request):
        if not self.ws_token:
            return None
        if token_of(request.path, request.headers) == self.ws_token:
            return None
        return connection.respond(401, "Unauthorized\n")

    async def _ws_handler(self, connection: ServerConnection) -> None:
        self.clients.append(connection)
        print(f"[mock] 客户端接入: {connection.remote_address}")
        try:
            if self.auto_lifecycle:
                await connection.send(json.dumps(meta_lifecycle("connect"), ensure_ascii=False))
            async for raw in connection:
                request: Dict = json.loads(raw)
                self.actions.append(request)
                action = request.get("action")
                if action == "no_reply":                 # 故障注入：完全不回
                    continue

                delay = self.slow_actions.get(action or "")
                if delay:
                    asyncio.create_task(self.reply_later(connection, request, delay))
                    continue

                await connection.send(json.dumps(self.reply_to(request), ensure_ascii=False))
        except ConnectionClosed:
            pass
        finally:
            if connection in self.clients:
                self.clients.remove(connection)
            print("[mock] 客户端断开")

    async def reply_later(self, connection, request: Dict, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await connection.send(json.dumps(self.reply_to(request), ensure_ascii=False))
        except ConnectionClosed:
            pass

    def reply_to(self, request: Dict) -> Dict:
        """动作分派表：实现够用即可，其余一律 1404"""
        action = request.get("action")
        params = request.get("params") or {}

        if action in self.handlers:
            return self.handlers[action](request)
        match action:
            case "get_login_info":
                return envelope(request, data={"user_id": SELF_ID, "nickname": NICKNAME})
            case "get_version_info":
                return envelope(request, data={"app_name": "SnowLuma", "app_version": "mock-1.0",
                                               "protocol_version": "v11"})
            case "get_status":
                return envelope(request, data={"online": True, "good": True, "time": 0})
            case "get_group_info":
                return envelope(request, data={"group_id": params.get("group_id"), "group_name": "测试群"})
            case "get_group_list":
                return envelope(request, data=[{"group_id": 123456, "group_name": "测试群"}])
            case "_set_model_show":
                return envelope(request, data=None)
            case "send_msg":
                if params.get("group_id") == 999:        # 故障注入：模拟风控失败
                    return envelope(request, status="failed", retcode=100,
                                    message="risk", wording="账号可能被风控")
                return envelope(request, data={"message_id": 1})
            case "echo_less":                    # 故障注入：不回填 echo
                response = envelope(request, data={"message_id": 1})
                response.pop("echo", None)
                return response
            case "fail_test":                    # 故障注入：业务失败
                return envelope(request, status="failed", retcode=100,
                                message="bad", wording="请求失败")
        return envelope(request, status="failed", retcode=1404, message="unknown action")

    # -------------------------------------------------------- 事件推送
    async def push(self, payload: Dict[str, Any]) -> int:
        sent = 0
        for conn in list(self.clients):
            try:
                await conn.send(json.dumps(payload, ensure_ascii=False))
                sent += 1
            except ConnectionClosed:
                pass
        return sent

    def actions_named(self, name: str) -> List[Dict[str, Any]]:
        return [a for a in self.actions if a.get("action") == name]

    def last_action(self, name: str) -> Optional[Dict[str, Any]]:
        found = self.actions_named(name)
        return found[-1] if found else None

    # -------------------------------------------------------- HTTP API
    def _start_http(self) -> None:
        outer = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b"{}"
                try:
                    params = json.loads(body)
                except json.JSONDecodeError:
                    params = {}
                action = self.path.strip('/').split('?')[0]
                auth = self.headers.get("Authorization", "")
                outer.http_actions.append({"action": action, "params": params, "auth": auth, "path": self.path})

                if outer.http_token and auth != f"Bearer {outer.http_token}":
                    payload = json.dumps({"status": "failed", "retcode": 1403, "data": None,
                                          "message": "token 校验失败", "wording": ""}).encode()
                    self._write(401, payload)
                    return
                
                payload = json.dumps(outer.reply_to({"action": action, "params": params}),
                                     ensure_ascii=False).encode()
                self._write(200, payload)

            def _write(self, code: int, payload: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                return

        self._http_server = ThreadingHTTPServer(("127.0.0.1", self.http_port), Handler)
        self._http_server.daemon_threads = True
        threading.Thread(target=self._http_server.serve_forever, daemon=True).start()

# ------------------------------------------------------------------ 事件工厂
def _seg(seg_type: str, **data: Any) -> dict:
    return {"type": seg_type, "data": data}

def group_message(
    text: str,
    *,
    group_id: int = 123456,
    user_id: int = 169699201,
    nickname: str = "雨弈",
    card: str = "群名片",
    message_format: str = "array",
    message_id: int = 12345,
    segments: Optional[list[dict]] = None,
) -> dict:
    segs = segments if segments is not None else [_seg("text", text=text)]
    message: Any = segs if message_format == "array" else text
    return {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "time": int(time.time()),
        "self_id": SELF_ID,
        "message_id": message_id,
        "group_id": group_id,
        "user_id": user_id,
        "message": message,
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": user_id, "nickname": nickname, "card": card, "role": "owner"},
        "anonymous": None,
    }


def private_message(text: str, *, user_id: int = 169699201, nickname: str = "雨弈") -> dict:
    """注意：私聊事件没有 group_id，这一条会被用来验证「不炸」。"""
    return {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "time": int(time.time()),
        "self_id": SELF_ID,
        "message_id": 54321,
        "user_id": user_id,
        "message": [_seg("text", text=text)],
        "raw_message": text,
        "sender": {"user_id": user_id, "nickname": nickname},
    }


def notice(notice_type: str, *, group_id: int = 123456, user_id: int = 88888,
           sub_type: Optional[str] = "approve", **extra: Any) -> dict:
    return {
        "post_type": "notice",
        "notice_type": notice_type,
        "sub_type": sub_type,
        "time": int(time.time()),
        "self_id": SELF_ID,
        "group_id": group_id,
        "user_id": user_id,
        **extra,
    }


def group_request(comment: str = "求进群", *, group_id: int = 123456,
                  user_id: int = 77777, flag: str = "flag-1") -> dict:
    return {
        "post_type": "request",
        "request_type": "group",
        "sub_type": "add",
        "time": int(time.time()),
        "self_id": SELF_ID,
        "group_id": group_id,
        "user_id": user_id,
        "comment": comment,
        "flag": flag,
    }


def meta_lifecycle(sub_type: str = "connect") -> dict:
    return {"post_type": "meta_event", "meta_event_type": "lifecycle",
            "sub_type": sub_type, "time": int(time.time()), "self_id": SELF_ID}


def meta_heartbeat(interval: int = 5000) -> dict:
    return {"post_type": "meta_event", "meta_event_type": "heartbeat",
            "time": int(time.time()), "self_id": SELF_ID, "interval": interval,
            "status": {"online": True, "good": True}}

# ------------------------------------------------------------------ 用例运行器
class CaseRunner:
    def __init__(self):
        self.results: List[Tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, bool(ok), detail))
        print(("  [PASS]  " if ok else "  [FAIL]  ") + name 
              + (f"  -> {detail}" if detail and not ok else ""))

    def finish(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print(f"\n==== 共 {len(self.results)} 项，失败 {len(failed)} 项 ====")
        for name in failed:
            print(f"  FAILED: {name}")
        return 1 if failed else 0

# ------------------------------------------------------------------ 自检
async def _self_test() -> int:
    """只验证 mock 自己是否符合 OneBot v11 的收发约定，不涉及被测代码"""
    import httpx
    from websockets.exceptions import InvalidStatus

    runner = CaseRunner()
    async with MockSnowLuma() as mock:
        try:
            async with websockets.connect(f"ws://127.0.0.1:{mock.ws_port}/?access_token=wrong"):
                runner.check("错误 token 被拒绝", False, "竟然连上了")
        except InvalidStatus as exc:
            runner.check("错误 token 被拒绝(401)", exc.response.status_code == 401, str(exc))

        uri = f"ws://127.0.0.1:{mock.ws_port}/?access_token={mock.ws_token}"
        async with websockets.connect(uri, max_size=None) as client:
            hello = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("连接后收到 lifecycle",
                         hello.get("meta_event_type") == "lifecycle", str(hello))
            await client.send(json.dumps({"action": "get_login_info", "params": {}, "echo": "e1"}))
            reply = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("动作应答带 echo 且 retcode=0",
                         reply.get("echo") == "e1" and reply.get("retcode") == 0
                         and reply["data"]["user_id"] == SELF_ID, str(reply))

            await client.send(json.dumps({"action": "fail_test", "params": {}, "echo": "e2"}))
            reply = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("业务失败信封 retcode!=0", reply.get("retcode") == 100, str(reply))

            await client.send(json.dumps({"action": "echo_less", "params": {}, "echo": "e3"}))
            reply = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("echo_less 不含 echo 字段", "echo" not in reply, str(reply))

            await client.send(json.dumps({"action": "no_reply", "params": {}, "echo": "e4"}))
            try:
                await asyncio.wait_for(client.recv(), 0.4)
                runner.check("no_reply 不回应答", False, "竟然回了")
            except asyncio.TimeoutError:
                runner.check("no_reply 不回应答（客户端超时）", True)

            await mock.push(group_message("ping"))
            pushed = json.loads(await asyncio.wait_for(client.recv(), 2))
            runner.check("能推送事件到客户端",
                         pushed.get("post_type") == "message"
                         and pushed["message"][0]["data"]["text"] == "ping", str(pushed))

        runner.check("动作被记录", bool(mock.actions_named("get_login_info")),
                     str(len(mock.actions)))

        async with httpx.AsyncClient(timeout=5) as http:
            ok = await http.post(
                f"http://127.0.0.1:{mock.http_port}/send_msg",
                json={"message_type": "group", "group_id": 1, "message": "hi"},
                headers={"Authorization": f"Bearer {mock.http_token}"}
            )
            runner.check("HTTP 正确 token 返回信封",
                         ok.status_code == 200 and ok.json().get("retcode") == 0
                         and ok.json()["data"]["message_id"] == 1, ok.text)
            bad = await http.post(f"http://127.0.0.1:{mock.http_port}/send_msg", json={})
            runner.check("HTTP 缺少 token 返回 401", bad.status_code == 401, str(bad.status_code))
            runner.check("HTTP 请求体被记录为 params",
                         mock.http_actions[0]["params"]["group_id"] == 1,
                         json.dumps(mock.http_actions[:1], ensure_ascii=False))

    return runner.finish()

if __name__ == "__main__":
    print(f"自测结束，退出码为 {asyncio.run(_self_test())}")
