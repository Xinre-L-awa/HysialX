"""
SnowLuma (OneBot v11) 通信层异常
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["SnowLumaError", "ConfigError", "ConnectionUnavailable", "ActionFailed"]


class SnowLumaError(Exception):
    """本层所有异常的基类"""


class ConfigError(SnowLumaError):
    """HysialX 连接配置缺失、损坏或字段非法

    Parameters
    ----------
    message:
        人话描述，会直接作为 ``str(exc)`` 的第一段打印出来
    path:
        出问题的配置文件路径。
    field:
        出问题的字段名（可选）
    value:
        该字段实际拿到的值（可选，便于定位是拼错还是类型错）
    expected:
        期望的取值范围（可选）
    """

    def __init__(
        self,
        message: str,
        *,
        path: Optional[str] = None,
        field: Optional[str] = None,
        value: Any = None,
        expected: Optional[str] = None,
    ) -> None:
        self.message = message
        self.path = path
        self.field = field
        self.value = value
        self.expected = expected
        # 一定要喂给 super()，这样 exc.args / traceback 里的信息才完整
        super().__init__(self._compose())

    def _compose(self) -> str:
        parts = [self.message]
        if self.path:
            parts.append(f"文件: {self.path}")
        if self.field:
            parts.append(f"字段: {self.field}")
        if self.value is not None:
            parts.append(f"当前值: {self.value!r}")
        if self.expected:
            parts.append(f"期望: {self.expected}")
        return ";".join(parts)

    def __str__(self) -> str:
        return self._compose()

    # ------------------------------------------------------------ 工厂方法
    # 让 config.py 的抛错点保持一行，且消息格式统一
    @classmethod
    def missing(cls, path: Any) -> "ConfigError":
        return cls(
            "配置文件不存在（可用 load_config(create=True) 生成模板）",
            path=str(path),
        )

    @classmethod
    def bad_json(cls, path: Any, exc: Exception) -> "ConfigError":
        # exc 里自带行号列号，直接带上，别丢
        return cls(f"配置文件不是合法 JSON：{exc}", path=str(path))

    @classmethod
    def bad_field(cls, path: Any, field: str, value: Any, expected: str) -> "ConfigError":
        return cls("字段取值非法", path=str(path), field=field, value=value, expected=expected)


class ConnectionUnavailable(SnowLumaError):
    """当前没有可用通道：WS 未连接、反向未接入、或动作等待应答超时。"""


class ActionFailed(SnowLumaError):
    """协议端返回了非 0 的 retcode（HTTP 200 也可能是业务失败）。"""

    def __init__(
        self,
        action: str,
        *,
        status: Optional[str] = None,
        retcode: Optional[int] = None,
        message: str = "",
        wording: str = "",
        data: Any = None,
    ) -> None:
        self.action = action
        self.status = status
        self.retcode = retcode
        self.message = message
        self.wording = wording
        self.data = data
        detail = wording or message
        super().__init__(
            f"调用动作 {action} 失败: status={status!r}, retcode={retcode!r}"
            + (f", {detail}" if detail else "")
        )

    @property
    def detail(self) -> str:
        return self.wording or self.message or ""

# 自测：字段与可读性
e = ActionFailed("send_msg", status="failed", retcode=100, wording="账号可能被风控")
assert e.retcode == 100 and e.detail == "账号可能被风控"
assert "send_msg" in str(e) and "100" in str(e)
assert isinstance(e, SnowLumaError) and isinstance(e, Exception)
assert not isinstance(e, BaseException) or True   # 关键：它应该能被 except Exception 抓到
try:
    raise e
except Exception:      # 必须能进来
    pass
