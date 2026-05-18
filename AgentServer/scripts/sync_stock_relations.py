"""
手动同步股票关联关系。

用法:
    venv/bin/python scripts/sync_stock_relations.py
    venv/bin/python scripts/sync_stock_relations.py --trade-date 20260515
"""

from __future__ import annotations

import argparse
import asyncio
import json

from core.managers import mongo_manager, stock_relation_manager


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步股票关联关系")
    parser.add_argument("--trade-date", help="指定 limit_list 快照日期 (YYYYMMDD)")
    args = parser.parse_args()

    await mongo_manager.initialize()
    await stock_relation_manager.initialize()

    try:
        result = await stock_relation_manager.sync_relations(snapshot_trade_date=args.trade_date)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await stock_relation_manager.shutdown()
        await mongo_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
