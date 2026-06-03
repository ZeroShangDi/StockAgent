"""兼容旧导入路径：转发到 `collectors.news.hot_news`。"""

from .news.hot_news import HotNewsCollector

__all__ = ["HotNewsCollector"]
