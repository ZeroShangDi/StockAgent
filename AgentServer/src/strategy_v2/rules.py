"""
Strategy V2 task creation rules.

Keep this file aligned with docs/STRATEGY_V2_TASK_RULES.md and the frontend
task creation dictionary.
"""

from __future__ import annotations

from typing import Any, Iterable, List

from common.models.strategy_v2 import (
    StrategyV2ActionType,
    StrategyV2CreateTaskRequest,
    StrategyV2DictionaryItem,
    StrategyV2RuleDictionary,
    StrategyV2ScheduleMode,
    StrategyV2SceneType,
    StrategyV2TargetScopeType,
)


SCENE_TARGETS: dict[StrategyV2SceneType, set[StrategyV2TargetScopeType]] = {
    StrategyV2SceneType.SCAN: {
        StrategyV2TargetScopeType.WATCHLIST,
        StrategyV2TargetScopeType.TRADE_ACCOUNT,
        StrategyV2TargetScopeType.STOCK_POOL,
        StrategyV2TargetScopeType.ALL_MARKET,
    },
    StrategyV2SceneType.LISTEN: {
        StrategyV2TargetScopeType.WATCHLIST,
        StrategyV2TargetScopeType.TRADE_ACCOUNT,
        StrategyV2TargetScopeType.STOCK_POOL,
        StrategyV2TargetScopeType.ALL_MARKET,
        StrategyV2TargetScopeType.CUSTOM_STOCK_LIST,
        StrategyV2TargetScopeType.INDEX,
    },
    StrategyV2SceneType.BACKTEST: {
        StrategyV2TargetScopeType.ALL_MARKET,
    },
    StrategyV2SceneType.SIM_TRADE: {
        StrategyV2TargetScopeType.ALL_MARKET,
    },
}

SCENE_SCHEDULES: dict[StrategyV2SceneType, set[StrategyV2ScheduleMode]] = {
    StrategyV2SceneType.SCAN: {
        StrategyV2ScheduleMode.ONCE,
        StrategyV2ScheduleMode.SCHEDULED,
        StrategyV2ScheduleMode.MANUAL,
    },
    StrategyV2SceneType.LISTEN: {
        StrategyV2ScheduleMode.SCHEDULED,
        StrategyV2ScheduleMode.MANUAL,
    },
    StrategyV2SceneType.BACKTEST: {
        StrategyV2ScheduleMode.ONCE,
        StrategyV2ScheduleMode.MANUAL,
    },
    StrategyV2SceneType.SIM_TRADE: {
        StrategyV2ScheduleMode.SCHEDULED,
        StrategyV2ScheduleMode.MANUAL,
    },
}

STOCK_SCOPES = {
    StrategyV2TargetScopeType.WATCHLIST,
    StrategyV2TargetScopeType.TRADE_ACCOUNT,
    StrategyV2TargetScopeType.STOCK_POOL,
    StrategyV2TargetScopeType.ALL_MARKET,
    StrategyV2TargetScopeType.CUSTOM_STOCK_LIST,
}

