"""
策略订阅 API

简化架构：
- 每种策略类型只有一条策略数据
- 管理员可修改策略参数
- 普通用户只能添加/移除个股
"""

import asyncio
import logging
import uuid
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Body, Depends
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from core.protocols import StrategyType
from core.rpc import rpc_manager
from .auth import get_current_user, require_admin, CurrentUser


logger = logging.getLogger("api.subscription")


router = APIRouter()


# ==================== 已实现的策略类型 ====================

IMPLEMENTED_STRATEGIES = [
    StrategyType.MA5_BUY,      # 5日线低吸
    StrategyType.LIMIT_OPEN,   # 涨跌停打开
    StrategyType.PRICE_CHANGE, # 涨跌幅阈值
    StrategyType.SUPPORT_RESISTANCE, # 撑压线
    StrategyType.FIXED_STOP_LOSS, # 固定止损
    StrategyType.TRAILING_STOP_LOSS, # 移动止损
    StrategyType.POSITION_PNL, # 持仓总盈亏阈值
    StrategyType.POSITION_INTRADAY_PNL, # 盘中持仓盈亏变化
]

IMPLEMENTED_STRATEGY_VALUES = [s.value for s in IMPLEMENTED_STRATEGIES]
ALERT_FREQUENCY_OPTIONS = [
    {"label": "每日一次", "value": "daily_once"},
    {"label": "提醒后关闭", "value": "once_then_disable"},
    {"label": "不限次数", "value": "unlimited"},
]

