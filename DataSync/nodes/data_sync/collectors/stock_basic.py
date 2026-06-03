"""兼容旧导入路径：转发到 `collectors.stock.basic`。"""

from .stock.basic import StockBasicCollector

__all__ = ["StockBasicCollector"]
