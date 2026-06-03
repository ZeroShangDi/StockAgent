"""
处理任务

数据处理、聚类、统计、清理等非采集类任务。
"""

from .daily_stats import DailyStatsTask
from .market_statistics_cache import MarketStatisticsCacheTask
from .market_weather import MarketWeatherTask


__all__ = [
    "DailyStatsTask",
    "MarketStatisticsCacheTask",
    "MarketWeatherTask",
]
