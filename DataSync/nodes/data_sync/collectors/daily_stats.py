"""兼容旧导入路径：统一转发到当前的每日统计任务实现。"""

from ..tasks.daily_stats import DailyStatsTask


class DailyStatsCollector(DailyStatsTask):
    """兼容旧类名，实际执行逻辑复用当前 DailyStatsTask。"""


__all__ = ["DailyStatsCollector"]
