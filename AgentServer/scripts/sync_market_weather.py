"""
同步市场晴雨表历史数据。

默认补最近 30 个交易日，可指定具体日期、区间、是否从后往前补，
也可顺手把三大核心指数一起补齐。
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
    parser.add_argument("--start-date", type=str, default=None, help="区间开始日期，支持 YYYYMMDD / YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None, help="区间结束日期，支持 YYYYMMDD / YYYY-MM-DD")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在记录")
    parser.add_argument("--descending", action="store_true", help="按日期从后往前补")
    parser.add_argument("--sleep-seconds", type=float, default=0.35, help="每次请求后的等待秒数")
    parser.add_argument("--stop-on-empty-streak", type=int, default=30, help="连续空结果阈值，达到后停止")
    parser.add_argument("--request-timeout-seconds", type=float, default=12.0, help="单次 Coze 请求超时秒数")
    parser.add_argument("--sync-index", action="store_true", help="同时补三大核心指数")
    args = parser.parse_args()

    await mongo_manager.initialize()
    await data_source_manager.initialize()

    if args.date:
        trade_date = args.date.replace("-", "")
        result = await market_weather_service.sync_trade_dates([trade_date], overwrite=args.overwrite)
    elif args.start_date or args.end_date:
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        start_date = (args.start_date or latest_trade_date).replace("-", "")
        end_date = (args.end_date or latest_trade_date).replace("-", "")
        result = await market_weather_service.sync_range(
            start_date=start_date,
            end_date=end_date,
            overwrite=args.overwrite,
            descending=args.descending,
            sleep_seconds=args.sleep_seconds,
            stop_on_empty_streak=args.stop_on_empty_streak or None,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    else:
        result = await market_weather_service.sync_recent(days=args.days, overwrite=args.overwrite)

    index_result = None
    if args.sync_index:
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        start_date = (args.start_date or args.date or latest_trade_date).replace("-", "")
        end_date = (args.end_date or args.date or latest_trade_date).replace("-", "")
        index_result = {
            "requested": 3,
            "success": 0,
            "failed": 0,
            "rows": 0,
            "errors": [],
        }
        for ts_code in ["000001.SH", "399001.SZ", "399006.SZ"]:
            try:
                records, source = await data_source_manager.get_index_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )
                if records:
                    write_result = await mongo_manager.bulk_upsert(
                        collection="index_daily",
                        documents=records,
                        key_fields=["ts_code", "trade_date"],
                        batch_size=1000,
                    )
                    index_result["rows"] += write_result["upserted"] + write_result["modified"]
                index_result["success"] += 1
                print(f"index {ts_code} synced via {source or '-'}")
            except Exception as exc:
                index_result["failed"] += 1
                index_result["errors"].append({"ts_code": ts_code, "error": str(exc)})

    print("市场晴雨表同步完成")
    print(result)
    if index_result is not None:
        print("核心指数同步完成")
        print(index_result)

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
