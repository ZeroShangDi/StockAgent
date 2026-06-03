"""兼容旧导入路径：转发到 `collectors.stock.moneyflow_industry`。"""

from .stock.moneyflow_industry import MoneyflowIndustryCollector

__all__ = ["MoneyflowIndustryCollector"]