# 策略元信息（名称、描述、默认参数）
STRATEGY_META = {
    StrategyType.MA5_BUY.value: {
        "name": "5日线低吸",
        "description": "当价格触及5日均线时提醒，适合低吸策略",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "touch_range": 2.0,
            "stable_periods": 2,
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {"key": "touch_range", "label": "触及范围 (%)", "type": "float", "default": 2.0},
            {"key": "stable_periods", "label": "企稳周期数", "type": "number", "default": 2},
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.LIMIT_OPEN.value: {
        "name": "涨跌停打开",
        "description": "涨停或跌停打开时提醒，适合打板策略",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "limit_type": "both",
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {
                "key": "limit_type",
                "label": "监控方向",
                "type": "string",
                "default": "both",
                "options": [
                    {"label": "涨停打开", "value": "up"},
                    {"label": "跌停打开", "value": "down"},
                    {"label": "双向", "value": "both"},
                ],
            },
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.PRICE_CHANGE.value: {
        "name": "涨跌幅阈值",
        "description": "涨跌幅超过阈值时提醒",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "threshold": 5.0,
            "direction": "both",
            "once_per_day": True,
            "alert_frequency": "daily_once",
        },
        "param_schema": [
            {"key": "threshold", "label": "涨跌阈值 (%)", "type": "float", "default": 5.0},
            {
                "key": "direction",
                "label": "监控方向",
                "type": "string",
                "default": "both",
                "options": [
                    {"label": "仅上涨", "value": "up"},
                    {"label": "仅下跌", "value": "down"},
                    {"label": "双向", "value": "both"},
                ],
            },
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.SUPPORT_RESISTANCE.value: {
        "name": "撑压线",
        "description": "根据每只股票单独配置的支撑线/压力线，在接近或突破时提醒",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "near_threshold_pct": 1.0,
            "breakout_threshold_pct": 0.5,
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {"key": "near_threshold_pct", "label": "接近阈值 (%)", "type": "float", "default": 1.0},
            {"key": "breakout_threshold_pct", "label": "突破阈值 (%)", "type": "float", "default": 0.5},
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.FIXED_STOP_LOSS.value: {
        "name": "固定止损",
        "description": "从加入监听时的基准价开始计算，跌到固定比例时提醒",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "default_stop_loss_pct": 8.0,
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {"key": "default_stop_loss_pct", "label": "默认止损比例 (%)", "type": "float", "default": 8.0},
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.TRAILING_STOP_LOSS.value: {
        "name": "移动止损",
        "description": "跟踪加入后最高价，回撤到固定比例时提醒",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "default_trail_pct": 6.0,
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {"key": "default_trail_pct", "label": "默认回撤比例 (%)", "type": "float", "default": 6.0},
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.POSITION_PNL.value: {
        "name": "持仓盈亏阈值",
        "description": "按交割单推导的当前持仓成本，监控总浮盈亏达到指定阈值",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "position_group_id": "",
            "position_group_name": "",
            "loss_threshold_pct": 3.0,
            "profit_threshold_pct": 8.0,
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {"key": "position_group_id", "label": "持仓分组", "type": "string", "default": ""},
            {"key": "loss_threshold_pct", "label": "亏损提醒阈值 (%)", "type": "float", "default": 3.0},
            {"key": "profit_threshold_pct", "label": "盈利提醒阈值 (%)", "type": "float", "default": 8.0},
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
    StrategyType.POSITION_INTRADAY_PNL.value: {
        "name": "盘中持仓盈亏变化",
        "description": "按昨收到现价的变化，监控盘中持仓收益波动",
        "schedule_type": "intraday_minute",
        "schedule_label": "盘中轮询",
        "basic_param_keys": ["alert_frequency"],
        "default_params": {
            "position_group_id": "",
            "position_group_name": "",
            "swing_threshold_pct": 2.0,
            "direction": "both",
            "once_per_day": True,
            "alert_frequency": "daily_once",
            "stock_configs": {},
        },
        "param_schema": [
            {"key": "position_group_id", "label": "持仓分组", "type": "string", "default": ""},
            {"key": "swing_threshold_pct", "label": "盘中波动阈值 (%)", "type": "float", "default": 2.0},
            {
                "key": "direction",
                "label": "波动方向",
                "type": "string",
                "default": "both",
                "options": [
                    {"label": "双向", "value": "both"},
                    {"label": "仅向上", "value": "up"},
                    {"label": "仅向下", "value": "down"},
                ],
            },
            {"key": "alert_frequency", "label": "提醒频率", "type": "string", "default": "daily_once", "options": ALERT_FREQUENCY_OPTIONS},
        ],
    },
}


# ==================== RPC 通知 ====================


async def _notify_listeners_refresh(strategy_type: Optional[str] = None) -> None:
    """
    通知所有 Listener 节点刷新策略配置
    
    在策略被修改后调用，确保 Listener 节点能及时感知变更。
    
    Args:
        strategy_type: 可选，指定刷新的策略类型
    """
    try:
        trace_id = uuid.uuid4().hex
        
        # 广播给所有 Listener 节点
        results = await rpc_manager.broadcast_by_type(
            node_type="listener",
            method="refresh_strategies",
            params={"strategy_type": strategy_type},
            trace_id=trace_id,
            source_node="web",
            timeout=5.0,
        )
        
        success_count = sum(1 for r in results if r.get("success"))
        total_count = len(results)
        
        if total_count > 0:
            logger.info(
                f"[{trace_id}] Notified {success_count}/{total_count} Listener nodes "
                f"to refresh strategies"
            )
        else:
            logger.debug(f"[{trace_id}] No Listener nodes to notify")
            
    except Exception as e:
        # 不阻塞主流程，仅记录日志
        logger.warning(f"Failed to notify Listener nodes: {e}")


# ==================== 请求/响应模型 ====================


class StockInfo(BaseModel):
    """股票信息"""
    ts_code: str
    name: str


class SubscriptionResponse(BaseModel):
    """策略订阅响应"""
    subscription_id: str
    strategy_id: str
    strategy_name: str
    strategy_type: str
    watch_list: List[str]  # 保持原有字段兼容
    watch_list_info: List[StockInfo]  # 新增：包含名称的股票列表
    params: dict
    is_active: bool
    created_at: str
    updated_at: str


class StrategyTypeInfo(BaseModel):
    """策略类型信息"""
    type: str
    name: str
    description: str
    schedule_type: str = "intraday_minute"
    schedule_label: str = "盘中轮询"
    basic_param_keys: List[str] = Field(default_factory=list)
    param_schema: List[dict]


class UpdateParamsRequest(BaseModel):
    """更新策略参数请求（仅管理员）"""
    params: dict = Field(..., description="策略参数")


class AddStockRequest(BaseModel):
    """添加股票请求"""
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")


class BatchAddStocksRequest(BaseModel):
    """批量添加股票请求"""
    ts_codes: List[str] = Field(..., min_length=1, description="股票代码列表")


class AddStockResponse(BaseModel):
    """添加股票响应"""
    success: bool
    message: str
    watch_list: List[str]


class BatchAddStockResponse(BaseModel):
    """批量添加股票响应"""
    success: bool
    message: str
    watch_list: List[str]
    added: List[str]
    skipped: List[str]


class UpdateStockConfigRequest(BaseModel):
    """更新单只股票的策略配置"""
    config: Dict[str, Any] = Field(..., description="单只股票的策略配置")


# ==================== 辅助函数 ====================


async def _get_stock_names(ts_codes: List[str]) -> dict:
    """批量获取股票名称"""
    if not ts_codes:
        return {}
    
    stocks = await mongo_manager.find_many(
        "stock_basic",
        {"ts_code": {"$in": ts_codes}},
        projection={"ts_code": 1, "name": 1},
    )
    
    return {s["ts_code"]: s.get("name", s["ts_code"]) for s in stocks}


async def _to_response(record: dict) -> SubscriptionResponse:
    """将 MongoDB 记录转换为响应模型"""
    created_at = record.get("created_at")
    updated_at = record.get("updated_at")
    watch_list = record.get("watch_list", [])
    
    # 获取股票名称
    stock_names = await _get_stock_names(watch_list)
    watch_list_info = [
        StockInfo(ts_code=code, name=stock_names.get(code, code))
        for code in watch_list
    ]
    
    return SubscriptionResponse(
        subscription_id=record.get("subscription_id", ""),
        strategy_id=record.get("strategy_id", ""),
        strategy_name=record.get("strategy_name", ""),
        strategy_type=record.get("strategy_type", ""),
        watch_list=watch_list,
        watch_list_info=watch_list_info,
        params=record.get("params", {}),
        is_active=record.get("is_active", True),
        created_at=created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or ""),
        updated_at=updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at or ""),
    )


async def _get_daily_record_for_date(ts_code: str, trade_date: str) -> dict:
    record = await mongo_manager.find_one(
        "stock_daily",
        {"ts_code": ts_code, "trade_date": trade_date},
        projection={"trade_date": 1, "low": 1, "high": 1, "close": 1},
    )
    if not record:
        raise HTTPException(status_code=400, detail=f"{ts_code} 在 {trade_date} 没有日线数据，请选择有效交易日")
    return record


async def _resolve_point_price(ts_code: str, trade_date: str, price_field: str) -> float:
    record = await _get_daily_record_for_date(ts_code, trade_date)

    value = record.get(price_field)
    if value is None:
        raise HTTPException(status_code=400, detail=f"{ts_code} 在 {trade_date} 缺少 {price_field} 价格，无法自动补全点位")

    return float(value)


async def _get_latest_daily_record(ts_code: str) -> dict:
    records = await mongo_manager.find_many(
        "stock_daily",
        {"ts_code": ts_code},
        projection={"trade_date": 1, "close": 1, "high": 1},
        sort=[("trade_date", -1)],
        limit=1,
    )
    if not records:
        raise HTTPException(status_code=400, detail=f"{ts_code} 缺少本地日线数据，暂时无法初始化止损基准")
    return records[0]


async def _resolve_close_price(ts_code: str, trade_date: str) -> float:
    record = await _get_daily_record_for_date(ts_code, trade_date)
    value = record.get("close")
    if value is None:
        raise HTTPException(status_code=400, detail=f"{ts_code} 在 {trade_date} 缺少收盘价，无法自动补全止损基准")
    return float(value)


def _parse_positive_float(raw_value: Any, field_name: str) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 必须为有效数字") from exc

    if value <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} 必须大于 0")
    return value


def _normalize_percent_input(raw_value: Any, field_name: str, default: float) -> float:
    candidate = default if raw_value in (None, "") else raw_value
    try:
        value = float(candidate)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 必须为有效数字") from exc

    if value <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} 必须大于 0")
    return value


async def _normalize_line_points(
    ts_code: str,
    line_type: str,
    points: Any,
) -> List[Dict[str, Any]]:
    if not isinstance(points, list) or len(points) != 2:
        raise HTTPException(status_code=400, detail=f"{line_type} 必须提供两个坐标点")

    normalized: List[Dict[str, Any]] = []
    price_field = "low" if line_type == "support_points" else "high"

    for index, point in enumerate(points, start=1):
        if not isinstance(point, dict):
            raise HTTPException(status_code=400, detail=f"{line_type} 第 {index} 个点位格式不正确")
        trade_date = str(point.get("date", "")).strip()
        if not trade_date or len(trade_date) != 8 or not trade_date.isdigit():
            raise HTTPException(status_code=400, detail=f"{line_type} 第 {index} 个点位日期必须为 YYYYMMDD")

        await _get_daily_record_for_date(ts_code, trade_date)

        raw_price = point.get("price")
        if raw_price in (None, ""):
            price = await _resolve_point_price(ts_code, trade_date, price_field)
        else:
            try:
                price = float(raw_price)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{line_type} 第 {index} 个点位价格无效") from exc

        if price <= 0:
            raise HTTPException(status_code=400, detail=f"{line_type} 第 {index} 个点位价格必须大于 0")

        normalized.append({"date": trade_date, "price": round(price, 4)})

    normalized.sort(key=lambda item: item["date"])
    if normalized[0]["date"] == normalized[1]["date"]:
        raise HTTPException(status_code=400, detail=f"{line_type} 的两个点位日期不能相同")

    return normalized


async def _normalize_support_resistance_config(ts_code: str, config: Dict[str, Any]) -> Dict[str, Any]:
    trend_type = str(config.get("trend_type", "custom")).strip() or "custom"
    support_enabled = bool(config.get("support_enabled", False))
    resistance_enabled = bool(config.get("resistance_enabled", False))

    if not support_enabled and not resistance_enabled:
        raise HTTPException(status_code=400, detail="至少需要启用支撑线或压力线中的一条")

    normalized = {
        "trend_type": trend_type,
        "support_enabled": support_enabled,
        "resistance_enabled": resistance_enabled,
        "support_points": [],
        "resistance_points": [],
        "note": str(config.get("note", "") or "").strip(),
    }

    if support_enabled:
        normalized["support_points"] = await _normalize_line_points(
            ts_code=ts_code,
            line_type="support_points",
            points=config.get("support_points"),
        )
    if resistance_enabled:
        normalized["resistance_points"] = await _normalize_line_points(
            ts_code=ts_code,
            line_type="resistance_points",
            points=config.get("resistance_points"),
        )

    return normalized


async def _normalize_fixed_stop_loss_config(
    ts_code: str,
    config: Dict[str, Any],
    existing_config: Optional[Dict[str, Any]],
    default_stop_loss_pct: float,
) -> Dict[str, Any]:
    current = dict(existing_config or {})
    enabled = bool(config.get("enabled", current.get("enabled", True)))
    note = str(config.get("note", current.get("note", "")) or "").strip()

    reference_date = str(config.get("reference_date", current.get("reference_date", "")) or "").strip()
    raw_reference_price = config.get("reference_price", current.get("reference_price"))

    if not reference_date:
        latest_record = await _get_latest_daily_record(ts_code)
        reference_date = str(latest_record.get("trade_date") or "")
        latest_close = float(latest_record.get("close") or 0)
    else:
        latest_close = await _resolve_close_price(ts_code, reference_date)

    if raw_reference_price in (None, ""):
        reference_price = latest_close
    else:
        reference_price = _parse_positive_float(raw_reference_price, "参考价格")

    stop_loss_pct = _normalize_percent_input(
        config.get("stop_loss_pct", current.get("stop_loss_pct")),
        "止损比例",
        default_stop_loss_pct,
    )

    return {
        "enabled": enabled,
        "reference_price": round(reference_price, 4),
        "reference_date": reference_date,
        "stop_loss_pct": round(stop_loss_pct, 4),
        "note": note,
        "last_triggered_date": str(current.get("last_triggered_date", "") or ""),
    }


async def _normalize_trailing_stop_loss_config(
    ts_code: str,
    config: Dict[str, Any],
    existing_config: Optional[Dict[str, Any]],
    default_trail_pct: float,
) -> Dict[str, Any]:
    current = dict(existing_config or {})
    enabled = bool(config.get("enabled", current.get("enabled", True)))
    note = str(config.get("note", current.get("note", "")) or "").strip()

    entry_date = str(config.get("entry_date", current.get("entry_date", "")) or "").strip()
    raw_entry_price = config.get("entry_price", current.get("entry_price"))

    if not entry_date:
        latest_record = await _get_latest_daily_record(ts_code)
        entry_date = str(latest_record.get("trade_date") or "")
        fallback_entry_price = float(latest_record.get("close") or 0)
    else:
        fallback_entry_price = await _resolve_close_price(ts_code, entry_date)

    if raw_entry_price in (None, ""):
        entry_price = fallback_entry_price
    else:
        entry_price = _parse_positive_float(raw_entry_price, "入场价格")

    highest_price_date = str(
        config.get("highest_price_date", current.get("highest_price_date", entry_date)) or entry_date
    ).strip()
    raw_highest_price = config.get("highest_price", current.get("highest_price"))

    if raw_highest_price in (None, ""):
        if highest_price_date:
            highest_price = await _resolve_close_price(ts_code, highest_price_date)
        else:
            highest_price = entry_price
            highest_price_date = entry_date
    else:
        highest_price = _parse_positive_float(raw_highest_price, "最高价格")

    if highest_price_date and highest_price_date < entry_date:
        raise HTTPException(status_code=400, detail="最高价日期不能早于入场日期")

    highest_price = max(highest_price, entry_price)
    if not highest_price_date:
        highest_price_date = entry_date

    trail_pct = _normalize_percent_input(
        config.get("trail_pct", current.get("trail_pct")),
        "回撤比例",
        default_trail_pct,
    )

    return {
        "enabled": enabled,
        "entry_price": round(entry_price, 4),
        "entry_date": entry_date,
        "highest_price": round(highest_price, 4),
        "highest_price_date": highest_price_date,
        "trail_pct": round(trail_pct, 4),
        "note": note,
        "last_triggered_date": str(current.get("last_triggered_date", "") or ""),
    }


async def _initialize_stock_config_on_add(
    strategy_type: str,
    record: Dict[str, Any],
    ts_code: str,
) -> Optional[Dict[str, Any]]:
    params = dict(record.get("params", {}) or {})
    stock_configs = dict(params.get("stock_configs", {}) or {})
    if strategy_type == StrategyType.SUPPORT_RESISTANCE.value:
        return None

    if strategy_type == StrategyType.FIXED_STOP_LOSS.value:
        if stock_configs.get(ts_code):
            return None
        latest_record = await _get_latest_daily_record(ts_code)
        stock_configs[ts_code] = {
            "enabled": True,
            "reference_price": round(float(latest_record.get("close") or 0), 4),
            "reference_date": str(latest_record.get("trade_date") or ""),
            "stop_loss_pct": round(float(params.get("default_stop_loss_pct", 8.0) or 8.0), 4),
            "note": "",
            "last_triggered_date": "",
        }
    elif strategy_type == StrategyType.TRAILING_STOP_LOSS.value:
        if stock_configs.get(ts_code):
            return None
        latest_record = await _get_latest_daily_record(ts_code)
        latest_price = round(float(latest_record.get("close") or 0), 4)
        latest_date = str(latest_record.get("trade_date") or "")
        stock_configs[ts_code] = {
            "enabled": True,
            "entry_price": latest_price,
            "entry_date": latest_date,
            "highest_price": latest_price,
            "highest_price_date": latest_date,
            "trail_pct": round(float(params.get("default_trail_pct", 6.0) or 6.0), 4),
            "note": "",
            "last_triggered_date": "",
        }
    else:
        return None

    params["stock_configs"] = stock_configs
    return params


async def _normalize_transition_rules(
    user_id: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    transition_rules = params.get("transition_rules")
    if transition_rules is None:
        return params

    if not isinstance(transition_rules, list):
        raise HTTPException(status_code=400, detail="transition_rules 必须为数组")

    normalized_rules: List[Dict[str, Any]] = []
    pool_cache: Dict[str, Dict[str, Any]] = {}

    async def get_pool(pool_id: str) -> Dict[str, Any]:
        if pool_id not in pool_cache:
            pool = await mongo_manager.find_one(
                "stock_pools",
                {"pool_id": pool_id, "user_id": user_id},
                projection={"pool_id": 1, "name": 1, "user_id": 1},
            )
            if not pool:
                raise HTTPException(status_code=400, detail=f"股池 {pool_id} 不存在或无权限访问")
            pool_cache[pool_id] = pool
        return pool_cache[pool_id]

    for raw_rule in transition_rules:
        if not isinstance(raw_rule, dict):
            raise HTTPException(status_code=400, detail="transition_rules 中存在无效规则")

        target_pool_id = str(raw_rule.get("target_pool_id", "")).strip()
        if not target_pool_id:
            raise HTTPException(status_code=400, detail="自动流转规则必须选择目标股池")

        target_pool = await get_pool(target_pool_id)

        source_pool_ids_raw = raw_rule.get("source_pool_ids") or []
        if not isinstance(source_pool_ids_raw, list):
            raise HTTPException(status_code=400, detail="source_pool_ids 必须为数组")

        source_pool_ids: List[str] = []
        source_pool_names: List[str] = []
        seen_source_ids = set()
        for item in source_pool_ids_raw:
            pool_id = str(item or "").strip()
            if not pool_id or pool_id in seen_source_ids or pool_id == target_pool_id:
                continue
            source_pool = await get_pool(pool_id)
            seen_source_ids.add(pool_id)
            source_pool_ids.append(pool_id)
            source_pool_names.append(str(source_pool.get("name") or pool_id))

        mode = str(raw_rule.get("mode", "move") or "move").strip().lower()
        if mode not in {"move", "copy"}:
            raise HTTPException(status_code=400, detail="自动流转模式只支持 move 或 copy")

        cooldown_days_raw = raw_rule.get("cooldown_days", 1)
        try:
            cooldown_days = max(1, int(cooldown_days_raw))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="cooldown_days 必须为大于等于 1 的整数") from exc

        normalized_rules.append({
            "rule_id": str(raw_rule.get("rule_id") or uuid.uuid4().hex),
            "enabled": bool(raw_rule.get("enabled", True)),
            "target_pool_id": target_pool_id,
            "target_pool_name": str(target_pool.get("name") or target_pool_id),
            "source_pool_ids": source_pool_ids,
            "source_pool_names": source_pool_names,
            "mode": mode,
            "cooldown_days": cooldown_days,
            "note": str(raw_rule.get("note", "") or "").strip(),
        })

    normalized_params = dict(params)
    normalized_params["transition_rules"] = normalized_rules
    return normalized_params


async def _normalize_position_group_params(
    user_id: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    normalized_params = dict(params)
    position_group_id = str(normalized_params.get("position_group_id") or "").strip()
    if not position_group_id:
        normalized_params["position_group_id"] = ""
        normalized_params["position_group_name"] = ""
        return normalized_params

    group = await mongo_manager.find_one(
        "trade_review_groups",
        {"group_id": position_group_id, "user_id": user_id},
        projection={"group_id": 1, "name": 1},
    )
    if not group:
        raise HTTPException(status_code=400, detail="持仓分组不存在或无权限访问")

    normalized_params["position_group_id"] = position_group_id
    normalized_params["position_group_name"] = str(group.get("name") or position_group_id)

    direction = normalized_params.get("direction")
    if direction is not None:
        direction_text = str(direction or "both").strip().lower()
        if direction_text not in {"both", "up", "down"}:
            raise HTTPException(status_code=400, detail="direction 只支持 both / up / down")
        normalized_params["direction"] = direction_text

    return normalized_params


def _normalize_alert_frequency(params: Dict[str, Any]) -> Dict[str, Any]:
    normalized_params = dict(params)
    raw_value = str(normalized_params.get("alert_frequency") or "").strip().lower()
    if raw_value:
        if raw_value not in {"daily_once", "once_then_disable", "unlimited"}:
            raise HTTPException(status_code=400, detail="alert_frequency 只支持 daily_once / once_then_disable / unlimited")
        normalized_params["alert_frequency"] = raw_value
        normalized_params["once_per_day"] = raw_value == "daily_once"
        return normalized_params

    if "once_per_day" in normalized_params:
        normalized_params["alert_frequency"] = "daily_once" if bool(normalized_params.get("once_per_day", True)) else "unlimited"
    return normalized_params


async def _validate_stock_exists(ts_code: str) -> dict:
    stock = await mongo_manager.find_one(
        "stock_basic",
        {"ts_code": ts_code},
    )
    if not stock:
        raise HTTPException(status_code=400, detail=f"股票 {ts_code} 不存在")
    return stock


async def _ensure_strategy_exists(strategy_type: str) -> dict:
    """
    确保策略存在，如果不存在则自动创建
    
    每种策略类型只有一条记录
    """
    import uuid
    
    # 查找现有策略
    record = await mongo_manager.find_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
    )
    
    if record:
        return record
    
    # 不存在则创建
    meta = STRATEGY_META.get(strategy_type, {})
    now = datetime.utcnow()
    
    doc = {
        "subscription_id": uuid.uuid4().hex,
        "strategy_id": uuid.uuid4().hex,
        "strategy_name": meta.get("name", strategy_type),
        "strategy_type": strategy_type,
        "watch_list": [],  # 初始为空，用户添加个股
        "params": meta.get("default_params", {}),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    
    await mongo_manager.insert_one("strategy_subscriptions", doc)
    return doc


# ==================== API 端点 ====================


@router.get("/types", response_model=List[StrategyTypeInfo])
async def get_available_strategy_types():
    """
    获取可用的策略类型列表
    
    返回已在 Listener 节点实现的策略类型
    """
    result = []
    for st in IMPLEMENTED_STRATEGIES:
        meta = STRATEGY_META.get(st.value, {})
        result.append(StrategyTypeInfo(
            type=st.value,
            name=meta.get("name", st.value),
            description=meta.get("description", ""),
            schedule_type=meta.get("schedule_type", "intraday_minute"),
            schedule_label=meta.get("schedule_label", "盘中轮询"),
            basic_param_keys=meta.get("basic_param_keys", []),
            param_schema=meta.get("param_schema", []),
        ))
    return result


@router.get("", response_model=List[SubscriptionResponse])
async def get_subscriptions(
    is_active: Optional[bool] = None,
    strategy_type: Optional[str] = None,
):
    """
    获取策略订阅列表
    
    每种策略类型只有一条记录
    """
    filter_query = {}
    
    if is_active is not None:
        filter_query["is_active"] = is_active
    if strategy_type:
        filter_query["strategy_type"] = strategy_type
    
    records = await mongo_manager.find_many(
        "strategy_subscriptions",
        filter_query,
        sort=[("strategy_type", 1)],
    )
    
    # 使用 asyncio.gather 并行获取股票名称
    responses = await asyncio.gather(*[_to_response(r) for r in records])
    return list(responses)


@router.get("/{strategy_type}", response_model=SubscriptionResponse)
async def get_subscription_by_type(strategy_type: str = Path(...)):
    """
    获取指定类型的策略
    
    如果不存在会自动创建（使用默认参数）
    """
    if strategy_type not in IMPLEMENTED_STRATEGY_VALUES:
        raise HTTPException(
            status_code=400, 
            detail=f"策略类型 '{strategy_type}' 不存在"
        )
    
    record = await _ensure_strategy_exists(strategy_type)
    return await _to_response(record)


@router.put("/{strategy_type}/params", response_model=SubscriptionResponse)
async def update_strategy_params(
    strategy_type: str = Path(...),
    data: UpdateParamsRequest = Body(...),
    admin: CurrentUser = Depends(require_admin),
):
    """
    更新策略参数（仅管理员）
    
    需要登录且具有管理员权限
    """
    if strategy_type not in IMPLEMENTED_STRATEGY_VALUES:
        raise HTTPException(
            status_code=400, 
            detail=f"策略类型 '{strategy_type}' 不存在"
        )
    
    # 确保策略存在
    record = await _ensure_strategy_exists(strategy_type)
    current_params = dict(record.get("params", {}) or {})
    updated_params = dict(data.params)
    if "stock_configs" in current_params and "stock_configs" not in updated_params:
        updated_params["stock_configs"] = current_params["stock_configs"]
    if "transition_rules" in current_params and "transition_rules" not in updated_params:
        updated_params["transition_rules"] = current_params["transition_rules"]
    updated_params = await _normalize_transition_rules(admin.user_id, updated_params)
    updated_params = await _normalize_position_group_params(admin.user_id, updated_params)
    updated_params = _normalize_alert_frequency(updated_params)
    
    # 更新参数
    await mongo_manager.update_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
        {
            "$set": {
                "params": updated_params,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    
    # 通知 Listener 节点刷新
    asyncio.create_task(_notify_listeners_refresh(strategy_type))
    
    # 获取更新后的记录
    updated = await mongo_manager.find_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
    )
    
    return await _to_response(updated)


@router.patch("/{strategy_type}/toggle")
async def toggle_subscription(
    strategy_type: str = Path(...),
    admin: CurrentUser = Depends(require_admin),
):
    """
    切换策略激活状态（仅管理员）
    
    需要登录且具有管理员权限
    """
    if strategy_type not in IMPLEMENTED_STRATEGY_VALUES:
        raise HTTPException(
            status_code=400, 
            detail=f"策略类型 '{strategy_type}' 不存在"
        )
    
    record = await _ensure_strategy_exists(strategy_type)
    new_status = not record.get("is_active", True)
    
    await mongo_manager.update_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
        {
            "$set": {
                "is_active": new_status,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    
    # 通知 Listener 节点刷新
    asyncio.create_task(_notify_listeners_refresh(strategy_type))
    
    return {
        "strategy_type": strategy_type,
        "is_active": new_status,
        "message": "已激活" if new_status else "已停用",
    }


# ==================== 个股管理 ====================


@router.post("/{strategy_type}/stocks", response_model=AddStockResponse)
async def add_stock_to_strategy(
    strategy_type: str = Path(...),
    data: AddStockRequest = Body(...),
):
    """
    向策略添加个股（所有用户可用）
    
    - 自动检查股票代码格式
    - 检查是否已存在，避免重复添加
    - 验证股票是否在 stock_basic 表中存在
    """
    if strategy_type not in IMPLEMENTED_STRATEGY_VALUES:
        raise HTTPException(
            status_code=400, 
            detail=f"策略类型 '{strategy_type}' 不存在"
        )
    
    ts_code = data.ts_code.upper()
    
    # 确保策略存在
    record = await _ensure_strategy_exists(strategy_type)
    watch_list: List[str] = record.get("watch_list", [])
    
    # 检查是否已存在
    if ts_code in watch_list:
        return AddStockResponse(
            success=False,
            message=f"{ts_code} 已在监听列表中",
            watch_list=watch_list,
        )
    
    # 验证股票是否存在
    stock = await _validate_stock_exists(ts_code)
    
    # 添加到 watch_list
    watch_list.append(ts_code)

    update_payload: Dict[str, Any] = {
        "watch_list": watch_list,
        "updated_at": datetime.utcnow(),
    }
    initialized_params = await _initialize_stock_config_on_add(strategy_type, record, ts_code)
    if initialized_params is not None:
        update_payload["params"] = initialized_params

    await mongo_manager.update_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
        {
            "$set": update_payload
        },
    )
    
    # 通知 Listener 节点刷新
    asyncio.create_task(_notify_listeners_refresh(strategy_type))
    
    stock_name = stock.get("name", ts_code)
    suffix = ""
    if strategy_type == StrategyType.SUPPORT_RESISTANCE.value:
        suffix = "，请继续配置撑压线点位"
    elif strategy_type == StrategyType.FIXED_STOP_LOSS.value:
        suffix = "，已按最新本地收盘价初始化固定止损基准，可后续调整"
    elif strategy_type == StrategyType.TRAILING_STOP_LOSS.value:
        suffix = "，已按最新本地收盘价初始化移动止损基准，可后续调整"
    return AddStockResponse(
        success=True,
        message=f"已添加 {stock_name}({ts_code}){suffix}",
        watch_list=watch_list,
    )


@router.post("/{strategy_type}/stocks/batch", response_model=BatchAddStockResponse)
async def batch_add_stocks_to_strategy(
    strategy_type: str = Path(...),
    data: BatchAddStocksRequest = Body(...),
):
    """
    批量向策略添加个股（所有用户可用）

    - 自动去重
    - 跳过已经存在的股票
    - 验证股票是否存在
    """
    if strategy_type not in IMPLEMENTED_STRATEGY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"策略类型 '{strategy_type}' 不存在"
        )

    normalized_codes: List[str] = []
    seen_codes = set()
    for raw_code in data.ts_codes:
        ts_code = str(raw_code or "").strip().upper()
        if not ts_code:
            continue
        if not re.match(r"^\d{6}\.(SH|SZ|BJ)$", ts_code):
            continue
        if ts_code in seen_codes:
            continue
        seen_codes.add(ts_code)
        normalized_codes.append(ts_code)

    if not normalized_codes:
        raise HTTPException(status_code=400, detail="请至少提供一只有效股票")

    record = await _ensure_strategy_exists(strategy_type)
    watch_list: List[str] = list(record.get("watch_list", []))
    added: List[str] = []
    skipped: List[str] = []

    params = dict(record.get("params", {}) or {})
    stock_configs = dict(params.get("stock_configs", {}) or {})

    for ts_code in normalized_codes:
        if ts_code in watch_list:
            skipped.append(ts_code)
            continue
        await _validate_stock_exists(ts_code)
        watch_list.append(ts_code)
        added.append(ts_code)

        if strategy_type == StrategyType.FIXED_STOP_LOSS.value:
            latest_record = await _get_latest_daily_record(ts_code)
            stock_configs[ts_code] = {
                "enabled": True,
                "reference_price": round(float(latest_record.get("close") or 0), 4),
                "reference_date": str(latest_record.get("trade_date") or ""),
                "stop_loss_pct": round(float(params.get("default_stop_loss_pct", 8.0) or 8.0), 4),
                "note": "",
                "last_triggered_date": "",
            }
        elif strategy_type == StrategyType.TRAILING_STOP_LOSS.value:
            latest_record = await _get_latest_daily_record(ts_code)
            latest_price = round(float(latest_record.get("close") or 0), 4)
            latest_date = str(latest_record.get("trade_date") or "")
            stock_configs[ts_code] = {
                "enabled": True,
                "entry_price": latest_price,
                "entry_date": latest_date,
                "highest_price": latest_price,
                "highest_price_date": latest_date,
                "trail_pct": round(float(params.get("default_trail_pct", 6.0) or 6.0), 4),
                "note": "",
                "last_triggered_date": "",
            }

    if added:
        if strategy_type in {StrategyType.FIXED_STOP_LOSS.value, StrategyType.TRAILING_STOP_LOSS.value}:
            params["stock_configs"] = stock_configs
        await mongo_manager.update_one(
            "strategy_subscriptions",
            {"strategy_type": strategy_type},
            {
                "$set": {
                    "watch_list": watch_list,
                    **({"params": params} if strategy_type in {StrategyType.FIXED_STOP_LOSS.value, StrategyType.TRAILING_STOP_LOSS.value} else {}),
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        asyncio.create_task(_notify_listeners_refresh(strategy_type))

    message = f"已添加 {len(added)} 只股票"
    if skipped:
        message += f"，跳过 {len(skipped)} 只已存在股票"
    if strategy_type == StrategyType.SUPPORT_RESISTANCE.value and added:
        message += "。请后续逐只配置撑压线点位"
    elif strategy_type == StrategyType.FIXED_STOP_LOSS.value and added:
        message += "。已按最新本地收盘价初始化固定止损基准，可后续逐只调整"
    elif strategy_type == StrategyType.TRAILING_STOP_LOSS.value and added:
        message += "。已按最新本地收盘价初始化移动止损基准，可后续逐只调整"

    return BatchAddStockResponse(
        success=bool(added),
        message=message,
        watch_list=watch_list,
        added=added,
        skipped=skipped,
    )


@router.delete("/{strategy_type}/stocks/{ts_code}", response_model=AddStockResponse)
async def remove_stock_from_strategy(
    strategy_type: str = Path(...),
    ts_code: str = Path(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$"),
):
    """从策略移除个股（所有用户可用）"""
    if strategy_type not in IMPLEMENTED_STRATEGY_VALUES:
        raise HTTPException(
            status_code=400, 
            detail=f"策略类型 '{strategy_type}' 不存在"
        )
    
    ts_code = ts_code.upper()
    
    # 确保策略存在
    record = await _ensure_strategy_exists(strategy_type)
    watch_list: List[str] = record.get("watch_list", [])
    
    # 检查是否存在
    if ts_code not in watch_list:
        return AddStockResponse(
            success=False,
            message=f"{ts_code} 不在监听列表中",
            watch_list=watch_list,
        )
    
    # 移除
    watch_list.remove(ts_code)
    params = dict(record.get("params", {}) or {})
    stock_configs = dict(params.get("stock_configs", {}) or {})
    if ts_code in stock_configs:
        stock_configs.pop(ts_code, None)
        params["stock_configs"] = stock_configs
    
    await mongo_manager.update_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
        {
            "$set": {
                "watch_list": watch_list,
                "params": params,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    
    # 通知 Listener 节点刷新
    asyncio.create_task(_notify_listeners_refresh(strategy_type))
    
    return AddStockResponse(
        success=True,
        message=f"已移除 {ts_code}",
        watch_list=watch_list,
    )


@router.put("/{strategy_type}/stocks/{ts_code}/config", response_model=SubscriptionResponse)
async def update_stock_config(
    strategy_type: str = Path(...),
    ts_code: str = Path(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$"),
    data: UpdateStockConfigRequest = Body(...),
):
    """更新单只股票的策略配置"""
    if strategy_type not in {
        StrategyType.SUPPORT_RESISTANCE.value,
        StrategyType.FIXED_STOP_LOSS.value,
        StrategyType.TRAILING_STOP_LOSS.value,
    }:
        raise HTTPException(status_code=400, detail="当前策略暂不支持按股票单独配置")

    record = await _ensure_strategy_exists(strategy_type)
    ts_code = ts_code.upper()
    watch_list: List[str] = record.get("watch_list", [])
    if ts_code not in watch_list:
        raise HTTPException(status_code=400, detail=f"{ts_code} 不在监听列表中，请先添加股票")

    params = dict(record.get("params", {}) or {})
    stock_configs = dict(params.get("stock_configs", {}) or {})
    current_config = dict(stock_configs.get(ts_code, {}) or {})

    if strategy_type == StrategyType.SUPPORT_RESISTANCE.value:
        normalized_config = await _normalize_support_resistance_config(ts_code, data.config)
    elif strategy_type == StrategyType.FIXED_STOP_LOSS.value:
        normalized_config = await _normalize_fixed_stop_loss_config(
            ts_code,
            data.config,
            current_config,
            float(params.get("default_stop_loss_pct", 8.0) or 8.0),
        )
    else:
        normalized_config = await _normalize_trailing_stop_loss_config(
            ts_code,
            data.config,
            current_config,
            float(params.get("default_trail_pct", 6.0) or 6.0),
        )

    stock_configs[ts_code] = normalized_config
    params["stock_configs"] = stock_configs

    await mongo_manager.update_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
        {
            "$set": {
                "params": params,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    asyncio.create_task(_notify_listeners_refresh(strategy_type))
    updated = await mongo_manager.find_one(
        "strategy_subscriptions",
        {"strategy_type": strategy_type},
    )
    return await _to_response(updated)


# ==================== 管理员初始化 ====================


@router.post("/init", status_code=201)
async def init_all_strategies(
    admin: CurrentUser = Depends(require_admin),
):
    """
    初始化所有策略（仅管理员）
    
    为每种已实现的策略类型创建一条记录（如果不存在）
    需要登录且具有管理员权限
    """
    
    created = []
    existing = []
    
    for st in IMPLEMENTED_STRATEGIES:
        record = await mongo_manager.find_one(
            "strategy_subscriptions",
            {"strategy_type": st.value},
        )
        
        if record:
            existing.append(st.value)
        else:
            await _ensure_strategy_exists(st.value)
            created.append(st.value)
    
    return {
        "message": "初始化完成",
        "created": created,
        "existing": existing,
    }
