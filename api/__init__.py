from .bot import Bot as Bot
from .event import SenderInfo as SenderInfo
from .event import NoticeEvent as NoticeEvent
from .event import MessageEvent as MessageEvent
from .event import RequestEvent as RequestEvent
from .event import WaitingEvent as WaitingEvent
from .event import GroupMessageEvent as GroupMessageEvent
from .event import PrivateMessageEvent as PrivateMessageEvent

from .on import on_at as on_at
from .on import custom as custom
from .on import RunInLoop as RunInLoop
from .on import on_regex as on_regex
from .on import on_notice as on_notice
from .on import on_request as on_request
from .on import on_command as on_command
from .on import on_keyword as on_keyword
from .on import on_startup as on_startup
from .on import on_waiting as on_waiting
from .on import on_scheduled as on_scheduled

from .on import add_child_func as add_child_func
from .on import get_func_pool as get_func_pool
from .on import get_plugin_pool as get_plugin_pool
from .on import get_notice_func_pool as get_notice_func_pool
from .on import get_request_func_pool as get_request_func_pool
from .on import get_waiting_task_pool as get_waiting_task_pool
from .on import get_scheduled_task_pool as get_scheduled_task_pool

from .utils import At as At
from .utils import AtAll as AtAll
from .utils import Text as Text
from .utils import Reply as Reply
from .utils import Message as Message
from .utils import FaceSegment as FaceSegment
from .utils import FileSegment as FileSegment
from .utils import VideoSegment as VideoSegment
from .utils import RecordSegment as RecordSegment

from .utils import shutdown as shutdown
from .utils import is_shutdown_requested as is_shutdown_requested
from .utils import run_func as run_func
from .utils import set_device as set_device
from .utils import to_shutdown as to_shutdown
from .utils import ImageSegment as ImageSegment
from .utils import AnalyseCQCode as AnalyseCQCode
from .utils import await_run_func as await_run_func
from .utils import get_connection as get_connection
from .utils import set_connection as set_connection
from .utils import require_connection as require_connection
from .utils import getExpectedFuncs as getExpectedFuncs
from .utils import func_accepts_event as func_accepts_event

from .exception import FinishException as FinishException

from snowluma.segment import MessageSegment as MessageSegment      # 段数组路径也是官方 API

DEFAULT_PLUGINS_DATA_PATH = "./DataForXPlugin"
