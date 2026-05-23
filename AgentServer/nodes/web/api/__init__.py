"""
Web API 路由
"""

from .auth import router as auth_router
from .user import router as user_router
from .task import router as task_router
from .stock import router as stock_router
from .market import router as market_router
from .subscription import router as subscription_router
from .backtest import router as backtest_router
from .report import router as report_router
from .system import router as system_router
from .market_weather import router as market_weather_router
from .stock_picker import router as stock_picker_router
from .practice import router as practice_router
from .trade_review import router as trade_review_router
from .assistant import router as assistant_router
from .strategy_v2 import router as strategy_v2_router

__all__ = [
    "auth_router",
    "user_router",
    "task_router",
    "stock_router",
    "market_router",
    "subscription_router",
    "backtest_router",
    "report_router",
    "system_router",
    "market_weather_router",
    "stock_picker_router",
    "practice_router",
    "trade_review_router",
    "assistant_router",
    "strategy_v2_router",
]
