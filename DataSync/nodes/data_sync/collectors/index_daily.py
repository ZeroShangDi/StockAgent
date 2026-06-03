"""兼容旧导入路径：转发到 `collectors.stock.index_daily`。"""

from .stock.index_daily import IndexDailyCollector

__all__ = ["IndexDailyCollector"]
