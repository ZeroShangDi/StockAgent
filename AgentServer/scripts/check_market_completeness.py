"""检查本地股票数据库完整性（覆盖率/最新交易日）。

输出：
- stock_basic 总量（含上市数）
- 以“数据源最新交易日”为基准，统计 stock_daily / daily_basic / index_daily 覆盖数量
- 同时打印各集合自身的最新 trade_date（用于发现数据日期落后）
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import data_source_manager, mongo_manager


async def _latest_trade_date_in_collection(collection: str) -> Optional[str]:
    doc = await mongo_manager.find_one(collection, {}, sort=[("trade_date", -1)])
    if not doc:
        return None
    return doc.get("trade_date")


async def main() -> None:
    expected_latest_trade_date: Optional[str] = None
    expected_latest_trade_source: Optional[str] = None
    try:
        await asyncio.wait_for(data_source_manager.initialize(), timeout=5.0)
        expected_latest_trade_date, expected_latest_trade_source = await data_source_manager.get_latest_trade_date()
    except Exception:
        # 数据源不可用时不终止：仍可用本地库自身最新日期做粗略诊断
        expected_latest_trade_date = None
        expected_latest_trade_source = None

    try:
        await asyncio.wait_for(mongo_manager.initialize(), timeout=3.0)
    except Exception as exc:
        print("=== Market DB completeness (local MongoDB) ===")
        if expected_latest_trade_date:
            print(
                f"Expected latest trade date (data source): {expected_latest_trade_date} "
                f"(source={expected_latest_trade_source or 'unknown'})"
            )
            print()
        print("MongoDB unavailable: failed to connect/ping.")
        print(f"Error: {exc!r}")
        print()
        print("Hint: If running inside a restricted sandbox, localhost:27017 may be blocked.")
        print()
        logs_dir = Path(__file__).parent.parent / "logs"
        if logs_dir.exists():
            candidates = sorted(
                logs_dir.glob("market_sync_*.log"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            if candidates:
                latest = candidates[0]
                stat = latest.stat()
                age_seconds = max(0.0, time.time() - stat.st_mtime)
                print("Sync inference (ps may be blocked):")
                print(f"  latest market sync log: {latest.name} (size={stat.st_size} bytes)")
                print(f"  last modified: {latest.stat().st_mtime:.0f} (epoch seconds)")
                print(f"  freshness: ~{age_seconds/60:.1f} minutes ago (rough)")
                print("  sync_running_guess: maybe" if age_seconds < 10 * 60 else "  sync_running_guess: no")
            else:
                print("Sync inference (ps may be blocked):")
                print("  no market_sync_*.log found under logs/")
        try:
            await data_source_manager.shutdown()
        except Exception:
            pass
        return

    stock_basic_total = await mongo_manager.count("stock_basic", {})
    listed_stock_total = await mongo_manager.count("stock_basic", {"list_status": "L"})
    if listed_stock_total <= 0:
        listed_stock_total = stock_basic_total

    stock_daily_latest = await _latest_trade_date_in_collection("stock_daily")
    daily_basic_latest = await _latest_trade_date_in_collection("daily_basic")
    index_daily_latest = await _latest_trade_date_in_collection("index_daily")

    stock_daily_covered = (
        len(await mongo_manager.db["stock_daily"].distinct("ts_code", {"trade_date": expected_latest_trade_date}))
        if expected_latest_trade_date
        else 0
    )
    daily_basic_covered = (
        len(await mongo_manager.db["daily_basic"].distinct("ts_code", {"trade_date": expected_latest_trade_date}))
        if expected_latest_trade_date
        else 0
    )
    index_daily_covered = (
        len(await mongo_manager.db["index_daily"].distinct("ts_code", {"trade_date": expected_latest_trade_date}))
        if expected_latest_trade_date
        else 0
    )

    def _pct(part: int, total: int) -> float:
        return (part / total) if total > 0 else 0.0

    print("=== Market DB completeness (local MongoDB) ===")
    print(
        f"Expected latest trade date (data source): {expected_latest_trade_date or 'N/A'}"
        + (f" (source={expected_latest_trade_source or 'unknown'})" if expected_latest_trade_date else "")
    )
    print()
    print(f"stock_basic total: {stock_basic_total} (listed: {listed_stock_total})")
    print()
    print("Latest trade_date per collection (actual local data):")
    print(f"  stock_daily: {stock_daily_latest or 'N/A'}")
    print(f"  daily_basic: {daily_basic_latest or 'N/A'}")
    print(f"  index_daily: {index_daily_latest or 'N/A'}")
    print()
    print(f"Coverage on {expected_latest_trade_date} (distinct ts_code):")
    print(f"  stock_daily: {stock_daily_covered} ({_pct(stock_daily_covered, listed_stock_total):.1%})")
    print(f"  daily_basic: {daily_basic_covered} ({_pct(daily_basic_covered, listed_stock_total):.1%})")
    print(f"  index_daily: {index_daily_covered}")

    try:
        await data_source_manager.shutdown()
    except Exception:
        pass
    await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
