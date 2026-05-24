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

DIRECTION_OPTIONS = [
    {"label": "双向", "value": "both"},
    {"label": "向上", "value": "up"},
    {"label": "向下", "value": "down"},
]

INDEX_OPTIONS = [
    {"label": "上证指数", "value": "000001.SH"},
    {"label": "深证成指", "value": "399001.SZ"},
    {"label": "创业板指", "value": "399006.SZ"},
]

BUILTIN_STRATEGY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "strategy_key": "one_line_stock_picker",
        "name": "一句话选股",
        "description": "输入自然语言选股条件，复用原一句话选股服务生成候选列表；策略逐股匹配候选代码，命中返回 1，未命中返回 0。",
        "impl_type": "builtin_code",
        "supported_scenes": ["scan", "listen"],
        "supports_state": False,
        "version": 1,
        "tags": ["AI选股", "自然语言", "候选池"],
        "param_schema": [
            {
                "key": "query_text",
                "label": "选股语句",
                "type": "string",
                "default": "",
                "required": True,
                "description": "传给一句话选股服务的自然语言条件，例如“近三个月放量突破年线且排除 ST”。",
            },
            {
                "key": "cache_ttl_days",
                "label": "缓存天数",
                "type": "number",
                "default": 1,
                "description": "同一用户、同一选股语句在缓存期内复用候选列表，避免全市场逐股匹配时重复调用接口。",
            },
        ],
        "sample_outputs": [
            {"signal": 1, "title": "命中一句话选股结果", "summary": "股票代码出现在接口返回候选列表中，可进入股池或生成临时清单。"},
            {"signal": 0, "title": "未命中候选列表", "summary": "股票代码不在当日缓存结果中，不触发动作。"},
            {"signal": -1, "title": "查询不可用", "summary": "文本参数为空或接口异常时由运行器记录失败，不进入正常动作链。"},
        ],
    },
    {
        "strategy_key": "double_cannon",
        "name": "双响炮",
        "description": "近一个月内出现两根涨幅超阈值的大阳线，第二根收盘价高于第一根；中间调整不跌破第一根最低价，且第二根距离最新交易日较近。",
        "impl_type": "builtin_code",
        "supported_scenes": ["scan", "listen", "backtest", "sim_trade"],
        "supports_state": False,
        "version": 1,
        "tags": ["形态", "双响炮", "强势"],
        "param_schema": [
            {"key": "lookback_days", "label": "回看交易日", "type": "number", "default": 22, "description": "用于寻找两根大阳线的最近交易日数量，默认约一个月。"},
            {"key": "min_bull_pct", "label": "大阳涨幅阈值(%)", "type": "float", "default": 5, "description": "单根阳线涨幅达到该阈值才视为有效大阳线。"},
            {"key": "max_second_age_days", "label": "第二炮距今天数", "type": "number", "default": 5, "description": "第二根大阳线距离最新交易日不能超过该交易日数。"},
            {"key": "require_second_volume_gt_first", "label": "第二炮放量", "type": "boolean", "default": False, "description": "启用后要求第二根大阳线成交量大于第一根。"},
            {"key": "require_bullish_ma", "label": "均线多头排列", "type": "boolean", "default": False, "description": "启用后要求最新交易日均线满足短期 > 中期 > 长期。"},
            {"key": "ma_short", "label": "短期均线", "type": "number", "default": 5, "description": "均线多头排列中的短期均线周期。"},
            {"key": "ma_mid", "label": "中期均线", "type": "number", "default": 10, "description": "均线多头排列中的中期均线周期。"},
            {"key": "ma_long", "label": "长期均线", "type": "number", "default": 20, "description": "均线多头排列中的长期均线周期。"},
            {"key": "require_pullback_shrink_volume", "label": "调整缩量", "type": "boolean", "default": False, "description": "启用后要求两根大阳线之间的平均成交量小于两根大阳线均量。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "双响炮形态成立", "summary": "可进入候选池、临时清单或监听后续确认。"},
            {"signal": 0, "title": "形态未完整成立", "summary": "未找到有效两根大阳线，或可选过滤条件未满足。"},
            {"signal": -1, "title": "形态结构破坏", "summary": "两根大阳线之间存在收盘价跌破第一根最低价的 K 线。"},
        ],
    },
    {
        "strategy_key": "turtle_trading",
        "name": "海龟通道突破",
        "description": "简化版海龟交易法：以前 N 日唐奇安通道突破作为买入信号，跌破前 M 日退出通道作为卖出/风险信号，用于测试完整交易方法在 Strategy V2 中的单策略闭环。",
        "impl_type": "builtin_code",
        "supported_scenes": ["scan", "listen", "backtest", "sim_trade"],
        "supports_state": False,
        "version": 1,
        "tags": ["海龟", "趋势跟踪", "通道突破"],
        "param_schema": [
            {"key": "entry_window", "label": "入场通道周期", "type": "number", "default": 20, "description": "价格突破最近 N 个交易日高点时输出买入信号。"},
            {"key": "exit_window", "label": "退出通道周期", "type": "number", "default": 10, "description": "价格跌破最近 M 个交易日低点时输出卖出/风险信号。"},
            {"key": "use_close_confirmation", "label": "收盘价确认", "type": "boolean", "default": True, "description": "启用后以收盘价突破/跌破确认；关闭后以最高价/最低价触发。"},
            {"key": "atr_period", "label": "ATR 周期", "type": "number", "default": 20, "description": "用于计算波动率解释与可选过滤。"},
            {"key": "min_atr_pct", "label": "最小 ATR 波动率(%)", "type": "float", "default": 0, "description": "大于 0 时，突破信号需要 ATR/收盘价不低于该比例。"},
            {"key": "max_atr_pct", "label": "最大 ATR 波动率(%)", "type": "float", "default": 0, "description": "大于 0 时，突破信号需要 ATR/收盘价不高于该比例。"},
            {"key": "require_volume_confirm", "label": "成交量确认", "type": "boolean", "default": False, "description": "启用后，突破当日成交量需要达到均量倍数。"},
            {"key": "volume_window", "label": "成交量均量周期", "type": "number", "default": 20, "description": "计算成交量确认时使用的均量周期。"},
            {"key": "volume_multiplier", "label": "成交量确认倍数", "type": "float", "default": 1.2, "description": "启用成交量确认时，最新成交量需大于均量乘以该倍数。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "突破入场通道", "summary": "价格突破前 N 日高点，可加入候选池、通知或模拟买入。"},
            {"signal": 0, "title": "通道内震荡", "summary": "未突破入场通道，也未跌破退出通道。"},
            {"signal": -1, "title": "跌破退出通道", "summary": "价格跌破前 M 日低点，可作为卖出、止损或剔除信号。"},
        ],
    },
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
                "options": DIRECTION_OPTIONS,
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
        "strategy_key": "market_index_alert",
        "name": "指数指标预警",
        "description": "迁移自市场监听：围绕指数涨跌幅、涨跌家数、涨跌停家数与北向资金变化输出市场风险或情绪信号。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen"],
        "supports_state": True,
        "version": 1,
        "tags": ["指数", "市场", "预警"],
        "param_schema": [
            {
                "key": "index_code",
                "label": "参考指数",
                "type": "select",
                "default": "000001.SH",
                "description": "用于指数涨跌幅监听的参考指数。",
                "options": INDEX_OPTIONS,
            },
            {"key": "index_rise_enabled", "label": "启用指数上涨提醒", "type": "boolean", "default": True, "description": "是否监听指数上涨阈值。"},
            {"key": "index_rise_threshold", "label": "指数上涨阈值(%)", "type": "float", "default": 1.5, "description": "指数涨幅达到该值时输出正向信号。"},
            {"key": "index_fall_enabled", "label": "启用指数下跌提醒", "type": "boolean", "default": True, "description": "是否监听指数下跌阈值。"},
            {"key": "index_fall_threshold", "label": "指数下跌阈值(%)", "type": "float", "default": 1.5, "description": "指数跌幅达到该值时输出负向信号。"},
            {"key": "up_count_enabled", "label": "启用上涨家数提醒", "type": "boolean", "default": False, "description": "是否监听全市场上涨家数。"},
            {"key": "up_count_threshold", "label": "上涨家数阈值", "type": "number", "default": 3000, "description": "上涨家数达到该值时输出市场偏强信号。"},
            {"key": "down_count_enabled", "label": "启用下跌家数提醒", "type": "boolean", "default": False, "description": "是否监听全市场下跌家数。"},
            {"key": "down_count_threshold", "label": "下跌家数阈值", "type": "number", "default": 3000, "description": "下跌家数达到该值时输出市场偏弱信号。"},
            {"key": "limit_up_enabled", "label": "启用涨停家数提醒", "type": "boolean", "default": False, "description": "是否监听涨停家数。"},
            {"key": "limit_up_threshold", "label": "涨停家数阈值", "type": "number", "default": 80, "description": "涨停家数达到该值时输出市场强势信号。"},
            {"key": "limit_down_enabled", "label": "启用跌停家数提醒", "type": "boolean", "default": False, "description": "是否监听跌停家数。"},
            {"key": "limit_down_threshold", "label": "跌停家数阈值", "type": "number", "default": 20, "description": "跌停家数达到该值时输出风险信号。"},
            {"key": "north_money_in_enabled", "label": "启用北向流入提醒", "type": "boolean", "default": False, "description": "是否监听北向资金流入。"},
            {"key": "north_money_in_threshold", "label": "北向流入阈值(亿)", "type": "float", "default": 20, "description": "北向资金流入达到该值时输出正向信号。"},
            {"key": "north_money_out_enabled", "label": "启用北向流出提醒", "type": "boolean", "default": False, "description": "是否监听北向资金流出。"},
            {"key": "north_money_out_threshold", "label": "北向流出阈值(亿)", "type": "float", "default": 20, "description": "北向资金流出达到该值时输出风险信号。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "市场指标偏强", "summary": "指数、上涨家数或北向资金达到正向阈值。"},
            {"signal": 0, "title": "市场指标未触发", "summary": "关键指标仍在配置阈值内。"},
            {"signal": -1, "title": "市场风险触发", "summary": "指数下跌、跌停家数或北向流出达到风险阈值。"},
        ],
    },
    {
        "strategy_key": "limit_open",
        "name": "涨跌停打开",
        "description": "迁移自市场监听：检测涨停或跌停封板后打开的盘中异动，适合打板与风险观察。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen"],
        "supports_state": True,
        "version": 1,
        "tags": ["涨跌停", "打板", "盘中"],
        "param_schema": [
            {
                "key": "limit_type",
                "label": "监控方向",
                "type": "select",
                "default": "both",
                "description": "决定监听涨停打开、跌停打开还是双向。",
                "options": [
                    {"label": "双向", "value": "both"},
                    {"label": "涨停打开", "value": "up"},
                    {"label": "跌停打开", "value": "down"},
                ],
            },
        ],
        "sample_outputs": [
            {"signal": 1, "title": "涨停打开", "summary": "涨停封板状态被打开，可触发通知或股池流转。"},
            {"signal": 0, "title": "封板状态未变化", "summary": "未检测到打开动作。"},
            {"signal": -1, "title": "跌停打开", "summary": "跌停封板状态被打开，可作为风险或反转观察信号。"},
        ],
    },
    {
        "strategy_key": "intraday_price_move",
        "name": "分钟异动",
        "description": "迁移自市场监听：最近 N 分钟内涨跌幅超过阈值时触发，适合短线异动监听。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen"],
        "supports_state": True,
        "version": 1,
        "tags": ["分钟", "异动", "短线"],
        "param_schema": [
            {"key": "interval_minutes", "label": "区间分钟数", "type": "number", "default": 5, "description": "用于比较价格变化的分钟窗口。"},
            {"key": "threshold_pct", "label": "涨跌幅阈值(%)", "type": "float", "default": 2, "description": "窗口内涨跌幅达到该阈值时触发。"},
            {
                "key": "direction",
                "label": "监控方向",
                "type": "select",
                "default": "both",
                "description": "决定监听向上异动、向下异动还是双向。",
                "options": DIRECTION_OPTIONS,
            },
        ],
        "sample_outputs": [
            {"signal": 1, "title": "短线向上异动", "summary": "窗口内涨幅超过阈值。"},
            {"signal": 0, "title": "未触发", "summary": "窗口内涨跌幅未达到阈值。"},
            {"signal": -1, "title": "短线向下异动", "summary": "窗口内跌幅超过阈值。"},
        ],
    },
    {
        "strategy_key": "support_resistance",
        "name": "撑压线",
        "description": "迁移自市场监听：按股票级配置的支撑线和压力线，监听接近、跌破或突破行为。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen"],
        "supports_state": True,
        "version": 1,
        "tags": ["支撑", "压力", "画线"],
        "param_schema": [
            {"key": "near_threshold_pct", "label": "接近阈值(%)", "type": "float", "default": 1, "description": "价格接近支撑/压力线的允许范围。"},
            {"key": "breakout_threshold_pct", "label": "突破阈值(%)", "type": "float", "default": 0.5, "description": "确认突破或跌破线位的阈值。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "突破压力或站上关键线", "summary": "适合提醒或推动进入更高优先级股池。"},
            {"signal": 0, "title": "线位附近观察", "summary": "未达到突破或跌破条件。"},
            {"signal": -1, "title": "跌破支撑或触发风险线", "summary": "适合风险提醒或从观察池移出。"},
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
        "strategy_key": "trailing_stop_loss",
        "name": "移动止损",
        "description": "迁移自市场监听：跟踪加入监听后的最高价，回撤达到阈值后输出风险信号。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen", "sim_trade", "backtest"],
        "supports_state": True,
        "version": 1,
        "tags": ["移动止损", "持仓", "风控"],
        "param_schema": [
            {"key": "default_trail_pct", "label": "默认回撤比例(%)", "type": "float", "default": 6, "description": "从最高价回撤达到该比例时触发。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "价格继续创新高", "summary": "更新最高价状态，不触发卖出风险。"},
            {"signal": 0, "title": "回撤未达阈值", "summary": "继续持有或观察。"},
            {"signal": -1, "title": "移动止损触发", "summary": "从最高价回撤超过阈值，适合通知或模拟卖出。"},
        ],
    },
    {
        "strategy_key": "position_pnl",
        "name": "持仓盈亏阈值",
        "description": "迁移自市场监听：按交割单账户推导当前持仓成本，监听持仓总浮盈或浮亏达到阈值。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen"],
        "supports_state": True,
        "version": 1,
        "tags": ["持仓", "盈亏", "账户"],
        "param_schema": [
            {"key": "loss_threshold_pct", "label": "亏损提醒阈值(%)", "type": "float", "default": 3, "description": "持仓亏损达到该比例时输出风险信号。"},
            {"key": "profit_threshold_pct", "label": "盈利提醒阈值(%)", "type": "float", "default": 8, "description": "持仓盈利达到该比例时输出正向信号。"},
        ],
        "sample_outputs": [
            {"signal": 1, "title": "持仓盈利达标", "summary": "账户或持仓浮盈达到配置阈值。"},
            {"signal": 0, "title": "盈亏未触发", "summary": "持仓盈亏仍在配置区间内。"},
            {"signal": -1, "title": "持仓亏损触发", "summary": "账户或持仓浮亏达到配置阈值。"},
        ],
    },
    {
        "strategy_key": "position_intraday_pnl",
        "name": "盘中持仓盈亏变化",
        "description": "迁移自市场监听：按昨收到当前价的变化，监听持仓盘中收益波动。",
        "impl_type": "builtin_code",
        "supported_scenes": ["listen"],
        "supports_state": True,
        "version": 1,
        "tags": ["持仓", "盘中", "波动"],
        "param_schema": [
            {"key": "swing_threshold_pct", "label": "盘中波动阈值(%)", "type": "float", "default": 2, "description": "盘中收益变化达到该比例时触发。"},
            {
                "key": "direction",
                "label": "波动方向",
                "type": "select",
                "default": "both",
                "description": "决定监听向上、向下还是双向波动。",
                "options": DIRECTION_OPTIONS,
            },
        ],
        "sample_outputs": [
            {"signal": 1, "title": "盘中浮盈扩大", "summary": "持仓相对昨收出现明显正向波动。"},
            {"signal": 0, "title": "盘中波动正常", "summary": "持仓波动未达到阈值。"},
            {"signal": -1, "title": "盘中浮亏扩大", "summary": "持仓相对昨收出现明显负向波动。"},
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
    strategy = get_strategy_definition(body.strategy_key)

    if strategy_scenes is not None and scene not in strategy_scenes:
        errors.append("当前策略不支持所选场景")

    if strategy:
        for param in strategy.get("param_schema", []):
            if not param.get("required"):
                continue
            key = param.get("key")
            value = body.params.get(key, param.get("default")) if key else None
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"策略参数“{param.get('label') or key}”不能为空")

    if scope == StrategyV2TargetScopeType.EVENT:
        errors.append("事件范围本期只保留，不支持创建任务")

    if scope not in SCENE_TARGETS.get(scene, set()):
        errors.append("当前场景不支持所选目标范围")

    if schedule_mode not in SCENE_SCHEDULES.get(scene, set()):
        errors.append("当前场景不支持所选调度方式")

    if scene in {StrategyV2SceneType.BACKTEST, StrategyV2SceneType.SIM_TRADE} and not body.target_scope.params.get("trade_review_group_id"):
        errors.append("回测/模拟任务必须选择或创建交割单账户")

    if scope == StrategyV2TargetScopeType.CUSTOM_STOCK_LIST and scene != StrategyV2SceneType.LISTEN and not body.target_scope.ts_codes:
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
