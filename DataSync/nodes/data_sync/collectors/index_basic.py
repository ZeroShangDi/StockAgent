"""兼容旧导入路径：转发到 `collectors.stock.index_basic`。"""

from .stock.index_basic import IndexBasicCollector

__all__ = ["IndexBasicCollector"]