BUILTIN_STRATEGY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "strategy_key": "ma5_buy",
        "name": "5日线低吸",
        "description": "股价回落到均线附近后，等待重新企稳并输出正向信号，适合做候选入池与低吸观察。",
        "impl_type": "builtin_code",
        "supported_scenes": ["scan", "listen", "backtest", "sim_trade"],
        "supports_state": True,
        "version": 2,
        "tags": ["均线", "低吸", "企稳"],
        "param_schema": [
            {"key": "ma_period", "label": "均线周期", "type": "number", "default": 5, "description": "用于计算企稳参考的均线周期。"},
            {"key": "touch_range", "label": "接触阈值(%)", "type": "float", "default": 2, "description": "价格接近均线的允许偏差范围。"},
            {"key": "stable_periods", "label": "企稳轮数", "type": "number", "default": 2, "description": "连续站稳的最小轮数。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "回落后重新站稳", "summary": "适合进入候选池，后续在股池中继续筛。"},
            {"signal": 0, "title": "仍在震荡观察", "summary": "条件未充分，不触发动作。"},
            {"signal": -1, "title": "跌破均线失效", "summary": "观察条件被破坏，可移出当前观察路径。"},
        ],
    },
    {
        "strategy_key": "price_change",
        "name": "涨跌幅阈值",
        "description": "监控单只股票或一个范围在盘中达到指定涨跌幅阈值后的触发情况。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen", "scan", "backtest"],
        "supports_state": True,
        "version": 2,
        "tags": ["阈值", "异动", "盘中"],
        "param_schema": [
            {
                "key": "direction",
                "label": "方向",
                "type": "select",
                "default": "both",
                "description": "决定监控上涨、下跌还是双向异动。",
                "options": [
                    {"label": "双向", "value": "both"},
                    {"label": "向上", "value": "up"},
                    {"label": "向下", "value": "down"},
                ],
            },
            {"key": "threshold", "label": "阈值(%)", "type": "float", "default": 5, "description": "触发信号的涨跌幅阈值。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "向上突破阈值", "summary": "适合发通知，或推动从信号池流转到确认池。"},
            {"signal": 0, "title": "未触发", "summary": "没有明显异动，维持观察。"},
            {"signal": -1, "title": "向下触发阈值", "summary": "可用于风险提醒或候选剔除。"},
        ],
    },
    {
        "strategy_key": "fixed_stop_loss",
        "name": "固定止损",
        "description": "以参考价和止损比例为核心，适合持仓组或模拟交易任务做风险提醒。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen", "sim_trade", "backtest"],
        "supports_state": True,
        "version": 2,
        "tags": ["止损", "持仓", "风控"],
        "param_schema": [
            {"key": "reference_price", "label": "参考价", "type": "float", "default": 10.2, "description": "止损线的基准价格。"},
            {"key": "stop_loss_pct", "label": "止损比例(%)", "type": "float", "default": 8, "description": "参考价向下的止损幅度。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "止损触发", "summary": "任务层通常会执行通知或模拟卖出。"},
            {"signal": 0, "title": "持仓正常", "summary": "还未触发止损。"},
            {"signal": -1, "title": "跌势恶化", "summary": "可作为更强的负向风险信号。"},
        ],
    },
    {
        "strategy_key": "breadth_pulse",
        "name": "市场涨跌比脉冲",
        "description": "观察指数与涨跌家数结构，适合做市场情绪监听和训练时段筛选。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen", "scan"],
        "supports_state": False,
        "version": 1,
        "tags": ["情绪", "市场", "宽度"],
        "param_schema": [
            {"key": "up_down_ratio", "label": "涨跌比阈值", "type": "float", "default": 2.2, "description": "市场偏强所需的涨跌家数比。"},
            {"key": "limit_up_threshold", "label": "涨停家数", "type": "number", "default": 55, "description": "辅助确认市场强度。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "市场宽度强化", "summary": "适合推动强势模式池的自动加仓观察。"},
            {"signal": 0, "title": "市场中性", "summary": "等待进一步确认。"},
            {"signal": -1, "title": "市场退潮", "summary": "用于提醒缩容或降低进攻性。"},
        ],
    },
]

BUILTIN_STRATEGY_SCENES: dict[str, set[StrategyV2SceneType]] = {
    item["strategy_key"]: {StrategyV2SceneType(scene) for scene in item["supported_scenes"]}
    for item in BUILTIN_STRATEGY_DEFINITIONS
}


def get_strategy_definition(strategy_key: str) -> dict[str, Any] | None:
    for item in BUILTIN_STRATEGY_DEFINITIONS:
        if item["strategy_key"] == strategy_key:
            return item
    return None


def _supports_scene(items: Iterable[StrategyV2SceneType]) -> List[StrategyV2SceneType]:
    return list(items)


