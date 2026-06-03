"""MongoDB 全局模型导出。

按需加载，避免 DataSync 导入模型包时顺手带入用户认证相关依赖。
"""


def __getattr__(name: str):
    if name in {"User", "UserInDB"}:
        from common.models.user import User, UserInDB

        exports = {
            "User": User,
            "UserInDB": UserInDB,
        }
        return exports[name]

    if name in {"Stock", "StockDaily", "StockFinancial"}:
        from common.models.stock import Stock, StockDaily, StockFinancial

        exports = {
            "Stock": Stock,
            "StockDaily": StockDaily,
            "StockFinancial": StockFinancial,
        }
        return exports[name]

    if name in {"Strategy", "StrategyResult", "AnalysisTask"}:
        from common.models.strategy import Strategy, StrategyResult, AnalysisTask

        exports = {
            "Strategy": Strategy,
            "StrategyResult": StrategyResult,
            "AnalysisTask": AnalysisTask,
        }
        return exports[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "User",
    "UserInDB",
    "Stock",
    "StockDaily",
    "StockFinancial",
    "Strategy",
    "StrategyResult",
    "AnalysisTask",
]
