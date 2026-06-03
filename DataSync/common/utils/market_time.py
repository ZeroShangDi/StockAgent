"""
中国市场时间工具。

统一使用 Asia/Shanghai，避免部署在 UTC 服务器时盘中逻辑误判。
"""

from datetime import datetime, date
from zoneinfo import ZoneInfo


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def market_now(value: datetime | None = None) -> datetime:
    """返回上海时区当前时间，或把给定时间转换到上海时区。"""
    if value is None:
        return datetime.now(MARKET_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=MARKET_TIMEZONE)
    return value.astimezone(MARKET_TIMEZONE)


def market_today() -> date:
    """返回上海时区下的当前日期。"""
    return market_now().date()


def market_today_str() -> str:
    """返回上海时区下的当前日期字符串 YYYYMMDD。"""
    return market_now().strftime("%Y%m%d")
