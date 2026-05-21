"""
修复北交所股票被误写成 .SZ 的 ts_code。

当前主要针对 92 开头的北交所股票，例如：
- 920092.SZ -> 920092.BJ

会同步修复核心行情表和常见业务引用字段，避免继续影响后续补数和页面查询。

用法:
    cd AgentServer
    venv/bin/python scripts/fix_bj_exchange_suffix.py
    venv/bin/python scripts/fix_bj_exchange_suffix.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager


CORE_TS_CODE_COLLECTIONS = (
    "stock_basic",
    "stock_daily",
    "daily_basic",
    "limit_list",
    "stock_relations",
)


def _build_new_ts_code(old_ts_code: str) -> str:
    code = str(old_ts_code or "").split(".", 1)[0].strip().upper()
    return f"{code}.BJ"


async def _find_wrong_bj_codes() -> List[Tuple[str, str]]:
    records = await mongo_manager.find_many(
        "stock_basic",
        {
            "$or": [
                {"ts_code": {"$regex": r"^92\d{4}\.SZ$"}},
                {"symbol": {"$regex": r"^92\d{4}$"}, "ts_code": {"$regex": r"\.SZ$"}},
            ]
        },
        projection={"ts_code": 1, "symbol": 1, "name": 1, "market": 1, "_id": 0},
    )

    mappings: List[Tuple[str, str]] = []
    for item in records:
        old_ts_code = str(item.get("ts_code") or "").strip().upper()
        if not old_ts_code:
            continue
        new_ts_code = _build_new_ts_code(old_ts_code)
        if old_ts_code != new_ts_code:
            mappings.append((old_ts_code, new_ts_code))
    return sorted(set(mappings))


async def _fix_core_collections(mappings: List[Tuple[str, str]], dry_run: bool) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for collection in CORE_TS_CODE_COLLECTIONS:
        updated = 0
        for old_ts_code, new_ts_code in mappings:
            if dry_run:
                updated += await mongo_manager.count(collection, {"ts_code": old_ts_code})
                continue

            payload: Dict[str, Any] = {"ts_code": new_ts_code}
            if collection == "stock_basic":
                payload["market"] = "北交所"
                payload["updated_at"] = datetime.utcnow()

            result = await mongo_manager._db[collection].update_many(  # type: ignore[attr-defined]
                {"ts_code": old_ts_code},
                {"$set": payload},
            )
            updated += int(result.modified_count)
        stats[collection] = updated
    return stats


async def _fix_users_watchlist(mappings: List[Tuple[str, str]], dry_run: bool) -> int:
    users = await mongo_manager.find_many(
        "users",
        {"watchlist": {"$exists": True, "$ne": []}},
        projection={"user_id": 1, "watchlist": 1, "_id": 0},
    )
    updated = 0
    mapping_dict = dict(mappings)
    for user in users:
        watchlist = [str(code or "").strip().upper() for code in user.get("watchlist", [])]
        new_watchlist = [mapping_dict.get(code, code) for code in watchlist]
        if new_watchlist == watchlist:
            continue
        updated += 1
        if not dry_run:
            await mongo_manager.update_one(
                "users",
                {"user_id": user["user_id"]},
                {"$set": {"watchlist": new_watchlist}},
            )
    return updated


async def _fix_tasks(mappings: List[Tuple[str, str]], dry_run: bool) -> int:
    tasks = await mongo_manager.find_many(
        "tasks",
        {
            "$or": [
                {"ts_codes": {"$exists": True, "$ne": []}},
                {"stock_names.ts_code": {"$exists": True}},
            ]
        },
        projection={"task_id": 1, "ts_codes": 1, "stock_names": 1, "_id": 0},
    )
    updated = 0
    mapping_dict = dict(mappings)
    for task in tasks:
        changed = False
        ts_codes = [mapping_dict.get(str(code or "").strip().upper(), str(code or "").strip().upper()) for code in task.get("ts_codes", [])]
        stock_names = []
        for item in task.get("stock_names", []) or []:
            entry = dict(item)
            ts_code = str(entry.get("ts_code") or "").strip().upper()
            new_ts_code = mapping_dict.get(ts_code, ts_code)
            if new_ts_code != ts_code:
                entry["ts_code"] = new_ts_code
                changed = True
            stock_names.append(entry)
        if ts_codes != task.get("ts_codes", []):
            changed = True
        if not changed:
            continue
        updated += 1
        if not dry_run:
            await mongo_manager.update_one(
                "tasks",
                {"task_id": task["task_id"]},
                {"$set": {"ts_codes": ts_codes, "stock_names": stock_names}},
            )
    return updated


async def _fix_stock_pools(mappings: List[Tuple[str, str]], dry_run: bool) -> int:
    pools = await mongo_manager.find_many(
        "stock_pools",
        {"stocks.ts_code": {"$exists": True}},
        projection={"pool_id": 1, "stocks": 1, "_id": 0},
    )
    updated = 0
    mapping_dict = dict(mappings)
    for pool in pools:
        stocks = []
        changed = False
        for item in pool.get("stocks", []) or []:
            entry = dict(item)
            ts_code = str(entry.get("ts_code") or "").strip().upper()
            new_ts_code = mapping_dict.get(ts_code, ts_code)
            if new_ts_code != ts_code:
                entry["ts_code"] = new_ts_code
                changed = True
            stocks.append(entry)
        if not changed:
            continue
        updated += 1
        if not dry_run:
            await mongo_manager.update_one(
                "stock_pools",
                {"pool_id": pool["pool_id"]},
                {"$set": {"stocks": stocks, "updated_at": datetime.utcnow()}},
            )
    return updated


async def _fix_strategy_subscriptions(mappings: List[Tuple[str, str]], dry_run: bool) -> int:
    records = await mongo_manager.find_many(
        "strategy_subscriptions",
        {"watch_list": {"$exists": True}},
        projection={"subscription_id": 1, "watch_list": 1, "params": 1, "_id": 0},
    )
    updated = 0
    mapping_dict = dict(mappings)
    for record in records:
        changed = False
        watch_list = [mapping_dict.get(str(code or "").strip().upper(), str(code or "").strip().upper()) for code in record.get("watch_list", [])]

        params = dict(record.get("params", {}) or {})
        stock_configs = dict(params.get("stock_configs", {}) or {})
        new_stock_configs: Dict[str, Any] = {}
        for ts_code, config in stock_configs.items():
            normalized = str(ts_code or "").strip().upper()
            mapped = mapping_dict.get(normalized, normalized)
            if mapped != normalized:
                changed = True
            new_stock_configs[mapped] = config

        if watch_list != record.get("watch_list", []):
            changed = True
        if not changed:
            continue

        updated += 1
        if not dry_run:
            params["stock_configs"] = new_stock_configs
            await mongo_manager.update_one(
                "strategy_subscriptions",
                {"subscription_id": record["subscription_id"]},
                {"$set": {"watch_list": watch_list, "params": params, "updated_at": datetime.utcnow()}},
            )
    return updated


async def main() -> None:
    parser = argparse.ArgumentParser(description="修复被误写为 .SZ 的北交所 ts_code")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不实际写库")
    args = parser.parse_args()

    await mongo_manager.initialize()
    try:
        mappings = await _find_wrong_bj_codes()
        if not mappings:
            print("没有发现需要修复的北交所错后缀代码。")
            return

        print("待修复映射：")
        for old_ts_code, new_ts_code in mappings:
            print(f"  {old_ts_code} -> {new_ts_code}")

        core_stats = await _fix_core_collections(mappings, args.dry_run)
        users_updated = await _fix_users_watchlist(mappings, args.dry_run)
        tasks_updated = await _fix_tasks(mappings, args.dry_run)
        pools_updated = await _fix_stock_pools(mappings, args.dry_run)
        subscriptions_updated = await _fix_strategy_subscriptions(mappings, args.dry_run)

        print("\n修复统计：")
        for collection, count in core_stats.items():
            print(f"  {collection}: {count}")
        print(f"  users.watchlist: {users_updated}")
        print(f"  tasks: {tasks_updated}")
        print(f"  stock_pools: {pools_updated}")
        print(f"  strategy_subscriptions: {subscriptions_updated}")
        print(f"\n模式: {'dry-run' if args.dry_run else 'apply'}")
    finally:
        await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
