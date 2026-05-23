"""
Strategy V2 task models.

These models intentionally describe the new V2 scene-task layer without changing
the legacy strategy subscription models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StrategyV2SceneType(str, Enum):
    SCAN = "scan"
    LISTEN = "listen"
    BACKTEST = "backtest"
    SIM_TRADE = "sim_trade"


class StrategyV2TargetScopeType(str, Enum):
    WATCHLIST = "watchlist"
    TRADE_ACCOUNT = "trade_account"
    STOCK_POOL = "stock_pool"
    ALL_MARKET = "all_market"
    CUSTOM_STOCK_LIST = "custom_stock_list"
    INDEX = "index"
    EVENT = "event"


class StrategyV2ScheduleMode(str, Enum):
    ONCE = "once"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class StrategyV2ActionType(str, Enum):
    NOTIFY = "notify"
    ADD_TO_POOL = "add_to_pool"
    POOL_TRANSITION = "pool_transition"
    TEMP_LIST = "temp_list"
    PAPER_TRADE = "paper_trade"


class StrategyV2TaskStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class StrategyV2TargetScope(BaseModel):
    scope_type: StrategyV2TargetScopeType
    scope_id: Optional[str] = None
    scope_name: Optional[str] = None
    ts_codes: List[str] = Field(default_factory=list)
    index_codes: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None


class StrategyV2ScheduleConfig(BaseModel):
    mode: StrategyV2ScheduleMode
    label: str
    timezone: str = "Asia/Shanghai"
    slot: Optional[str] = None
    interval_seconds: Optional[int] = None
    times: List[str] = Field(default_factory=list)
    trading_day_only: bool = False


class StrategyV2TaskAction(BaseModel):
    action_type: StrategyV2ActionType
    enabled: bool = True
    trigger_signals: List[int] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    label: Optional[str] = None


class StrategyV2CreateTaskRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scene_type: StrategyV2SceneType
    strategy_key: str = Field(..., min_length=1, max_length=100)
    target_scope: StrategyV2TargetScope
    schedule: StrategyV2ScheduleConfig
    params: Dict[str, Any] = Field(default_factory=dict)
    actions: List[StrategyV2TaskAction] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, max_length=500)


class StrategyV2SceneTaskResponse(StrategyV2CreateTaskRequest):
    task_id: str
    user_id: str
    status: StrategyV2TaskStatus
    target_scope_summary: str
    schedule_label: str
    created_at: datetime
    updated_at: datetime


class StrategyV2DictionaryItem(BaseModel):
    code: str
    label: str
    description: str
    supported_scenes: List[StrategyV2SceneType] = Field(default_factory=list)
    disabled: bool = False


class StrategyV2RuleDictionary(BaseModel):
    scenes: List[StrategyV2DictionaryItem]
    target_scopes: List[StrategyV2DictionaryItem]
    schedules: List[StrategyV2DictionaryItem]
    actions: List[StrategyV2DictionaryItem]
