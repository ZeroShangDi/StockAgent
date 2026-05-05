"""检查同步状态（增量同步起点 + 各集合最新日期）。

在受限环境（例如 sandbox）里，MongoDB 或外部数据源可能不可用；
此脚本会尽量给出“最新交易日（来自可用数据源）”并提示阻塞原因。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import data_source_manager, mongo_manager


async def main() -> None:
    latest_trade_date = None
    latest_source = None
    try:
        await asyncio.wait_for(data_source_manager.initialize(), timeout=8.0)
        latest_trade_date, latest_source = await data_source_manager.get_latest_trade_date()
    except Exception as exc:
        print("Data source unavailable: failed to get latest trade date.")
        print(f"Error: {exc!r}")

    if latest_trade_date:
        print(f"=== Latest trade date (data source): {latest_trade_date} (source={latest_source or 'unknown'}) ===\n")
    else:
        print("=== Latest trade date (data source): N/A ===\n")

    try:
        await asyncio.wait_for(mongo_manager.initialize(), timeout=3.0)
    except Exception as exc:
        print("MongoDB unavailable: failed to connect/ping.")
        print(f"Error: {exc!r}")
        print()
        print("Hint: If running inside a restricted sandbox, localhost:27017 may be blocked.")
        try:
            await data_source_manager.shutdown()
        except Exception:
            pass
        return
    
    print("=== sync_records (控制增量同步的起点) ===")
    records = await mongo_manager.find_many("sync_records", {})
    if records:
        for doc in records:
            sync_type = doc.get('sync_type', 'unknown')
            sync_date = doc.get('sync_date', 'N/A')
            need_sync = sync_date < latest_trade_date if sync_date != 'N/A' else True
            status = "需要同步" if need_sync else "已是最新"
            print(f"  {sync_type}: {sync_date} ({status})")
    else:
        print("  (空)")
    
    print()
    print("=== Latest dates per collection (实际数据) ===")
    for col in ["stock_daily", "index_daily", "limit_list", "daily_stats", "market_analysis"]:
        doc = await mongo_manager.find_one(col, {}, sort=[("trade_date", -1)])
        if doc:
            actual_date = doc.get('trade_date', 'N/A')
            match = "✓" if actual_date >= latest_trade_date else f"⚠ 缺失 {actual_date} -> {latest_trade_date}"
            print(f"  {col}: {actual_date} {match}")
        else:
            print(f"  {col}: no data")
    
    await data_source_manager.shutdown()
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
