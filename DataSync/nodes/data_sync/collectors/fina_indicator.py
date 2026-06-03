"""兼容旧导入路径：转发到 `collectors.stock.fina_indicator`。"""

from .stock.fina_indicator import FinaIndicatorCollector

__all__ = ["FinaIndicatorCollector"]
