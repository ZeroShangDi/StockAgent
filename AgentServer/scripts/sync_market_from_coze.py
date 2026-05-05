"""
使用统一数据源管理器对全市场股票做单股同步。

特点：
- 以 stock_basic 表中的股票池为准
- 单股逐只调用，适配 Coze 的单股请求能力
- 默认断点续跑：若某只股票在结束日期已有数据，则自动跳过
- 自动使用可用数据源，当前源失败时继续降级到其他源
- 可同时同步 stock_daily、daily_basic，以及核心指数 index_daily
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import data_source_manager, mongo_manager
from nodes.data_sync.collectors.stock.daily_basic import _clean_daily_basic_record


async def _has_trade_date_record(collection: str, ts_code: str, trade_date: str) -> bool:
    return await mongo_manager.count(
        collection,
        {"ts_code": ts_code, "trade_date": trade_date},
    ) > 0


async def _load_universe(offset: int, limit: int | None) -> List[str]:
    stocks = await mongo_manager.find_many(
        "stock_basic",
        {"list_status": "L"},
        projection={"ts_code": 1},
        sort=[("ts_code", 1)],
    )
    ts_codes = [stock["ts_code"] for stock in stocks if stock.get("ts_code")]
    if offset > 0:
        ts_codes = ts_codes[offset:]
    if limit is not None:
        ts_codes = ts_codes[:limit]
    return ts_codes


async def main() -> None:
    parser = argparse.ArgumentParser(description="使用统一数据源同步全市场股票数据")
    parser.add_argument("--start", type=str, default=None, help="开始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, default=None, help="结束日期 YYYYMMDD，默认最新交易日")
    parser.add_argument("--days", type=int, default=365, help="最近 N 天，默认 365")
    parser.add_argument("--offset", type=int, default=0, help="从第几只股票开始")
    parser.add_argument("--limit", type=int, default=None, help="最多同步多少只股票")
    parser.add_argument("--concurrent", type=int, default=4, help="并发数，默认 4")
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="输出日志文件路径（默认 logs/market_sync_YYYYMMDD.log）",
    )
    parser.add_argument("--skip-stock-daily", action="store_true", help="跳过 stock_daily")
    parser.add_argument("--skip-daily-basic", action="store_true", help="跳过 daily_basic")
    parser.add_argument("--skip-index-daily", action="store_true", help="跳过 index_daily")
    parser.add_argument("--no-resume", action="store_true", help="关闭断点续跑，强制重拉")
    args = parser.parse_args()

    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    default_log_file = logs_dir / f"market_sync_{datetime.now(UTC).astimezone().strftime('%Y%m%d')}.log"
    log_file = Path(args.log_file) if args.log_file else default_log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_fp = log_file.open("a", encoding="utf-8")

    def _log(line: str = "") -> None:
        print(line)
        log_fp.write(f"{line}\n")
        log_fp.flush()

    _log(f"Log file: {log_file}")
    _log(f"Started at: {datetime.now(UTC).astimezone().isoformat(timespec='seconds')}")

    try:
        await asyncio.wait_for(mongo_manager.initialize(), timeout=5.0)
    except Exception as exc:
        _log(f"MongoDB initialize failed: {exc!r}")
        log_fp.close()
        raise RuntimeError(f"MongoDB 初始化失败（无法连接/鉴权）：{exc}") from exc

    try:
        await asyncio.wait_for(data_source_manager.initialize(), timeout=10.0)
    except Exception as exc:
        await mongo_manager.shutdown()
        log_fp.close()
        raise RuntimeError(f"数据源管理器初始化失败：{exc}") from exc

    latest_trade_date, latest_trade_source = await data_source_manager.get_latest_trade_date()
    end_date = args.end or latest_trade_date
    if not end_date:
        log_fp.close()
        raise RuntimeError("无法获取最新交易日，请检查可用数据源配置")

    if args.start:
        start_date = args.start
    else:
        start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=max(args.days, 1))).strftime("%Y%m%d")

    ts_codes = await _load_universe(args.offset, args.limit)
    if not ts_codes:
        log_fp.close()
        raise RuntimeError("stock_basic 表中没有可同步股票，请先同步股票基础信息")

    _log(f"同步范围: {start_date} -> {end_date}")
    _log(f"股票数量: {len(ts_codes)}")
    _log(f"并发数: {args.concurrent}")
    _log(f"断点续跑: {'关闭' if args.no_resume else '开启'}")
    _log(f"最新交易日来源: {latest_trade_source or 'unknown'}")

    semaphore = asyncio.Semaphore(max(args.concurrent, 1))
    progress = {"done": 0, "daily": 0, "basic": 0, "skipped": 0, "failed": 0}

    async def sync_one(ts_code: str) -> Dict[str, Any]:
        async with semaphore:
            result: Dict[str, Any] = {"ts_code": ts_code, "daily": 0, "basic": 0, "skipped": False}
            try:
                need_daily = not args.skip_stock_daily
                need_basic = not args.skip_daily_basic

                if not args.no_resume:
                    if need_daily and await _has_trade_date_record("stock_daily", ts_code, end_date):
                        need_daily = False
                    if need_basic and await _has_trade_date_record("daily_basic", ts_code, end_date):
                        need_basic = False

                if not need_daily and not need_basic:
                    result["skipped"] = True
                    return result

                if need_daily:
                    daily_records, daily_source = await data_source_manager.get_daily(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if daily_records:
                        write_result = await mongo_manager.bulk_upsert(
                            collection="stock_daily",
                            documents=daily_records,
                            key_fields=["ts_code", "trade_date"],
                            batch_size=1000,
                        )
                        result["daily"] = write_result["upserted"] + write_result["modified"]
                        result["daily_source"] = daily_source

                if need_basic:
                    basic_records, basic_source = await data_source_manager.get_daily_basic(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                        preferred_source="coze",
                    )
                    if basic_records:
                        cleaned_records = []
                        for record in basic_records:
                            cleaned = _clean_daily_basic_record(record)
                            cleaned["updated_at"] = datetime.now(UTC)
                            cleaned_records.append(cleaned)
                        write_result = await mongo_manager.bulk_upsert(
                            collection="daily_basic",
                            documents=cleaned_records,
                            key_fields=["ts_code", "trade_date"],
                            batch_size=1000,
                        )
                        result["basic"] = write_result["upserted"] + write_result["modified"]
                        result["basic_source"] = basic_source
                return result
            except Exception as exc:
                result["error"] = str(exc)
                return result

    tasks = [sync_one(ts_code) for ts_code in ts_codes]
    for future in asyncio.as_completed(tasks):
        item = await future
        progress["done"] += 1
        progress["daily"] += int(item.get("daily", 0))
        progress["basic"] += int(item.get("basic", 0))
        if item.get("skipped"):
            progress["skipped"] += 1
        if item.get("error"):
            progress["failed"] += 1
            _log(f"[{progress['done']}/{len(ts_codes)}] {item['ts_code']} 失败: {item['error']}")
        elif item.get("skipped"):
            _log(f"[{progress['done']}/{len(ts_codes)}] {item['ts_code']} 跳过（结束日期已存在）")
        else:
            _log(
                f"[{progress['done']}/{len(ts_codes)}] {item['ts_code']} "
                f"stock_daily={item.get('daily', 0)}({item.get('daily_source', '-')}) "
                f"daily_basic={item.get('basic', 0)}({item.get('basic_source', '-')})"
            )

    index_total = 0
    index_failures = 0
    if not args.skip_index_daily:
        core_indices = ["000001.SH", "399001.SZ", "399006.SZ"]
        _log("")
        _log("开始同步核心指数...")
        for ts_code in core_indices:
            try:
                if not args.no_resume and await _has_trade_date_record("index_daily", ts_code, end_date):
                    _log(f"{ts_code} 跳过（结束日期已存在）")
                    continue
                records, index_source = await data_source_manager.get_index_daily(
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
                    count = write_result["upserted"] + write_result["modified"]
                    index_total += count
                    _log(f"{ts_code} index_daily={count} source={index_source or '-'}")
                else:
                    _log(f"{ts_code} index_daily=0")
            except Exception as exc:
                index_failures += 1
                _log(f"{ts_code} index_daily 失败: {exc}")

    _log("")
    _log(
        "完成: "
        f"stock_daily={progress['daily']}, "
        f"daily_basic={progress['basic']}, "
        f"index_daily={index_total}, "
        f"skipped={progress['skipped']}, "
        f"failed={progress['failed'] + index_failures}"
    )

    await data_source_manager.shutdown()
    await mongo_manager.shutdown()
    _log(f"Finished at: {datetime.now(UTC).astimezone().isoformat(timespec='seconds')}")
    log_fp.close()


if __name__ == "__main__":
    asyncio.run(main())
