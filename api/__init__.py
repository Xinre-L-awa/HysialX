from .bot import Bot as Bot
from .event import Event as Event

from .utils import At as At
from .utils import ImageSegment as ImageSegment
from .utils import MessageSegment as MessageSegment
from .utils import set_device as set_device
from .utils import AnalyseCQCode as AnalyseCQCode
from .utils import getExpectedFuncs as getExpectedFuncs

from .on import custom as custom
from .on import RunInLoop as RunInLoop
from .on import on_regex as on_regex
from .on import on_command as on_command
from .on import on_keyword as on_keyword
from .on import on_startup as on_startup
from .on import get_func_pool as get_func_pool
from .on import get_plugin_pool as get_plugin_pool
from .on import get_waiting_pool as get_waiting_pool

from .exception import FinishException as FinishException

DEFAULT_PLUGINS_DATA_PATH = "./DataForXPlugin"
