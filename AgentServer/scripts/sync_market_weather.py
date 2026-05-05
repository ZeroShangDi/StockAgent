"""
同步市场晴雨表历史数据。

默认补最近 30 个交易日，可指定具体日期或覆盖已存在记录。
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import data_source_manager, mongo_manager
from src.analysis.market_weather import market_weather_service


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步市场晴雨表")
    parser.add_argument("--days", type=int, default=30, help="最近 N 个交易日，默认 30")
    parser.add_argument("--date", type=str, default=None, help="只同步某一天，支持 YYYYMMDD / YYYY-MM-DD")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在记录")
    args = parser.parse_args()

    await mongo_manager.initialize()
    await data_source_manager.initialize()

    if args.date:
        trade_date = args.date.replace("-", "")
        result = await market_weather_service.sync_trade_dates([trade_date], overwrite=args.overwrite)
    else:
        result = await market_weather_service.sync_recent(days=args.days, overwrite=args.overwrite)

    print("市场晴雨表同步完成")
    print(result)

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
