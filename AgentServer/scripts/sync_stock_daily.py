"""
手动同步指定日期范围的 stock_daily 数据

用法:
    cd AgentServer
    
    # 同步单个日期
    python scripts/sync_stock_daily.py --date 20260106
    
    # 同步时间段
    python scripts/sync_stock_daily.py --start 20260106 --end 20260109
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime
from typing import Optional

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager, data_source_manager


RATE_LIMIT_ERROR_KEYWORDS = (
    "429",
    "rate limit",
    "too many requests",
    "frequency",
    "limit exceeded",
    "访问过于频繁",
    "频次",
    "限频",
    "请稍后",
)


def _is_rate_limit_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(keyword in lowered for keyword in RATE_LIMIT_ERROR_KEYWORDS)


async def get_trade_dates_in_range(start_date: str, end_date: str) -> list:
    """获取指定范围内的交易日"""
    dates, _ = await data_source_manager.get_trade_calendar(start_date, end_date)
    return sorted(dates) if dates else []


async def sync_stock_daily_for_date(trade_date: str, batch_size: int = 500) -> dict:
    """
    同步指定日期的 stock_daily 数据
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)
        batch_size: 每批处理的股票数量
        
    Returns:
        同步结果统计
    """
    print(f"\n{'='*60}")
    print(f"Syncing stock_daily for {trade_date}")
    print(f"{'='*60}")
    
    # 增量同步按交易日整市场抓取，避免按股票循环触发 Tushare 限流
    records, source = await data_source_manager.get_daily(trade_date=trade_date)

    if not records:
        print(f"  No data returned for {trade_date}, treated as failure")
        return {"date": trade_date, "count": 0, "status": "failed", "error": "empty_records"}

    result = await mongo_manager.bulk_upsert(
        collection="stock_daily",
        documents=records,
        key_fields=["ts_code", "trade_date"],
    )

    count = result.get("upserted", 0) + result.get("modified", 0)
    print(
        f"  Synced {count} records from {source or 'unknown'} "
        f"(upserted={result.get('upserted', 0)}, modified={result.get('modified', 0)})"
    )
    return {"date": trade_date, "count": count, "status": "ok", "source": source}


async def sync_index_daily_for_date(trade_date: str) -> dict:
    """同步指定日期的 index_daily 数据"""
    print(f"\nSyncing index_daily for {trade_date}...")
    
    # 主要指数列表
    index_codes = [
        "000001.SH",  # 上证指数
        "399001.SZ",  # 深证成指
        "399006.SZ",  # 创业板指
        "000016.SH",  # 上证50
        "000300.SH",  # 沪深300
        "000905.SH",  # 中证500
        "000688.SH",  # 科创50
    ]
    
    all_records = []
    
    # 逐个获取每个指数的数据（有些API不支持批量查询）
    for ts_code in index_codes:
        try:
            records, _ = await data_source_manager.get_index_daily(
                ts_code=ts_code,
                start_date=trade_date,
                end_date=trade_date,
            )
            
            if records:
                all_records.extend(records)
                print(f"    {ts_code}: OK")
            else:
                print(f"    {ts_code}: no data")
        except Exception as e:
            print(f"    {ts_code}: error - {e}")
    
    if not all_records:
        print(f"  No index data for {trade_date}")
        return {"date": trade_date, "count": 0}
    
    result = await mongo_manager.bulk_upsert(
        collection="index_daily",
        documents=all_records,
        key_fields=["ts_code", "trade_date"],
    )
    
    count = result.get("upserted", 0) + result.get("modified", 0)
    print(f"  Synced {count} index records")
    return {"date": trade_date, "count": count}


async def sync_limit_list_for_date(trade_date: str) -> dict:
    """同步指定日期的涨跌停数据"""
    print(f"\nSyncing limit_list for {trade_date}...")
    
    records, _ = await data_source_manager.get_limit_list(trade_date=trade_date)
    
    if not records:
        print(f"  No limit_list data for {trade_date}")
        return {"date": trade_date, "count": 0}
    
    result = await mongo_manager.bulk_upsert(
        collection="limit_list",
        documents=records,
        key_fields=["ts_code", "trade_date"],
    )
    
    count = result.get("upserted", 0) + result.get("modified", 0)
    print(f"  Synced {count} limit records")
    return {"date": trade_date, "count": count}


async def main(args):
    print("=" * 60)
    print("Stock Daily Data Sync Script")
    print("=" * 60)
    
    # 初始化
    await mongo_manager.initialize()
    await data_source_manager.initialize()
    
    # 确定日期范围
    if args.date:
        trade_dates = [args.date]
    elif args.start and args.end:
        trade_dates = await get_trade_dates_in_range(args.start, args.end)
    else:
        print("Error: Please specify --date or --start/--end")
        return
    
    if not trade_dates:
        print("No trading dates found in the specified range")
        return
    
    print(f"\nWill sync {len(trade_dates)} trading days: {trade_dates[0]} ~ {trade_dates[-1]}")
    
    # 同步每个日期
    results = []
    failed_dates = []
    aborted_reason: Optional[str] = None
    for trade_date in trade_dates:
        try:
            result = await sync_stock_daily_for_date(trade_date)
        except Exception as exc:
            result = {"date": trade_date, "count": 0, "status": "failed", "error": str(exc)}

        results.append(result)
        if result["status"] != "ok":
            failed_dates.append(trade_date)
            print(f"  ❌ {trade_date}: {result.get('error', 'unknown_error')}")
            if _is_rate_limit_error(result.get("error", "")):
                aborted_reason = f"检测到接口限频/流控错误，任务中止：{result.get('error')}"
                print(f"  ❌ {aborted_reason}")
                break
            if len(failed_dates) >= args.max_failures:
                aborted_reason = f"失败日期已达到阈值 {args.max_failures}，任务中止"
                print(f"  ❌ {aborted_reason}")
                break
        else:
            if not args.skip_index_daily:
                await sync_index_daily_for_date(trade_date)
            
            if not args.skip_limit_list:
                await sync_limit_list_for_date(trade_date)

        if args.sleep_seconds > 0:
            await asyncio.sleep(args.sleep_seconds)
    
    # 汇总
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for r in results:
        status = "✓" if r["status"] == "ok" else "✗"
        print(f"  {status} {r['date']}: {r['count']} records")
    
    total = sum(r["count"] for r in results)
    print(f"\nTotal: {total} records synced")
    print(f"Failed dates: {len(failed_dates)}")
    if aborted_reason:
        print(f"Abort reason: {aborted_reason}")
    
    # 关闭连接
    await mongo_manager.shutdown()
    await data_source_manager.shutdown()
    if failed_dates or aborted_reason:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync stock_daily for specified dates")
    parser.add_argument("--date", type=str, help="Single date to sync (e.g., 20260106)")
    parser.add_argument("--start", type=str, help="Start date of range (e.g., 20260106)")
    parser.add_argument("--end", type=str, help="End date of range (e.g., 20260109)")
    parser.add_argument("--skip-index-daily", action="store_true", help="Skip syncing index_daily")
    parser.add_argument("--skip-limit-list", action="store_true", help="Skip syncing limit_list")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="每个交易日额外休眠秒数，降低接口频次")
    parser.add_argument("--max-failures", type=int, default=3, help="允许的最大失败日期数，超过后立即中止")
    
    args = parser.parse_args()
    
    if not args.date and not (args.start and args.end):
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/sync_stock_daily.py --date 20260106")
        print("  python scripts/sync_stock_daily.py --start 20260106 --end 20260109")
        sys.exit(1)
    
    asyncio.run(main(args))
