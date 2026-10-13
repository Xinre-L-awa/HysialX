# tests/test_responders.py —— 响应器分发矩阵（不联网、不加载真实插件）
"""覆盖这次修掉的分发语义：

- `@机器人 命令`（at 段 + 空格 + 命令）必须命中 on_command
- on_at 必须真的能触发（此前因为粗筛用纯文本判 `[CQ:at` 而 100% 失效）
- on_regex / custom / on_waiting 链路
- 通知池提前 break 后，下一条通知不能漏掉池首的响应器（池游标错位）
- 嵌套 WaitingFuncMeta 的 name/__str__ 不能炸
"""

import asyncio

import pytest

import main as main_module
from api import (
    add_child_func, custom, get_func_pool, get_notice_func_pool,
    get_request_func_pool, get_waiting_task_pool, on_at, on_command,
    on_notice, on_regex, on_waiting, RunInLoop, set_connection,
)
from api.utils import CreateOnWaitingTask
from plugins.manager import WaitingFuncMeta
from snowluma import LocalEchoConnection

SELF_ID = 999
GROUP_ID = 859874709
USER_ID = 169699201


@pytest.fixture
def pools():
    """清空并登记结束后还原：这些池子是进程级全局量，用例之间会互相污染"""
    func_pools = [get_func_pool(), get_notice_func_pool(), get_request_func_pool()]
    backups = [list(p.funcs) for p in func_pools]
    waiting = list(get_waiting_task_pool())
    for pool in func_pools:
        pool.funcs.clear()
    get_waiting_task_pool().pop_tasks(waiting)
    set_connection(LocalEchoConnection(self_id=SELF_ID, nickname="ResponderTest"))
    try:
        yield
    finally:
        for pool, backup in zip(func_pools, backups):
            pool.funcs[:] = backup
        left = list(get_waiting_task_pool())
        if left:
            get_waiting_task_pool().pop_tasks(left)
        set_connection(None)
        main_module.refresh_funcs()


def _payload(text: str, *, with_at: bool = False) -> dict:
    segments = ([{"type": "at", "data": {"qq": str(SELF_ID)}}] if with_at else []) + \
               [{"type": "text", "data": {"text": text}}]
    return {
        "post_type": "message", "message_type": "group", "sub_type": "normal",
        "time": 0, "self_id": SELF_ID, "message_id": 1,
        "group_id": GROUP_ID, "user_id": USER_ID,
        "message": segments,
        "raw_message": (f"[CQ:at,qq={SELF_ID}]" if with_at else "") + text,
        "sender": {"user_id": USER_ID, "nickname": "雨弈", "card": "群名片", "role": "owner"},
    }


def _feed(payload: dict) -> None:
    asyncio.run(main_module.handle_event(payload))


def test_plain_command_hits(pools):
    fired = []

    @on_command("菜单")
    async def handler(bot, event):
        fired.append(event.get_plain_text)

    main_module.refresh_funcs()
    _feed(_payload("菜单"))
    assert fired == ["菜单"]


def test_at_prefixed_command_hits(pools):
    """QQ 里 @机器人 后面通常带一个空格，命令匹配必须能穿透它"""
    fired = []

    @on_command("菜单")
    async def handler(bot, event):
        fired.append(1)

    main_module.refresh_funcs()
    _feed(_payload(" 菜单", with_at=True))
    assert fired, "@机器人 菜单（带空格）没有命中 on_command"


def test_on_at_fires_only_when_mentioned(pools):
    fired = []

    @on_at()
    async def handler(bot, event):
        fired.append(1)

    main_module.refresh_funcs()
    _feed(_payload("你好", with_at=True))
    assert fired, "on_at 响应器没有被触发（粗筛补候选的逻辑失效了）"

    fired.clear()
    _feed(_payload("你好", with_at=False))
    assert not fired, "没有 @机器人 时 on_at 不该触发"


def test_on_regex_and_custom(pools):
    seen = {}

    @on_regex(r"echo(.*)")
    async def echo(bot, event):
        seen["echo"] = event.get_message          # set_message(match.group(1))

    @custom(lambda text: "查到我了" if text.startswith(" ") else "")
    async def matcher(bot, event):
        seen["custom"] = event.get_plain_text

    main_module.refresh_funcs()
    _feed(_payload("echo hi"))
    assert seen.get("echo", "").strip() == "hi", seen      # group(1) 含前导空格，插件一般自己 strip

    _feed(_payload(" 随便什么"))                   # custom 保留前导空格语义
    assert seen.get("custom") == " 随便什么", seen


def test_on_waiting_child_chain(pools):
    """父响应器建任务 → 下一条消息触发子函数 → 任务被消费"""
    calls = []

    @on_waiting("input")
    async def parent(bot, event):
        calls.append("parent")
        await bot.input_value(group_id=event.get_group_id)

    async def child(bot, event):
        calls.append(("child", event.input_value))

    add_child_func(parent, child)
    main_module.refresh_funcs()

    _feed(_payload("input"))
    assert calls == ["parent"], calls
    # 框架自动入池 + 处理器里的 bot.input_value() 是同一个子函数，必须只留一个任务
    assert len(list(get_waiting_task_pool())) == 1, "等待任务被重复注册（子函数会触发两次）"

    _feed(_payload("hello"))
    assert calls == ["parent", ("child", "hello")], calls
    assert list(get_waiting_task_pool()) == [], "等待任务执行后应被移除"

    _feed(_payload("hello"))                     # 任务已消费，不该再触发（池子没有残留死任务）
    assert calls == ["parent", ("child", "hello")], f"池子里有残留任务: {calls}"


