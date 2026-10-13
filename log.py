import sys
from pathlib import Path
from loguru import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Record


def default_filter(record: "Record"):
    """默认的日志过滤器，根据 `config.log_level` 配置改变日志等级。"""
    log_level = record["extra"].get("log_level", "INFO")
    levelno = logger.level(log_level).no if isinstance(log_level, str) else log_level
    return record["level"].no >= levelno


default_format: str = (
    "<g>{time:YYYY-MM-DD HH:mm:ss}</g> "
    "[<lvl>{level}</lvl>] "
    "<c><u>HysialX</u></c> | "
    # "<c>{function}:{line}</c>| "
    "{message}"
)
"""默认日志格式"""

logger.remove()
logger_id = logger.add(
    sys.stdout,
    level=0,
    diagnose=False,
    filter=default_filter,
    format=default_format
)

# 文件 sink 必须用**绝对路径**：相对路径 "./logs/..." 是按 cwd 解析的，
# 一旦某个插件在 import 期 chdir（历史上 plugins/t 就这么干过），就会在 plugins/ 下
# 造出一个 plugins/logs/，还会被 load_plugins 当成插件目录去 import。
_LOG_DIR = Path(__file__).resolve().parent / "logs"
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(_LOG_DIR / "HysialLog.log", rotation="114.514 KB", encoding="utf-8")
except OSError:                      # 只读部署等场景：写不了文件也还能用 stdout
    logger.warning(f"无法创建日志目录 {_LOG_DIR}，本进程只输出到 stdout")
