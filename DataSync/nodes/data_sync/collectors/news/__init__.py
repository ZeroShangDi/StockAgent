"""
新闻采集器

采集财经新闻、政策文件、热点事件等。

注意:
- 事件聚类已迁移到 tasks/event_clustering.py
- 生命周期管理已迁移到 tasks/news_lifecycle.py
"""

from .stock_news import StockNewsCollector
from .hot_news import HotNewsCollector


class NewsCollector(StockNewsCollector):
    """兼容旧类名，保留旧任务标识。"""

    name = "news"

__all__ = [
    # 新闻采集
    "NewsCollector",               # 兼容旧入口
    "StockNewsCollector",          # 涨跌停股票新闻 (AKShare)
    "HotNewsCollector",            # 热点新闻看板
]
