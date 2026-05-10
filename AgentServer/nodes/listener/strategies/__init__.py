"""
策略执行器

内置策略:
- LimitOpenStrategy: 涨跌停打开策略
- PriceChangeStrategy: 涨跌幅阈值策略
- IntradayPriceMoveStrategy: 分钟异动策略
- MA5BuyStrategy: 5日线低吸策略
- SupportResistanceStrategy: 撑压线策略
- FixedStopLossStrategy: 固定止损策略
- TrailingStopLossStrategy: 移动止损策略
- PositionPnlStrategy: 持仓总盈亏阈值策略
- PositionIntradayPnlStrategy: 盘中持仓盈亏变化策略
- MarketIndexAlertStrategy: 指数指标预警策略
"""

from .base import BaseStrategy
from .limit_open import LimitOpenStrategy
from .price_change import PriceChangeStrategy
from .intraday_price_move import IntradayPriceMoveStrategy
from .ma5_buy import MA5BuyStrategy
from .support_resistance import SupportResistanceStrategy
from .fixed_stop_loss import FixedStopLossStrategy
from .trailing_stop_loss import TrailingStopLossStrategy
from .position_pnl import PositionPnlStrategy
from .position_intraday_pnl import PositionIntradayPnlStrategy
from .market_index_alert import MarketIndexAlertStrategy

__all__ = [
    "BaseStrategy",
    "LimitOpenStrategy",
    "PriceChangeStrategy",
    "IntradayPriceMoveStrategy",
    "MA5BuyStrategy",
    "SupportResistanceStrategy",
    "FixedStopLossStrategy",
    "TrailingStopLossStrategy",
    "PositionPnlStrategy",
    "PositionIntradayPnlStrategy",
    "MarketIndexAlertStrategy",
]
