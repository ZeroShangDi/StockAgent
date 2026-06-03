"""兼容旧导入路径：转发到 `collectors.stock.daily_basic`。"""

from .stock.daily_basic import DailyBasicCollector

__all__ = ["DailyBasicCollector"]
