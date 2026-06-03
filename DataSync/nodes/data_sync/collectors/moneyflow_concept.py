"""兼容旧导入路径：转发到 `collectors.stock.moneyflow_concept`。"""

from .stock.moneyflow_concept import MoneyflowConceptCollector

__all__ = ["MoneyflowConceptCollector"]
