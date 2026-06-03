"""
分析模块。

注意：此处避免做重量级或历史遗留依赖的包级导入，防止脚本和 API 在导入子模块时被无关依赖阻塞。
"""

from typing import Any

__all__ = [
    "StockLinkageAnalyzer",
    "StockRole",
]


def __getattr__(name: str) -> Any:
    if name in {"StockLinkageAnalyzer", "StockRole"}:
        from .stock_linkage import StockLinkageAnalyzer, StockRole

        return {
            "StockLinkageAnalyzer": StockLinkageAnalyzer,
            "StockRole": StockRole,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