def test_notice_pool_cursor_not_skipped(pools):
    """一条通知里 block=True 提前 break 后，下一条通知仍须从池首开始遍历"""
    fired = []

    @on_notice(4, block=True)                     # 4 = group_increase
    async def first(bot, event):
        fired.append("first")

    @on_notice(4)
    async def second(bot, event):
        fired.append("second")

    notice = {
        "post_type": "notice", "notice_type": "group_increase", "sub_type": "approve",
        "time": 0, "self_id": SELF_ID, "group_id": GROUP_ID, "user_id": 88888,
    }
    _feed(notice)
    _feed(notice)
    # add_func 是 insert(0)，所以池内顺序是 [second, first]；first 命中后 break。
    # 池游标错位时第二次遍历会整体空转（两个都不触发）。
    assert fired == ["second", "first", "second", "first"], f"通知池游标错位: {fired}"


def test_nested_waiting_meta_str_is_safe(pools):
    """bot.input_value 路径会包出嵌套的 WaitingFuncMeta，str(task) 不能炸"""
    @on_waiting("input")
    async def parent(bot, event): ...

    async def child(bot, event): ...

    add_child_func(parent, child)
    main_module.refresh_funcs()
    meta = next(f for f in get_func_pool() if f.match_pattern == "on_waiting")

    CreateOnWaitingTask(meta.child_func, USER_ID, GROUP_ID)      # 与 Bot.input_value 内部同一路径
    task = list(get_waiting_task_pool())[0]
    assert isinstance(task.func, WaitingFuncMeta)
    assert "child" in str(task)                                  # 旧实现这里 AttributeError


def test_pool_iterator_is_independent():
    """池子迭代器必须是独立的：消费者 break 不能把游标留给下一次遍历"""
    pool = get_notice_func_pool()
    backup = list(pool.funcs)
    pool.funcs.clear()
    try:
        for i in range(3):
            pool.add_func(_DummyMeta(i))
        for _ in pool:
            break                                                # 模拟命中 block=True 提前退出
        assert [m.tag for m in pool] == [2, 1, 0], "第二次遍历漏掉了池首元素"
    finally:
        pool.funcs[:] = backup


class _DummyMeta:
    def __init__(self, tag):
        self.tag = tag
        self.name = f"dummy{tag}"


def test_runinloop_before_responders(pools):
    """D2：RunInLoop 钩子先于响应器执行（统计钩子不能被响应器抢先）"""
    order = []

    @RunInLoop
    async def hook(bot, event):
        order.append("loop")

    @on_command("顺序")
    async def handler(bot, event):
        order.append("cmd")

    main_module.refresh_funcs()
    _feed(_payload("顺序"))
    assert order == ["loop", "cmd"], order


def test_sync_handler_does_not_break(pools):
    """D3：同步插件函数不会被 await（§0.1 的回归）"""
    ran = []

    @on_command("同步")
    def sync_handler(bot, event):          # 注意：同步 def
        ran.append(event.get_plain_text)

    main_module.refresh_funcs()
    _feed(_payload("同步"))
    assert ran == ["同步"], ran


def test_waiting_task_with_none_response_method(pools):
    """D5：response_method 传 None 时不能炸，且默认按 ["input"] 处理"""
    calls = []

    @on_waiting("提问")
    async def parent(bot, event): ...

    async def child(bot, event):
        calls.append(event.input_value)

    add_child_func(parent, child)
    main_module.refresh_funcs()
    meta = next(f for f in get_func_pool() if f.match_pattern == "on_waiting")

    # 与 bot.input_value(type_=None) 同一条路径：type_ 为 None 时必须落回 ["input"]，
    # 否则 task.response_method 是 None → wevent.input_value 不会被赋值
    CreateOnWaitingTask(meta.child_func, USER_ID, GROUP_ID, None)
    _feed(_payload("答案"))
    assert calls == ["答案"], calls


def test_unknown_notice_type_is_tolerated(pools):
    """D6：协议端没给 notice_type 时：不炸；只有"不限类型"的处理器会被调用"""
    wildcard, typed = [], []

    @on_notice(None)                       # 不限类型
    async def any_notice(bot, event):
        wildcard.append(1)

    @on_notice(4)                          # 只收 group_increase
    async def only_increase(bot, event):
        typed.append(1)

    _feed({"post_type": "notice", "time": 0, "self_id": SELF_ID,
           "group_id": GROUP_ID, "user_id": 88888})          # 没有 notice_type
    assert wildcard == [1], wildcard
    assert typed == [], typed

    _feed({"post_type": "notice", "notice_type": "group_increase", "time": 0,
           "self_id": SELF_ID, "group_id": GROUP_ID, "user_id": 88888})
    assert wildcard == [1, 1], wildcard
    assert typed == [1], typed
