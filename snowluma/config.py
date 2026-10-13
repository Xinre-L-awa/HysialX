"""
SnowLuma (OneBot v11) 连接配置：三层合并 + 配置目录自动发现。

优先级：内置默认值 < SnowLuma 目录发现 < HysialX 配置/环境变量。
约定："" / null / 0 一律表示「自动」，用户只维护 SnowLuma 一侧即可。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from log import logger
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit

from .exception import ConfigError

DEFAULT_CONFIG_PATH = "config/snowluma.json"
DEFAULT_WS_URL = "ws://127.0.0.1:3001/"
DEFAULT_HTTP_BASE = "http://127.0.0.1:3000"
DEFAULT_HTTP_PATH = "/"
DEFAULT_REVERSE_HOST = "0.0.0.0"
DEFAULT_REVERSE_PORT = 6700
DEFAULT_REVERSE_PATH = "/"

_WILDCARD_HOSTS = {"", "*", "0.0.0.0", "::", "[::]", "all"}
_MODES = {"forward", "reverse", "both"}
_TRANSPORTS = {"auto", "ws", "http"}
_FORMATS = {"auto", "array", "string"}

# ---------------------------------------------------------------- 模板（字段表）
# 首次运行时写到 config/snowluma.json，字段与设计文档 §5.2 一一对应
DEFAULT_CONFIG_TEMPLATE: Dict[str, Any] = {
    "_readme": [
        "HysialX 的 SnowLuma(OneBot v11) 连接配置。",
        "空字符串 / null / 0 表示「自动」：优先用 snowluma_dir 里发现的值，其次用内置默认值。",
        "snowluma_dir 指向 SnowLuma 安装目录（含 config/onebot.json 的那一层）。",
        "mode: forward(只主动连) / reverse(只收反向) / both。",
        "api_transport: auto(有 WS 走 WS，没有才走 HTTP) / ws / http。",
        "message_format: auto / array / string。",
    ],
    "snowluma_dir": "",
    "account": None,
    "mode": "both",
    "forward_url": "",
    "forward_token": "",
    "http_base": "",
    "http_path": "",
    "http_token": "",
    "reverse": {"enabled": True, "host": "", "port": None, "path": "", "access_token": ""},
    "message_format": "auto",
    "api_transport": "auto",
    "request_timeout": 10.0,
    "reconnect_interval": 5.0,
    "ping_interval": 30.0,
    "ping_timeout": 30.0,
    "event_workers": 4,
    "device_name": "",
}

# ------------------------------------------------------------------- 配置对象
@dataclass
class ReverseConfig:
    enabled: bool = True
    host: str = DEFAULT_REVERSE_HOST
    port: int = DEFAULT_REVERSE_PORT
    path: str = DEFAULT_REVERSE_PATH
    access_token: str = ""

@dataclass
class SnowLumaConfig:
    mode: str = "both"
    forward_url: str = DEFAULT_WS_URL
    forward_token: str = ""
    http_base: str = DEFAULT_HTTP_BASE
    http_path: str = DEFAULT_HTTP_PATH
    http_token: str = ""
    reverse: ReverseConfig = field(default_factory=ReverseConfig)
    message_format: str = "auto"
    api_transport: str = "auto"
    request_timeout: float = 10.0
    reconnect_interval: float = 5.0
    ping_interval: float = 30.0
    ping_timeout: float = 30.0
    event_workers: int = 4          # 最大事件并发处理数
    device_name: str = ""

    # 来源信息（只用于日志，不参与连接）
    snowluma_dir: str = ""
    account: Optional[int] = None
    config_path: Optional[str] = None
    source: str = "默认值"
    discovered_from: Optional[str] = None

    @property
    def forward_enabled(self) -> bool:
        return self.mode in ("forward", "both")

    @property
    def reverse_enabled(self) -> bool:
        return self.mode in ("reverse", "both") and self.reverse.enabled

    def ws_uri(self, mask: bool = False) -> str:
        """正向地址，token 以查询参数带上（SnowLuma 查询参数/Header 都支持）。"""
        if not self.forward_token:
            return self.forward_url
        sep = "&" if "?" in self.forward_url else "?"
        token = "***" if mask else quote(self.forward_token, safe="")
        return f"{self.forward_url}{sep}access_token={token}"

    def http_url(self, action: str) -> str:
        base = self.http_base.rstrip("/")
        path = self.http_path.strip("/")
        return f"{base}{'/' + path if path else ''}/{action.lstrip('/')}"

    def auth_headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def describe(self) -> str:
        """脱敏摘要，启动时打印一份，排障全靠它。"""
        mark = lambda v: "已配置" if v else "未配置"          # noqa: E731
        return "\n".join([
            f"配置来源: {self.source}",
            f"连接模式: {self.mode}（正向 {'开' if self.forward_enabled else '关'} / "
            f"反向 {'开' if self.reverse_enabled else '关'}）",
            f"正向 WebSocket: {self.ws_uri(mask=True)}（token: {mark(self.forward_token)}）",
            f"HTTP API: {self.http_base}{self.http_path}（token: {mark(self.http_token)}）",
            f"反向 WebSocket: ws://{self.reverse.host}:{self.reverse.port}{self.reverse.path}"
            f"（token: {mark(self.reverse.access_token)}）",
            f"事件消息格式: {self.message_format}，动作通道: {self.api_transport}",
        ])

# --------------------------------------------------------------------- 小工具
def _is_blank(value: Any) -> bool:
    """空串 / None / 0 都算「自动」。"""
    return value is None or (isinstance(value, str) and not value.strip()) or value == 0

def _as_int(value: Any, default: Optional[int]) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default

def local_host(host: Optional[str]) -> str:
    """监听用的通配地址 → 本机可直连地址（只用于我们主动连的方向）。"""
    if host is None or str(host).strip().lower() in _WILDCARD_HOSTS:
        return "127.0.0.1"
    return str(host).strip()

def normalize_path(path: Optional[str]) -> str:
    if not path:
        return "/"
    path = str(path).strip()
    return path if path.startswith("/") else "/" + path

# ------------------------------------------------------------------ 目录发现
def _resolve_config_dir(dirpath: Path) -> Optional[Path]:
    for candidate in (dirpath / "config", dirpath):
        if candidate.is_dir() and any(candidate.glob("onebot*.json")):
            return candidate

    return None

def _pick_onebot_file(config_dir: Path, account: Optional[int] = None) -> Optional[Path]:
    if account is not None:
        picked = config_dir / f"onebot_{account}.json"
        if picked.is_file():
            return picked

    account_files = sorted(p for p in config_dir.glob("onebot_*.json") if p.is_file())
    if len(account_files) == 1:
        return account_files[0]
    default_file = config_dir / "onebot.json"
    if default_file.is_file():
        return default_file
    return account_files[0] if account_files else None

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}

def _networks_of(raw: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """兼容新旧两种 SnowLuma 配置结构。"""
    networks = raw.get("networks") if isinstance(raw.get("networks"), dict) else {}

    def pick(*keys: str) -> List[Dict[str, Any]]:
        for key in keys:
            value = networks.get(key) if key in networks else raw.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return []

    return {
        "httpServers": pick("httpServers"),
        "wsServers": pick("wsServers"),
        "wsClients": pick("wsClients", "reverseWs"),
        "httpClients": pick("httpClients", "httpPostEndpoints"),
    }

def _enabled(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [x for x in items if _as_bool(x.get("enabled", True), True)]

def discover_from_dir(dirpath: str, account: Optional[int] = None) -> Dict[str, Any]:
    """从 SnowLuma 安装目录解析连接参数；解析不到就返回 {}"""
    base = Path(dirpath).expanduser()
    if not base.is_dir():
        return {}
    config_dir = _resolve_config_dir(base)
    if config_dir is None:
        return {}

    global_file = config_dir / "onebot.json"
    chosen = _pick_onebot_file(config_dir, account)
    raw: Dict[str, Any] = {}
    used: Optional[Path] = None
    if chosen is not None and chosen != global_file:
        candidate = _read_json(chosen)
        if candidate.get("networks") or candidate.get("wsServers") or candidate.get("httpServers"):
            raw, used = candidate, chosen
    if not raw and global_file.is_file():
        candidate = _read_json(global_file)
        if candidate.get("networks") or candidate.get("wsServers") or candidate.get("httpServers"):
            raw, used = candidate, global_file
    if not raw:
        return {}

    found: Dict[str, Any] = {
        "snowluma_dir": str(base),
        "discovered_from": str(used or config_dir)
    }
    if account is None and used is not None and used.name.startswith("onebot_"):
        found["account"] = _as_int(used.stem.split("_", 1)[1], None)

    networks = _networks_of(raw)
    ws_servers = _enabled(networks["wsServers"])
    if ws_servers:
        server = ws_servers[0]
        port = _as_int(server.get("port"), 3001) or 3001
        found["forward_url"] = (
            f"ws://{local_host(server.get('host', '127.0.0.1'))}:{port}"
            f"{normalize_path(server.get('path', '/'))}"
        )
        found["forward_token"] = str(server.get("accessToken") or '')
        if fmt := server.get("messageFormat"):
            found["message_format"] = str(fmt).lower()

    http_servers = _enabled(networks["httpServers"])
    if http_servers:
        server = http_servers[0]
        port = _as_int(server.get("port"), 3000) or 3000
        found["http_base"] = f"http://{local_host(server.get('host', '127.0.0.1'))}:{port}"
        found["http_path"] = normalize_path(server.get("path", '/'))
        found["http_token"] = str(server.get("accessToken") or "")

    ws_clients = _enabled(networks["wsClients"])
    if ws_clients:
        url = str(ws_clients[0].get("url") or '')
        if url:
            parsed = urlsplit(url)
            host = (parsed.hostname or '').lower()
            found["reverse_host"] = host if host and host not in _WILDCARD_HOSTS else DEFAULT_REVERSE_HOST
            found["reverse_port"] = parsed.port or DEFAULT_REVERSE_PORT
            found["reverse_path"] = normalize_path(parsed.path or '/')
        found["reverse_token"] = str(ws_clients[0].get("accessToken") or '')
        found["reverse_enabled"] = True

    return found

# ------------------------------------------------------------------ 合并配置
def _apply_discovery(cfg: SnowLumaConfig, found: Dict[str, Any]) -> None:
    if found.get("discovered_from"):
        cfg.discovered_from = found["discovered_from"]
        cfg.source = f"SnowLuma 配置 {found['discovered_from']}"
    cfg.forward_url = found.get("forward_url") or cfg.forward_url
    cfg.forward_token = found.get("forward_token") or cfg.forward_token
    cfg.http_base = found.get("http_base") or cfg.http_base
    cfg.http_path = found.get("http_path") or cfg.http_path
    cfg.http_token = found.get("http_token") or cfg.http_token
    if found.get("message_format") in ("array", "string"):
        cfg.message_format = found["message_format"]
    if found.get("reverse_port"):
        cfg.reverse.port = int(found["reverse_port"])
    if found.get("reverse_host"):
        cfg.reverse.host = str(found["reverse_host"])
    if found.get("reverse_path"):
        cfg.reverse.path = normalize_path(found["reverse_path"])
    if found.get("reverse_enabled"):
        cfg.reverse.enabled = True
    cfg.reverse.access_token = found.get("reverse_token") or cfg.reverse.access_token
    if found.get("account") is not None:
        cfg.account = found["account"]

def _apply_raw(cfg: SnowLumaConfig, raw: Dict[str, Any]) -> None:
    """HysialX 配置文件里的显式值；空值跳过（= 跟随上游）。"""
    if raw.get("mode") in _MODES:
        cfg.mode = str(raw["mode"]).lower()
    if not _is_blank(raw.get("forward_url")):
        cfg.forward_url = str(raw["forward_url"]).strip()
    if not _is_blank(raw.get("forward_token")):
        cfg.forward_token = str(raw["forward_token"]).strip()
    if not _is_blank(raw.get("http_base")):
        cfg.http_base = str(raw["http_base"]).strip().rstrip("/")
    if not _is_blank(raw.get("http_path")):
        cfg.http_path = normalize_path(raw["http_path"])
    if not _is_blank(raw.get("http_token")):
        cfg.http_token = str(raw["http_token"]).strip()
    if str(raw.get("message_format", "")).lower() in _FORMATS:
        cfg.message_format = str(raw["message_format"]).lower()
    if str(raw.get("api_transport", "")).lower() in _TRANSPORTS:
        cfg.api_transport = str(raw["api_transport"]).lower()
    if not _is_blank(raw.get("request_timeout")):
        cfg.request_timeout = _as_float(raw["request_timeout"], cfg.request_timeout)
    if not _is_blank(raw.get("reconnect_interval")):
        cfg.reconnect_interval = _as_float(raw["reconnect_interval"], cfg.reconnect_interval)
    if not _is_blank(raw.get("ping_interval")):
        cfg.ping_interval = _as_float(raw["ping_interval"], cfg.ping_interval)
    if not _is_blank(raw.get("ping_timeout")):
        cfg.ping_timeout = _as_float(raw["ping_timeout"], cfg.ping_timeout)
    if not _is_blank(raw.get("event_workers")):
        cfg.event_workers = max(1, _as_int(raw["event_workers"], cfg.event_workers) or 1)
    if not _is_blank(raw.get("device_name")):
        cfg.device_name = str(raw["device_name"]).strip()
    if not _is_blank(raw.get("account")):
        cfg.account = _as_int(raw["account"], cfg.account)

    reverse = raw.get("reverse")
    if isinstance(reverse, dict):
        if reverse.get("enabled") is not None:
            cfg.reverse.enabled = _as_bool(reverse["enabled"], cfg.reverse.enabled)
        if not _is_blank(reverse.get("host")):
            cfg.reverse.host = str(reverse["host"]).strip()
        if not _is_blank(reverse.get("port")):
            cfg.reverse.port = _as_int(reverse["port"], cfg.reverse.port) or cfg.reverse.port
        if not _is_blank(reverse.get("path")):
            cfg.reverse.path = normalize_path(reverse["path"])
        if not _is_blank(reverse.get("access_token")):
            cfg.reverse.access_token = str(reverse["access_token"]).strip()

def _apply_env(cfg: SnowLumaConfig, env: Optional[Dict[str, str]] = None) -> None:
    env = os.environ if env is None else env
    mapping = {
        "SNOWLUMA_FORWARD_WS": "forward_url", "SNOWLUMA_WS_URL": "forward_url",
        "SNOWLUMA_FORWARD_TOKEN": "forward_token", "SNOWLUMA_WS_TOKEN": "forward_token",
        "SNOWLUMA_HTTP_BASE": "http_base", "SNOWLUMA_HTTP_PATH": "http_path",
        "SNOWLUMA_HTTP_TOKEN": "http_token",
        "SNOWLUMA_MESSAGE_FORMAT": "message_format",
        "SNOWLUMA_API_TRANSPORT": "api_transport",
        "SNOWLUMA_MODE": "mode",
        "SNOWLUMA_ACCOUNT": "account",
        "SNOWLUMA_DEVICE_NAME": "device_name",
    }
    raw = {key: env[var] for var, key in mapping.items() if env.get(var)}
    if any(env.get(k) for k in ("SNOWLUMA_REVERSE_HOST", "SNOWLUMA_REVERSE_PORT", "SNOWLUMA_REVERSE_TOKEN")):
        raw["reverse"] = {
            "host": env.get("SNOWLUMA_REVERSE_HOST"),
            "port": env.get("SNOWLUMA_REVERSE_PORT"),
            "access_token": env.get("SNOWLUMA_REVERSE_TOKEN"),
        }
    if raw:
        _apply_raw(cfg, raw)
    if env.get("SNOWLUMA_DIR"):
        cfg.snowluma_dir = env["SNOWLUMA_DIR"]

def write_default_config(path: str = DEFAULT_CONFIG_PATH, overwrite: bool = False) -> bool:
    target = Path(path)
    if target.exists() and not overwrite:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(DEFAULT_CONFIG_TEMPLATE, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    return True

def _candidate_dirs() -> List[Path]:
    here = Path.cwd()
    names = ("SnowLuma", "snowluma")
    return [p / n for p in (here, here.parent) for n in names]

def load_config(path: Optional[str] = DEFAULT_CONFIG_PATH, *, create: bool = True, use_env: bool = True) -> SnowLumaConfig:
    cfg = SnowLumaConfig()
    raw: Dict[str, Any] = {}
    if path:
        target = Path(path)
        if not target.exists():
            if create:
                write_default_config(str(target))
            else:
                raise ConfigError.missing(target)
        if target.is_file():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # raise ConfigError(f"配置文件 {target} 解析失败: {exc}") from exc
                raise ConfigError.bad_json(target, exc) from exc   # ← 用工厂
            if not isinstance(raw, dict):
                # raise ConfigError(f"配置文件 {target} 顶层必须是 JSON 对象") from exc
                raise ConfigError.bad_field(target, "<顶层>", type(raw).__name__, "JSON 对象")
            cfg.config_path = str(target)

    # 1) 定位 SnowLuma 目录：配置文件 > 环境变量 > 自动探测
    if not _is_blank(dir := raw.get("snowluma_dir")):
        cfg.snowluma_dir = str(dir).strip()
    if use_env and (dir := os.environ.get("SNOWLUMA_DIR")):
        cfg.snowluma_dir = dir
    if not cfg.snowluma_dir:
        for candidate in _candidate_dirs():
            if _resolve_config_dir(candidate) is not None:
                cfg.snowluma_dir = str(candidate)
                cfg.source = f"自动发现 {candidate}"
                break

    # 2) 发现 → 3) 显式覆盖 → 4) 环境变量
    if cfg.snowluma_dir:
        try:
            found = discover_from_dir(cfg.snowluma_dir, _as_int(raw.get("account"), None))
        except Exception as exc:
            logger.warning(f"解析 SnowLuma 配置失败，改用默认值: {exc}")
            found = {}
        _apply_discovery(cfg, found)
    if raw:
        _apply_raw(cfg, raw)
    if use_env:
        _apply_env(cfg)

    # 5) 兜底：补齐「自动」字段并做枚举校验
    cfg.forward_url = cfg.forward_url or DEFAULT_WS_URL
    cfg.http_base = cfg.http_base or DEFAULT_HTTP_BASE
    cfg.http_path = cfg.http_path or DEFAULT_HTTP_PATH
    cfg.reverse.host = cfg.reverse.host or DEFAULT_REVERSE_HOST
    cfg.reverse.port = cfg.reverse.port or DEFAULT_REVERSE_PORT
    cfg.reverse.path = cfg.reverse.path or DEFAULT_REVERSE_PATH
    cfg.mode = cfg.mode if cfg.mode in _MODES else "both"
    cfg.api_transport = cfg.api_transport if cfg.api_transport in _TRANSPORTS else "auto"
    cfg.message_format = cfg.message_format if cfg.message_format in _FORMATS else "auto"
    if not cfg.source.startswith(("SnowLuma", "自动发现")):
        cfg.source = ", ".join(filter(None, [f"配置文件 {cfg.config_path}" if cfg.config_path else "默认值"]))
    return cfg
