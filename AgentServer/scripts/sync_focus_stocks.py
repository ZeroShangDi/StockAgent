"""
同步重点股票到本地数据库。

重点股票来源：
- users.watchlist
- strategy_subscriptions.watch_list（仅激活策略）

适用场景：
- Tushare 权限不足，无法稳定做全市场同步
- 希望先保证自选股、监听股在本地有 stock_daily / daily_basic 缓存
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import data_source_manager, mongo_manager
from nodes.data_sync.collectors.stock.daily_basic import _clean_daily_basic_record
from nodes.data_sync.collectors.stock.focus_universe import get_focus_stock_codes


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步重点股票（自选股 + 监听股）")
    parser.add_argument("--start", type=str, default=None, help="开始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, default=None, help="结束日期 YYYYMMDD，默认今天")
    parser.add_argument("--days", type=int, default=30, help="最近 N 天，默认 30")
    parser.add_argument("--limit", type=int, default=None, help="最多同步多少只重点股票")
    parser.add_argument("--skip-daily-basic", action="store_true", help="只同步 stock_daily")
    args = parser.parse_args()

    end_date = args.end or datetime.now().strftime("%Y%m%d")
    if args.start:
        start_date = args.start
    else:
        start_date = (datetime.now() - timedelta(days=max(args.days, 1))).strftime("%Y%m%d")

    await mongo_manager.initialize()
    await data_source_manager.initialize()

    ts_codes = await get_focus_stock_codes(args.limit)
    if not ts_codes:
        print("没有找到重点股票。请先添加自选股或监听股票。")
        return

    print(f"同步范围: {start_date} -> {end_date}")
    print(f"重点股票数: {len(ts_codes)}")
    print(f"股票列表: {', '.join(ts_codes)}")

    stock_daily_total = 0
    daily_basic_total = 0

    for index, ts_code in enumerate(ts_codes, 1):
        daily_records, daily_source = await data_source_manager.get_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        if daily_records:
            result = await mongo_manager.bulk_upsert(
                collection="stock_daily",
                documents=daily_records,
                key_fields=["ts_code", "trade_date"],
                batch_size=1000,
            )
            count = result["upserted"] + result["modified"]
            stock_daily_total += count
            print(f"[{index}/{len(ts_codes)}] stock_daily {ts_code}: {count} 条, source={daily_source or 'unknown'}")
        else:
            print(f"[{index}/{len(ts_codes)}] stock_daily {ts_code}: 无数据")

        if args.skip_daily_basic:
            continue

        basic_records, basic_source = await data_source_manager.get_daily_basic(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        if basic_records:
            cleaned_records = []
            for record in basic_records:
                cleaned = _clean_daily_basic_record(record)
                cleaned["updated_at"] = datetime.now(UTC)
                cleaned_records.append(cleaned)
            result = await mongo_manager.bulk_upsert(
                collection="daily_basic",
                documents=cleaned_records,
                key_fields=["ts_code", "trade_date"],
                batch_size=1000,
            )
            count = result["upserted"] + result["modified"]
            daily_basic_total += count
            print(f"[{index}/{len(ts_codes)}] daily_basic {ts_code}: {count} 条, source={basic_source or 'unknown'}")
        else:
            print(f"[{index}/{len(ts_codes)}] daily_basic {ts_code}: 无数据")

    print("")
    print(f"完成: stock_daily={stock_daily_total}, daily_basic={daily_basic_total}")

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
