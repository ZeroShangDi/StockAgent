"""Backfill daily_stats, market_statistics_cache, and market_weather for all 2026 dates."""
import asyncio
import logging
import sys
from datetime import UTC, datetime

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("backfill")

async def backfill_daily_stats():
    """Backfill daily_stats for all missing 2026 dates."""
    from core.managers.data_source_manager import data_source_manager
    from core.managers.mongo_manager import mongo_manager
    from nodes.data_sync.tasks.daily_stats import DailyStatsTask

    await data_source_manager.initialize()
    await mongo_manager.initialize()

    task = DailyStatsTask()

    # Get all trade dates in 2026
    trade_dates, _ = await data_source_manager.get_trade_calendar("20260101", "20260620")
    if not trade_dates:
        print("No trade dates found")
        return

    # Get existing daily_stats dates
    existing = await mongo_manager._db["daily_stats"].distinct("trade_date")
    existing_set = set(existing)

    missing = sorted([d for d in trade_dates if d not in existing_set])
    print(f"daily_stats: {len(trade_dates)} trade dates, {len(existing)} existing, {len(missing)} missing")

    if not missing:
        print("daily_stats: All caught up!")
        return

    success = 0
    failed = []
    for i, trade_date in enumerate(missing):
        try:
            result = await task._compute_single_day(trade_date, force=True)
            await mongo_manager.record_sync(sync_type="daily_stats", sync_date=trade_date, count=1)
            success += 1
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i+1}/{len(missing)} ({success} ok)")
            sys.stdout.flush()
        except Exception as e:
            failed.append((trade_date, str(e)))
            print(f"  FAILED {trade_date}: {e}")

    print(f"daily_stats done: {success} ok, {len(failed)} failed")
    for dt, err in failed[:5]:
        print(f"  {dt}: {err}")

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()


async def backfill_market_weather():
    """Backfill market_weather for all 2026 dates using Coze API."""
    from core.managers.data_source_manager import data_source_manager
    from core.managers.mongo_manager import mongo_manager
    from src.analysis.market_weather import market_weather_service

    await data_source_manager.initialize()
    await mongo_manager.initialize()

    # Get all trade dates in 2026
    trade_dates, _ = await data_source_manager.get_trade_calendar("20260101", "20260620")
    if not trade_dates:
        print("No trade dates found")
        return

    # Get existing market_weather dates
    collection = market_weather_service.COLLECTION if hasattr(market_weather_service, 'COLLECTION') else "market_weather_daily"
    existing = await mongo_manager._db[collection].distinct("trade_date")
    existing_set = set(existing)

    missing = sorted([d for d in trade_dates if d not in existing_set])
    print(f"market_weather: {len(trade_dates)} trade dates, {len(existing)} existing, {len(missing)} missing")

    if not missing:
        print("market_weather: All caught up!")
        return

    # Sync in batches to avoid overwhelming Coze API
    batch_size = 5
    success = 0
    failed = []

    for i in range(0, len(missing), batch_size):
        batch = missing[i:i+batch_size]
        try:
            result = await market_weather_service.sync_trade_dates(batch, overwrite=True)
            ok = result.get("success", 0)
            success += ok
            print(f"  Batch {i//batch_size+1}: dates={batch}, ok={ok}")
        except Exception as e:
            failed.extend([(d, str(e)) for d in batch])
            print(f"  Batch FAILED: {e}")

        # Small delay between batches
        if i + batch_size < len(missing):
            await asyncio.sleep(1)

    print(f"market_weather done: {success} ok, {len(failed)} failed")

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()


async def backfill_market_statistics_cache():
    """Backfill market_statistics_cache for missing 2026 dates."""
    from core.managers.data_source_manager import data_source_manager
    from core.managers.mongo_manager import mongo_manager
    from nodes.data_sync.tasks.market_statistics_cache import MarketStatisticsCacheTask

    await data_source_manager.initialize()
    await mongo_manager.initialize()

    task = MarketStatisticsCacheTask()

    # Get all trade dates in 2026
    trade_dates, _ = await data_source_manager.get_trade_calendar("20260101", "20260620")
    if not trade_dates:
        print("No trade dates found")
        return

    # Get existing cache dates
    existing = await mongo_manager._db["market_statistics_cache"].distinct("trade_date")
    existing_set = set(existing)

    missing = sorted([d for d in trade_dates if d not in existing_set])
    print(f"market_statistics_cache: {len(trade_dates)} trade dates, {len(existing)} existing, {len(missing)} missing")

    if not missing:
        print("market_statistics_cache: All caught up!")
        return

    success = 0
    failed = []
    for i, trade_date in enumerate(missing):
        try:
            # Check if daily_stats exists for this date (required dependency)
            daily_stats_doc = await mongo_manager.find_one("daily_stats", {"trade_date": trade_date})
            if not daily_stats_doc:
                print(f"  SKIP {trade_date}: no daily_stats yet")
                continue

            count = await task._build_for_trade_date(trade_date)
            if count > 0:
                success += 1
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i+1}/{len(missing)} ({success} ok)")
        except Exception as e:
            failed.append((trade_date, str(e)))
            print(f"  FAILED {trade_date}: {e}")

    print(f"market_statistics_cache done: {success} ok, {len(failed)} failed")

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()


async def main():
    print("=" * 60)
    print("Starting backfill for derived data...")
    print("=" * 60)

    # Phase 1: daily_stats (base dependency)
    print("\n[Phase 1] Backfilling daily_stats...")
    await backfill_daily_stats()

    # Phase 2: market_statistics_cache (depends on daily_stats)
    print("\n[Phase 2] Backfilling market_statistics_cache...")
    await backfill_market_statistics_cache()

    # Phase 3: market_weather (depends on Coze API)
    print("\n[Phase 3] Backfilling market_weather...")
    await backfill_market_weather()

    print("\n" + "=" * 60)
    print("Backfill complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