def build_rule_dictionary() -> StrategyV2RuleDictionary:
    return StrategyV2RuleDictionary(
        scenes=[
            StrategyV2DictionaryItem(code="scan", label="选股", description="筛选股票候选。"),
            StrategyV2DictionaryItem(code="listen", label="监听", description="持续监听目标并触发动作。"),
            StrategyV2DictionaryItem(code="backtest", label="回测", description="历史区间策略验证。"),
            StrategyV2DictionaryItem(code="sim_trade", label="模拟", description="准实盘模拟交易。"),
        ],
        target_scopes=[
            StrategyV2DictionaryItem(code="watchlist", label="自选股", description="当前用户自选股。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.LISTEN])),
            StrategyV2DictionaryItem(code="trade_account", label="持仓股/交易账户", description="从交割单分组推导当前持仓。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.LISTEN])),
            StrategyV2DictionaryItem(code="stock_pool", label="股池分组", description="选择某个股池。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.LISTEN])),
            StrategyV2DictionaryItem(code="all_market", label="全市场排除 ST", description="全市场并默认排除 ST。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.LISTEN, StrategyV2SceneType.BACKTEST, StrategyV2SceneType.SIM_TRADE])),
            StrategyV2DictionaryItem(code="custom_stock_list", label="自定义股票列表", description="当前任务内维护的股票列表。", supported_scenes=_supports_scene([StrategyV2SceneType.LISTEN])),
            StrategyV2DictionaryItem(code="index", label="指数", description="上证、深证、创业板等指数。", supported_scenes=_supports_scene([StrategyV2SceneType.LISTEN])),
            StrategyV2DictionaryItem(code="event", label="事件", description="预留，本期不开发。", disabled=True),
        ],
        schedules=[
            StrategyV2DictionaryItem(code="once", label="一次性运行", description="选股或回测一次性执行。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.BACKTEST])),
            StrategyV2DictionaryItem(code="scheduled", label="定时运行", description="按预设时间点或轮询频率执行。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.LISTEN, StrategyV2SceneType.SIM_TRADE])),
            StrategyV2DictionaryItem(code="manual", label="手动运行", description="只保存任务，由用户手动触发。", supported_scenes=_supports_scene([StrategyV2SceneType.SCAN, StrategyV2SceneType.LISTEN, StrategyV2SceneType.BACKTEST, StrategyV2SceneType.SIM_TRADE])),
        ],
        actions=[
            StrategyV2DictionaryItem(code="notify", label="通知", description="仅监听任务可用。", supported_scenes=_supports_scene([StrategyV2SceneType.LISTEN])),
            StrategyV2DictionaryItem(code="add_to_pool", label="加入股池", description="股票范围可用。"),
            StrategyV2DictionaryItem(code="pool_transition", label="股池流转", description="目标范围为股池分组时可用。"),
            StrategyV2DictionaryItem(code="temp_list", label="临时清单", description="一次性运行时可用。"),
            StrategyV2DictionaryItem(code="paper_trade", label="模拟成交", description="回测一次性生成最终交割单，模拟每日更新。", supported_scenes=_supports_scene([StrategyV2SceneType.BACKTEST, StrategyV2SceneType.SIM_TRADE])),
        ],
    )


def validate_task_config(body: StrategyV2CreateTaskRequest) -> list[str]:
    errors: list[str] = []
    scene = body.scene_type
    scope = body.target_scope.scope_type
    schedule_mode = body.schedule.mode
    strategy_scenes = BUILTIN_STRATEGY_SCENES.get(body.strategy_key)

    if strategy_scenes is not None and scene not in strategy_scenes:
        errors.append("当前策略不支持所选场景")

    if scope == StrategyV2TargetScopeType.EVENT:
        errors.append("事件范围本期只保留，不支持创建任务")

    if scope not in SCENE_TARGETS.get(scene, set()):
        errors.append("当前场景不支持所选目标范围")

    if schedule_mode not in SCENE_SCHEDULES.get(scene, set()):
        errors.append("当前场景不支持所选调度方式")

    if scene in {StrategyV2SceneType.BACKTEST, StrategyV2SceneType.SIM_TRADE} and not body.target_scope.params.get("trade_review_group_id"):
        errors.append("回测/模拟任务必须选择或创建交割单账户")

    if scope == StrategyV2TargetScopeType.CUSTOM_STOCK_LIST and not body.target_scope.ts_codes:
        errors.append("自定义股票列表不能为空")

    for action in body.actions:
        if not action.trigger_signals:
            errors.append("每个动作至少需要一个策略返回值")
            continue

        if action.action_type == StrategyV2ActionType.NOTIFY and scene != StrategyV2SceneType.LISTEN:
            errors.append("通知动作仅支持监听场景")
        elif action.action_type == StrategyV2ActionType.ADD_TO_POOL and scope not in STOCK_SCOPES:
            errors.append("加入股池动作仅支持股票范围")
        elif action.action_type == StrategyV2ActionType.POOL_TRANSITION and scope != StrategyV2TargetScopeType.STOCK_POOL:
            errors.append("股池流转动作仅支持股池分组范围")
        elif action.action_type == StrategyV2ActionType.TEMP_LIST and schedule_mode != StrategyV2ScheduleMode.ONCE:
            errors.append("临时清单动作仅支持一次性运行")
        elif action.action_type == StrategyV2ActionType.PAPER_TRADE and scene not in {StrategyV2SceneType.BACKTEST, StrategyV2SceneType.SIM_TRADE}:
            errors.append("模拟成交动作仅支持回测或模拟场景")

    return errors
