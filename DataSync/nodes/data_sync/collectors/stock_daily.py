"""兼容旧导入路径：转发到 `collectors.stock.daily`。"""

from .stock.daily import StockDailyCollector

__all__ = ["StockDailyCollector"]
