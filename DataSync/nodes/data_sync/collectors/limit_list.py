"""兼容旧导入路径：转发到 `collectors.stock.limit_list`。"""

from .stock.limit_list import LimitListCollector

__all__ = ["LimitListCollector"]
