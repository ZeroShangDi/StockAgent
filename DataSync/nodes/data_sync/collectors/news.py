"""兼容旧导入路径：统一转发到当前的股票新闻采集实现。"""

from .news.stock_news import StockNewsCollector


class NewsCollector(StockNewsCollector):
    """兼容旧类名，保留旧任务标识。"""

    name = "news"


__all__ = ["NewsCollector"]
