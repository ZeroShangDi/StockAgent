"""DataSync 的最小新闻采集共享类型包。

当前仅为 `nodes/data_sync/collectors/news/sources/*` 提供稳定导入面，
不在这里重新暴露旧版完整新闻采集框架。
"""

from .types import (
    CollectResult,
    NewsCategory,
    NewsItem,
    NewsSource,
)
from .sources import BaseSource

__all__ = [
    "CollectResult",
    "NewsCategory",
    "NewsItem",
    "NewsSource",
    "BaseSource",
]
