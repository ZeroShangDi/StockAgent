#!/usr/bin/env python
"""
A 股全量同步总控脚本。

目标：
1. 优先同步体量较小的数据，最后同步股票日线。
2. 默认只走 Tushare，并依赖 TushareManager 的保守限频与重试。
3. 先检查本地是否已有且完整，完整则跳过并记录，不浪费请求次数。
4. 失败不中断整轮任务，尽量跑完全流程；无法补齐的部分落失败日志。
5. 股票日线按股票补数，并输出按股票数量计算的百分比进度。

使用示例：
    cd AgentServer
    python scripts/sync_a_share_full.py

    # 强制重新检查各环节
    python scripts/sync_a_share_full.py --force

    # 只跑到 daily_basic，跳过财务与日线
    python scripts/sync_a_share_full.py --skip-fina-indicator --skip-stock-daily
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import data_source_manager, mongo_manager
from nodes.data_sync.collectors.stock.basic import _add_financial_metrics
from nodes.data_sync.collectors.stock.daily_basic import _clean_daily_basic_record


DEFAULT_STOCK_DAILY_START = "19900101"
DEFAULT_DAILY_BASIC_START = "20180101"
DEFAULT_INDEX_DAILY_START = "20000101"
DEFAULT_LIMIT_LIST_LOOKBACK_DAYS = 30
DEFAULT_FINA_LIMIT = 8
DEFAULT_CORE_INDEX_CODES = [
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000016.SH",
    "000300.SH",
    "000905.SH",
    "000688.SH",
]
FINA_COLLECTIONS = [
    ("income_statement", "fina_income", ["ts_code", "end_date"]),
    ("balance_sheet", "fina_balance", ["ts_code", "end_date"]),
    ("cashflow_statement", "fina_cashflow", ["ts_code", "end_date"]),
    ("financial_indicators", "fina_indicator", ["ts_code", "end_date"]),
]


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Unsupported json value: {type(value)!r}")


def _normalize_compact_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) != 8:
        return ""

    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        return ""
    return digits


def _date_to_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def _format_pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00%"
    return f"{(numerator / denominator) * 100:.2f}%"


def _merge_sparse_records(*records: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if value in (None, "", [], {}):
                continue
            merged[key] = value
    return merged


def _is_permission_error(message: str) -> bool:
    lowered = str(message or "").lower()
    keywords = (
        "permission",
        "权限",
        "积分",
        "insufficient",
        "not enough points",
        "抱歉",
        "未开通",
    )
    return any(keyword in lowered for keyword in keywords)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
        return parsed
    except (TypeError, ValueError):
        return default


def _compute_trade_date_slice(
    trade_dates: Sequence[str],
    start_date: str,
    end_date: str,
) -> List[str]:
    if not trade_dates or start_date > end_date:
        return []
    left = bisect_left(trade_dates, start_date)
    right = bisect_right(trade_dates, end_date)
    return list(trade_dates[left:right])


def _group_missing_dates_from_expected(
    expected_dates: Sequence[str],
    existing_dates: set[str],
) -> List[Tuple[str, str]]:
    if not expected_dates:
        return []

    grouped: List[Tuple[str, str]] = []
    start: Optional[str] = None
    prev: Optional[str] = None

    for trade_date in expected_dates:
        if trade_date in existing_dates:
            if start and prev:
                grouped.append((start, prev))
            start = None
            prev = None
            continue

        if start is None:
            start = trade_date
        prev = trade_date

    if start and prev:
        grouped.append((start, prev))
    return grouped


class RunRecorder:
    def __init__(self, run_dir: Path, logger: logging.Logger):
        self.run_dir = run_dir
        self.logger = logger
        self.skipped_path = run_dir / "skipped.jsonl"
        self.failed_path = run_dir / "failed.jsonl"
        self.summary_path = run_dir / "summary.json"
        self.state_path = run_dir / "state.json"
        self.state: Dict[str, Any] = {
            "started_at": datetime.now(UTC).isoformat(),
            "sections": {},
            "stats": {"skipped": 0, "failed": 0},
        }

    def record_skip(self, payload: Dict[str, Any]) -> None:
        self._append_jsonl(self.skipped_path, payload)
        self.state["stats"]["skipped"] += 1

    def record_failure(self, payload: Dict[str, Any]) -> None:
        self._append_jsonl(self.failed_path, payload)
        self.state["stats"]["failed"] += 1

    def update_section(self, name: str, payload: Dict[str, Any]) -> None:
        self.state["sections"][name] = payload
        self.flush_state()

    def flush_state(self) -> None:
        self.state["updated_at"] = datetime.now(UTC).isoformat()
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    def write_summary(self, payload: Dict[str, Any]) -> None:
        self.summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    def _append_jsonl(self, path: Path, payload: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False, default=_json_default))
            fp.write("\n")


def _build_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger(f"a_share_full_sync.{log_path.stem}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


async def _get_latest_trade_date() -> str:
    latest_trade_date, source = await data_source_manager.get_latest_trade_date(
        preferred_source="tushare",
    )
    if not latest_trade_date:
        raise RuntimeError("无法从 Tushare 获取最新交易日")
    return latest_trade_date


async def _get_trade_calendar(start_date: str, end_date: str) -> List[str]:
    trade_dates, source = await data_source_manager.get_trade_calendar(
        start_date=start_date,
        end_date=end_date,
        preferred_source="tushare",
    )
    if not trade_dates:
        raise RuntimeError(f"无法获取交易日历: {start_date} -> {end_date}")
    return sorted(trade_dates)


async def _count_docs(collection: str, filter_query: Dict[str, Any]) -> int:
    return await mongo_manager.db[collection].count_documents(filter_query)


async def _load_existing_trade_dates(collection: str, ts_code: str) -> List[str]:
    rows = await mongo_manager.find_many(
        collection,
        {"ts_code": ts_code},
        projection={"trade_date": 1, "_id": 0},
        sort=[("trade_date", 1)],
    )
    return [row["trade_date"] for row in rows if row.get("trade_date")]


async def _load_stock_daily_stats() -> Dict[str, Dict[str, Any]]:
    pipeline = [
        {
            "$group": {
                "_id": "$ts_code",
                "count": {"$sum": 1},
                "min_trade_date": {"$min": "$trade_date"},
                "max_trade_date": {"$max": "$trade_date"},
            }
        }
    ]
    rows = await mongo_manager.aggregate("stock_daily", pipeline)
    return {
        row["_id"]: {
            "count": _safe_int(row.get("count")),
            "min_trade_date": row.get("min_trade_date"),
            "max_trade_date": row.get("max_trade_date"),
        }
        for row in rows
        if row.get("_id")
    }


async def _load_fina_stats() -> Dict[str, Dict[str, Any]]:
    pipeline = [
        {
            "$group": {
                "_id": "$ts_code",
                "count": {"$sum": 1},
                "latest_end_date": {"$max": "$end_date"},
            }
        }
    ]
    rows = await mongo_manager.aggregate("fina_indicator", pipeline)
    return {
        row["_id"]: {
            "count": _safe_int(row.get("count")),
            "latest_end_date": row.get("latest_end_date"),
        }
        for row in rows
        if row.get("_id")
    }


async def sync_stock_basic(
    recorder: RunRecorder,
    logger: logging.Logger,
    latest_trade_date: str,
    force: bool,
) -> Dict[str, Any]:
    today = datetime.now().strftime("%Y%m%d")
    existing_count = await mongo_manager.count("stock_basic", {})
    if not force and existing_count > 0 and await mongo_manager.is_synced("stock_basic", today):
        recorder.record_skip(
            {
                "section": "stock_basic",
                "reason": "already_synced_today",
                "sync_date": today,
                "existing_count": existing_count,
            }
        )
        result = {"status": "skipped", "existing_count": existing_count}
        recorder.update_section("stock_basic", result)
        return result

    merged_by_code: Dict[str, Dict[str, Any]] = {}
    fetch_count = 0
    for status in ["L", "D", "P"]:
        records, source = await data_source_manager.get_stock_basic(
            list_status=status,
            preferred_source="tushare",
        )
        logger.info("stock_basic[%s]: fetched %s rows from %s", status, len(records or []), source or "unknown")
        fetch_count += len(records or [])
        for record in records or []:
            ts_code = str(record.get("ts_code") or "").upper()
            if not ts_code:
                continue
            merged = _merge_sparse_records(merged_by_code.get(ts_code), record)
            merged.setdefault("list_status", status)
            merged_by_code[ts_code] = merged

    if not merged_by_code:
        raise RuntimeError("stock_basic 未获取到任何数据")

    daily_basic_map: Dict[str, Dict[str, Any]] = {}
    latest_daily_basic, source = await data_source_manager.get_daily_basic(
        trade_date=latest_trade_date,
        preferred_source="tushare",
    )
    for item in latest_daily_basic or []:
        ts_code = str(item.get("ts_code") or "").upper()
        if ts_code:
            daily_basic_map[ts_code] = item

    now = datetime.utcnow()
    documents: List[Dict[str, Any]] = []
    merged_metric_count = 0
    for ts_code, record in merged_by_code.items():
        cleaned = dict(record)
        cleaned["updated_at"] = now
        metrics = daily_basic_map.get(ts_code)
        if metrics:
            _add_financial_metrics(cleaned, metrics)
            merged_metric_count += 1
        documents.append(cleaned)

    write_result = await mongo_manager.bulk_upsert(
        collection="stock_basic",
        documents=documents,
        key_fields=["ts_code"],
        batch_size=1000,
    )
    await mongo_manager.record_sync("stock_basic", today, count=write_result["total"])
    result = {
        "status": "ok",
        "fetched": fetch_count,
        "written": write_result["total"],
        "upserted": write_result["upserted"],
        "modified": write_result["modified"],
        "merged_metrics": merged_metric_count,
    }
    recorder.update_section("stock_basic", result)
    return result


async def sync_index_basic(
    recorder: RunRecorder,
    logger: logging.Logger,
    force: bool,
) -> Dict[str, Any]:
    today = datetime.now().strftime("%Y%m%d")
    existing_count = await mongo_manager.count("index_basic", {})
    if not force and existing_count > 0 and await mongo_manager.is_synced("index_basic", today):
        recorder.record_skip(
            {
                "section": "index_basic",
                "reason": "already_synced_today",
                "sync_date": today,
                "existing_count": existing_count,
            }
        )
        result = {"status": "skipped", "existing_count": existing_count}
        recorder.update_section("index_basic", result)
        return result

    markets = ["SSE", "SZSE", "SW", "CSI"]
    documents: List[Dict[str, Any]] = []
    for market in markets:
        records, source = await data_source_manager.get_index_basic(
            market=market,
            preferred_source="tushare",
        )
        logger.info("index_basic[%s]: fetched %s rows from %s", market, len(records or []), source or "unknown")
        documents.extend(records or [])

    if not documents:
        raise RuntimeError("index_basic 未获取到任何数据")

    write_result = await mongo_manager.bulk_upsert(
        collection="index_basic",
        documents=documents,
        key_fields=["ts_code"],
        batch_size=1000,
    )
    await mongo_manager.record_sync("index_basic", today, count=write_result["total"])
    result = {
        "status": "ok",
        "written": write_result["total"],
        "upserted": write_result["upserted"],
        "modified": write_result["modified"],
    }
    recorder.update_section("index_basic", result)
    return result


async def sync_index_daily(
    recorder: RunRecorder,
    logger: logging.Logger,
    latest_trade_date: str,
    history_start: str,
    index_codes: Sequence[str],
) -> Dict[str, Any]:
    calendar = await _get_trade_calendar(history_start, latest_trade_date)
    index_meta_rows = await mongo_manager.find_many(
        "index_basic",
        {"ts_code": {"$in": list(index_codes)}},
        projection={"ts_code": 1, "base_date": 1, "list_date": 1, "_id": 0},
    )
    index_meta = {row["ts_code"]: row for row in index_meta_rows if row.get("ts_code")}

    total_ranges = 0
    total_rows = 0
    skipped = 0
    failed = 0

    for ts_code in index_codes:
        meta = index_meta.get(ts_code, {})
        start_candidates = [
            _normalize_compact_date(meta.get("base_date")),
            _normalize_compact_date(meta.get("list_date")),
            history_start,
        ]
        start_date = next((item for item in start_candidates if item), history_start)
        expected_dates = _compute_trade_date_slice(calendar, start_date, latest_trade_date)
        if not expected_dates:
            recorder.record_skip(
                {
                    "section": "index_daily",
                    "ts_code": ts_code,
                    "reason": "no_trade_dates_in_target_range",
                    "start_date": start_date,
                    "end_date": latest_trade_date,
                }
            )
            skipped += 1
            continue

        existing_dates = await _load_existing_trade_dates("index_daily", ts_code)
        existing_set = set(existing_dates)
        missing_dates = [trade_date for trade_date in expected_dates if trade_date not in existing_set]
        if not missing_dates:
            recorder.record_skip(
                {
                    "section": "index_daily",
                    "ts_code": ts_code,
                    "reason": "already_complete",
                    "start_date": start_date,
                    "end_date": latest_trade_date,
                    "existing_count": len(existing_dates),
                }
            )
            skipped += 1
            continue

        missing_ranges = _group_missing_dates_from_expected(expected_dates, existing_set)
        for range_start, range_end in missing_ranges:
            total_ranges += 1
            try:
                records, source = await data_source_manager.get_index_daily(
                    ts_code=ts_code,
                    start_date=range_start,
                    end_date=range_end,
                    preferred_source="tushare",
                )
                if not records:
                    failed += 1
                    recorder.record_failure(
                        {
                            "section": "index_daily",
                            "ts_code": ts_code,
                            "range": [range_start, range_end],
                            "reason": "empty_response",
                        }
                    )
                    continue

                write_result = await mongo_manager.bulk_upsert(
                    collection="index_daily",
                    documents=records,
                    key_fields=["ts_code", "trade_date"],
                    batch_size=1000,
                )
                written = write_result["upserted"] + write_result["modified"]
                total_rows += written
                logger.info(
                    "index_daily %s %s -> %s: %s rows from %s",
                    ts_code,
                    range_start,
                    range_end,
                    written,
                    source or "unknown",
                )
            except Exception as exc:
                failed += 1
                recorder.record_failure(
                    {
                        "section": "index_daily",
                        "ts_code": ts_code,
                        "range": [range_start, range_end],
                        "error": str(exc),
                    }
                )

    coverage = await mongo_manager.count(
        "index_daily",
        {"trade_date": latest_trade_date, "ts_code": {"$in": list(index_codes)}},
    )
    if coverage >= len(index_codes):
        await mongo_manager.record_sync("index_daily", latest_trade_date, count=coverage)

    result = {
        "status": "ok" if failed == 0 else "partial",
        "written": total_rows,
        "ranges": total_ranges,
        "skipped": skipped,
        "failed": failed,
        "latest_trade_coverage": coverage,
    }
    recorder.update_section("index_daily", result)
    return result


async def sync_limit_list(
    recorder: RunRecorder,
    logger: logging.Logger,
    latest_trade_date: str,
    start_date: str,
) -> Dict[str, Any]:
    calendar = await _get_trade_calendar(start_date, latest_trade_date)
    written = 0
    skipped = 0
    failed = 0

    for trade_date in calendar:
        existing_count = await _count_docs("limit_list", {"trade_date": trade_date})
        if existing_count > 0:
            skipped += 1
            recorder.record_skip(
                {
                    "section": "limit_list",
                    "trade_date": trade_date,
                    "reason": "already_exists",
                    "existing_count": existing_count,
                }
            )
            continue

        try:
            records, source = await data_source_manager.get_limit_list(
                trade_date=trade_date,
                preferred_source="tushare",
            )
            if not records:
                recorder.record_failure(
                    {
                        "section": "limit_list",
                        "trade_date": trade_date,
                        "reason": "empty_response",
                    }
                )
                failed += 1
                continue

            write_result = await mongo_manager.bulk_upsert(
                collection="limit_list",
                documents=records,
                key_fields=["ts_code", "trade_date"],
                batch_size=1000,
            )
            current_written = write_result["upserted"] + write_result["modified"]
            written += current_written
            logger.info("limit_list %s: %s rows from %s", trade_date, current_written, source or "unknown")
        except Exception as exc:
            if _is_permission_error(str(exc)):
                recorder.record_failure(
                    {
                        "section": "limit_list",
                        "trade_date": trade_date,
                        "error": str(exc),
                        "reason": "permission_or_points_not_enough",
                    }
                )
                result = {
                    "status": "skipped_permission",
                    "written": written,
                    "skipped": skipped,
                    "failed": failed + 1,
                }
                recorder.update_section("limit_list", result)
                return result

            recorder.record_failure(
                {
                    "section": "limit_list",
                    "trade_date": trade_date,
                    "error": str(exc),
                }
            )
            failed += 1

    latest_count = await _count_docs("limit_list", {"trade_date": latest_trade_date})
    if latest_count > 0:
        await mongo_manager.record_sync("limit_list", latest_trade_date, count=latest_count)

    result = {
        "status": "ok" if failed == 0 else "partial",
        "written": written,
        "skipped": skipped,
        "failed": failed,
        "latest_trade_coverage": latest_count,
    }
    recorder.update_section("limit_list", result)
    return result


async def sync_daily_basic(
    recorder: RunRecorder,
    logger: logging.Logger,
    latest_trade_date: str,
    start_date: str,
) -> Dict[str, Any]:
    calendar = await _get_trade_calendar(start_date, latest_trade_date)
    written = 0
    skipped = 0
    failed = 0

    for idx, trade_date in enumerate(calendar, 1):
        existing_count = await _count_docs("daily_basic", {"trade_date": trade_date})
        if existing_count > 0:
            skipped += 1
            recorder.record_skip(
                {
                    "section": "daily_basic",
                    "trade_date": trade_date,
                    "reason": "already_exists",
                    "existing_count": existing_count,
                }
            )
            continue

        try:
            records, source = await data_source_manager.get_daily_basic(
                trade_date=trade_date,
                preferred_source="tushare",
            )
            if not records:
                failed += 1
                recorder.record_failure(
                    {
                        "section": "daily_basic",
                        "trade_date": trade_date,
                        "reason": "empty_response",
                    }
                )
                continue

            cleaned_records: List[Dict[str, Any]] = []
            for record in records:
                cleaned = _clean_daily_basic_record(record)
                if cleaned.get("ts_code") and cleaned.get("trade_date"):
                    cleaned_records.append(cleaned)

            write_result = await mongo_manager.bulk_upsert(
                collection="daily_basic",
                documents=cleaned_records,
                key_fields=["ts_code", "trade_date"],
                batch_size=5000,
            )
            current_written = write_result["upserted"] + write_result["modified"]
            written += current_written
            logger.info(
                "daily_basic %s [%s/%s]: %s rows from %s",
                trade_date,
                idx,
                len(calendar),
                current_written,
                source or "unknown",
            )
        except Exception as exc:
            failed += 1
            recorder.record_failure(
                {
                    "section": "daily_basic",
                    "trade_date": trade_date,
                    "error": str(exc),
                }
            )

    latest_count = await _count_docs("daily_basic", {"trade_date": latest_trade_date})
    if latest_count > 0:
        await mongo_manager.record_sync("daily_basic", latest_trade_date, count=latest_count)

    result = {
        "status": "ok" if failed == 0 else "partial",
        "written": written,
        "skipped": skipped,
        "failed": failed,
        "latest_trade_coverage": latest_count,
    }
    recorder.update_section("daily_basic", result)
    return result


async def sync_fina_indicator(
    recorder: RunRecorder,
    logger: logging.Logger,
    force: bool,
    fina_limit: int,
) -> Dict[str, Any]:
    today = datetime.now().strftime("%Y%m%d")
    existing_count = await mongo_manager.count("fina_indicator", {})
    if not force and existing_count > 0 and await mongo_manager.is_synced(
        "fina_indicator",
        today,
        granularity="month",
    ):
        recorder.record_skip(
            {
                "section": "fina_indicator",
                "reason": "already_synced_this_month",
                "sync_month": today[:6],
                "existing_count": existing_count,
            }
        )
        result = {"status": "skipped", "existing_count": existing_count}
        recorder.update_section("fina_indicator", result)
        return result

    stocks = await mongo_manager.find_many(
        "stock_basic",
        {"list_status": {"$in": ["L", "D", "P"]}},
        projection={"ts_code": 1, "_id": 0},
    )
    ts_codes = sorted({str(row.get("ts_code") or "").upper() for row in stocks if row.get("ts_code")})
    if not ts_codes:
        raise RuntimeError("fina_indicator 依赖 stock_basic，但当前库中没有股票列表")

    existing_stats = await _load_fina_stats()
    written = 0
    skipped = 0
    failed = 0

    for idx, ts_code in enumerate(ts_codes, 1):
        stat = existing_stats.get(ts_code)
        if stat and _safe_int(stat.get("count")) >= fina_limit:
            skipped += 1
            recorder.record_skip(
                {
                    "section": "fina_indicator",
                    "ts_code": ts_code,
                    "reason": "enough_recent_rows_already_exist",
                    "existing_count": stat.get("count"),
                    "latest_end_date": stat.get("latest_end_date"),
                }
            )
            continue

        try:
            payload, source = await data_source_manager.get_financial_data(
                ts_code=ts_code,
                limit=fina_limit,
                preferred_source="tushare",
            )
            if not payload:
                skipped += 1
                recorder.record_skip(
                    {
                        "section": "fina_indicator",
                        "ts_code": ts_code,
                        "reason": "empty_response",
                    }
                )
                continue

            current_written = 0
            for data_key, collection_name, key_fields in FINA_COLLECTIONS:
                records = payload.get(data_key, []) or []
                if not records:
                    continue
                write_result = await mongo_manager.bulk_upsert(
                    collection=collection_name,
                    documents=records,
                    key_fields=key_fields,
                    batch_size=500,
                )
                current_written += write_result["upserted"] + write_result["modified"]

            written += current_written
            if idx % 100 == 0 or idx == len(ts_codes):
                logger.info(
                    "fina_indicator progress: %s (%s/%s), written=%s, skipped=%s, failed=%s",
                    _format_pct(idx, len(ts_codes)),
                    idx,
                    len(ts_codes),
                    written,
                    skipped,
                    failed,
                )
        except Exception as exc:
            failed += 1
            recorder.record_failure(
                {
                    "section": "fina_indicator",
                    "ts_code": ts_code,
                    "error": str(exc),
                }
            )

    if failed == 0:
        await mongo_manager.record_sync("fina_indicator", today, count=written)

    result = {
        "status": "ok" if failed == 0 else "partial",
        "written": written,
        "skipped": skipped,
        "failed": failed,
        "stock_count": len(ts_codes),
    }
    recorder.update_section("fina_indicator", result)
    return result


def _resolve_stock_target_start(stock: Dict[str, Any], default_start: str) -> str:
    list_date = _normalize_compact_date(stock.get("list_date"))
    return list_date or default_start


def _resolve_stock_target_end(stock: Dict[str, Any], latest_trade_date: str) -> str:
    delist_date = _normalize_compact_date(stock.get("delist_date"))
    if delist_date:
        return min(delist_date, latest_trade_date)
    return latest_trade_date


async def sync_stock_daily(
    recorder: RunRecorder,
    logger: logging.Logger,
    latest_trade_date: str,
    history_start: str,
    max_gap_segments: int,
) -> Dict[str, Any]:
    all_stocks = await mongo_manager.find_many(
        "stock_basic",
        {"list_status": {"$in": ["L", "D", "P"]}},
        projection={"ts_code": 1, "name": 1, "list_date": 1, "delist_date": 1, "list_status": 1, "_id": 0},
    )
    if not all_stocks:
        raise RuntimeError("stock_daily 依赖 stock_basic，但当前库中没有股票列表")

    stocks = sorted(
        all_stocks,
        key=lambda item: _resolve_stock_target_start(item, history_start),
        reverse=True,
    )
    stock_stats = await _load_stock_daily_stats()
    calendar = await _get_trade_calendar(history_start, latest_trade_date)

    processed = 0
    synced_stocks = 0
    skipped_stocks = 0
    failed_stocks = 0
    written_rows = 0
    requested_ranges = 0

    for stock in stocks:
        processed += 1
        ts_code = str(stock.get("ts_code") or "").upper()
        if not ts_code:
            failed_stocks += 1
            recorder.record_failure({"section": "stock_daily", "error": "missing_ts_code", "stock": stock})
            continue

        target_start = _resolve_stock_target_start(stock, history_start)
        target_end = _resolve_stock_target_end(stock, latest_trade_date)
        if not target_start or target_start > target_end:
            skipped_stocks += 1
            recorder.record_skip(
                {
                    "section": "stock_daily",
                    "ts_code": ts_code,
                    "reason": "invalid_target_range",
                    "start_date": target_start,
                    "end_date": target_end,
                }
            )
            continue

        expected_dates = _compute_trade_date_slice(calendar, target_start, target_end)
        if not expected_dates:
            skipped_stocks += 1
            recorder.record_skip(
                {
                    "section": "stock_daily",
                    "ts_code": ts_code,
                    "reason": "no_trade_dates_in_target_range",
                    "start_date": target_start,
                    "end_date": target_end,
                }
            )
            continue

        stat = stock_stats.get(ts_code)
        if stat:
            if (
                stat.get("min_trade_date")
                and stat.get("max_trade_date")
                and stat["min_trade_date"] <= target_start
                and stat["max_trade_date"] >= target_end
                and _safe_int(stat.get("count")) >= len(expected_dates)
            ):
                skipped_stocks += 1
                recorder.record_skip(
                    {
                        "section": "stock_daily",
                        "ts_code": ts_code,
                        "reason": "already_complete",
                        "start_date": target_start,
                        "end_date": target_end,
                        "existing_count": stat.get("count"),
                    }
                )
                if processed % 20 == 0 or processed == len(stocks):
                    logger.info(
                        "stock_daily progress: %s (%s/%s), synced=%s, skipped=%s, failed=%s",
                        _format_pct(processed, len(stocks)),
                        processed,
                        len(stocks),
                        synced_stocks,
                        skipped_stocks,
                        failed_stocks,
                    )
                continue

        existing_dates = await _load_existing_trade_dates("stock_daily", ts_code)
        existing_set = set(existing_dates)
        missing_dates = [trade_date for trade_date in expected_dates if trade_date not in existing_set]
        if not missing_dates:
            skipped_stocks += 1
            recorder.record_skip(
                {
                    "section": "stock_daily",
                    "ts_code": ts_code,
                    "reason": "already_complete_after_exact_check",
                    "start_date": target_start,
                    "end_date": target_end,
                    "existing_count": len(existing_dates),
                }
            )
            if processed % 20 == 0 or processed == len(stocks):
                logger.info(
                    "stock_daily progress: %s (%s/%s), synced=%s, skipped=%s, failed=%s",
                    _format_pct(processed, len(stocks)),
                    processed,
                    len(stocks),
                    synced_stocks,
                    skipped_stocks,
                    failed_stocks,
                )
            continue

        missing_ranges = _group_missing_dates_from_expected(expected_dates, existing_set)
        request_ranges = (
            [(target_start, target_end)]
            if len(missing_ranges) > max_gap_segments
            else missing_ranges
        )

        stock_written = 0
        stock_errors = 0
        for range_start, range_end in request_ranges:
            requested_ranges += 1
            try:
                records, source = await data_source_manager.get_daily(
                    ts_code=ts_code,
                    start_date=range_start,
                    end_date=range_end,
                    preferred_source="tushare",
                )
                if not records:
                    stock_errors += 1
                    recorder.record_failure(
                        {
                            "section": "stock_daily",
                            "ts_code": ts_code,
                            "range": [range_start, range_end],
                            "reason": "empty_response",
                        }
                    )
                    continue

                write_result = await mongo_manager.bulk_upsert(
                    collection="stock_daily",
                    documents=records,
                    key_fields=["ts_code", "trade_date"],
                    batch_size=1000,
                )
                current_written = write_result["upserted"] + write_result["modified"]
                stock_written += current_written
                written_rows += current_written
                logger.info(
                    "stock_daily %s %s -> %s: %s rows from %s",
                    ts_code,
                    range_start,
                    range_end,
                    current_written,
                    source or "unknown",
                )
            except Exception as exc:
                stock_errors += 1
                recorder.record_failure(
                    {
                        "section": "stock_daily",
                        "ts_code": ts_code,
                        "range": [range_start, range_end],
                        "error": str(exc),
                    }
                )

        refreshed_dates = await _load_existing_trade_dates("stock_daily", ts_code)
        refreshed_set = set(refreshed_dates)
        remaining_missing = [trade_date for trade_date in expected_dates if trade_date not in refreshed_set]
        if remaining_missing:
            failed_stocks += 1
            recorder.record_failure(
                {
                    "section": "stock_daily",
                    "ts_code": ts_code,
                    "reason": "remaining_gaps_after_sync",
                    "missing_count": len(remaining_missing),
                    "first_missing": remaining_missing[:10],
                    "target_start": target_start,
                    "target_end": target_end,
                }
            )
        else:
            synced_stocks += 1
            if stock_written == 0:
                recorder.record_skip(
                    {
                        "section": "stock_daily",
                        "ts_code": ts_code,
                        "reason": "ranges_refreshed_but_no_net_new_rows",
                        "target_start": target_start,
                        "target_end": target_end,
                    }
                )

        if processed % 10 == 0 or processed == len(stocks):
            logger.info(
                "stock_daily progress: %s (%s/%s), synced=%s, skipped=%s, failed=%s, written_rows=%s",
                _format_pct(processed, len(stocks)),
                processed,
                len(stocks),
                synced_stocks,
                skipped_stocks,
                failed_stocks,
                written_rows,
            )

    latest_active_codes = [
        str(stock.get("ts_code") or "").upper()
        for stock in stocks
        if _resolve_stock_target_end(stock, latest_trade_date) >= latest_trade_date
    ]
    latest_coverage = 0
    if latest_active_codes:
        latest_coverage = len(
            await mongo_manager.db["stock_daily"].distinct(
                "ts_code",
                {"trade_date": latest_trade_date, "ts_code": {"$in": latest_active_codes}},
            )
        )
        if latest_coverage >= max(len(latest_active_codes) - failed_stocks, 1):
            await mongo_manager.record_sync("stock_daily", latest_trade_date, count=latest_coverage)

    result = {
        "status": "ok" if failed_stocks == 0 else "partial",
        "stock_count": len(stocks),
        "processed": processed,
        "synced_stocks": synced_stocks,
        "skipped_stocks": skipped_stocks,
        "failed_stocks": failed_stocks,
        "written_rows": written_rows,
        "requested_ranges": requested_ranges,
        "latest_trade_coverage": latest_coverage,
    }
    recorder.update_section("stock_daily", result)
    return result


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    project_root = Path(__file__).resolve().parents[1]
    logs_root = project_root / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    run_dir = logs_root / f"a_share_full_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = _build_logger(run_dir / "run.log")
    recorder = RunRecorder(run_dir=run_dir, logger=logger)

    logger.info("Run directory: %s", run_dir)
    logger.info("Arguments: %s", vars(args))

    await mongo_manager.initialize()
    await data_source_manager.initialize()

    try:
        latest_trade_date = await _get_latest_trade_date()
        logger.info("Latest trade date resolved from Tushare: %s", latest_trade_date)

        results: Dict[str, Any] = {
            "run_dir": str(run_dir),
            "latest_trade_date": latest_trade_date,
            "started_at": datetime.now(UTC).isoformat(),
            "sections": {},
        }

        results["sections"]["stock_basic"] = await sync_stock_basic(
            recorder=recorder,
            logger=logger,
            latest_trade_date=latest_trade_date,
            force=args.force,
        )
        results["sections"]["index_basic"] = await sync_index_basic(
            recorder=recorder,
            logger=logger,
            force=args.force,
        )
        results["sections"]["index_daily"] = await sync_index_daily(
            recorder=recorder,
            logger=logger,
            latest_trade_date=latest_trade_date,
            history_start=args.index_daily_start,
            index_codes=args.index_codes,
        )

        if args.skip_limit_list:
            skip_result = {"status": "manually_skipped"}
            recorder.update_section("limit_list", skip_result)
            results["sections"]["limit_list"] = skip_result
        else:
            limit_list_start = args.limit_list_start
            if not limit_list_start:
                auto_start = _date_to_dt(latest_trade_date)
                auto_start = auto_start.replace(hour=0, minute=0, second=0, microsecond=0)
                limit_list_start = (
                    auto_start - timedelta(days=DEFAULT_LIMIT_LIST_LOOKBACK_DAYS)
                ).strftime("%Y%m%d")
            results["sections"]["limit_list"] = await sync_limit_list(
                recorder=recorder,
                logger=logger,
                latest_trade_date=latest_trade_date,
                start_date=limit_list_start,
            )

        results["sections"]["daily_basic"] = await sync_daily_basic(
            recorder=recorder,
            logger=logger,
            latest_trade_date=latest_trade_date,
            start_date=args.daily_basic_start,
        )

        if args.skip_fina_indicator:
            skip_result = {"status": "manually_skipped"}
            recorder.update_section("fina_indicator", skip_result)
            results["sections"]["fina_indicator"] = skip_result
        else:
            results["sections"]["fina_indicator"] = await sync_fina_indicator(
                recorder=recorder,
                logger=logger,
                force=args.force,
                fina_limit=args.fina_limit,
            )

        if args.skip_stock_daily:
            skip_result = {"status": "manually_skipped"}
            recorder.update_section("stock_daily", skip_result)
            results["sections"]["stock_daily"] = skip_result
        else:
            results["sections"]["stock_daily"] = await sync_stock_daily(
                recorder=recorder,
                logger=logger,
                latest_trade_date=latest_trade_date,
                history_start=args.stock_daily_start,
                max_gap_segments=args.stock_daily_max_gap_segments,
            )

        results["finished_at"] = datetime.now(UTC).isoformat()
        results["stats"] = recorder.state.get("stats", {})
        recorder.write_summary(results)
        recorder.flush_state()
        logger.info("Full sync finished. Summary written to %s", recorder.summary_path)
        return results
    finally:
        await data_source_manager.shutdown()
        await mongo_manager.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="全量同步 A 股核心数据（优先小表，最后补股票日线）")
    parser.add_argument("--force", action="store_true", help="忽略按日/月同步标记，重新检查并执行")
    parser.add_argument(
        "--index-daily-start",
        type=str,
        default=DEFAULT_INDEX_DAILY_START,
        help=f"指数日线默认起点，默认 {DEFAULT_INDEX_DAILY_START}",
    )
    parser.add_argument(
        "--daily-basic-start",
        type=str,
        default=DEFAULT_DAILY_BASIC_START,
        help=f"daily_basic 默认起点，默认 {DEFAULT_DAILY_BASIC_START}",
    )
    parser.add_argument(
        "--stock-daily-start",
        type=str,
        default=DEFAULT_STOCK_DAILY_START,
        help=f"stock_daily 缺少上市日期时的默认起点，默认 {DEFAULT_STOCK_DAILY_START}",
    )
    parser.add_argument(
        "--limit-list-start",
        type=str,
        default="",
        help="limit_list 起点；不传则默认只补最近 30 天",
    )
    parser.add_argument(
        "--fina-limit",
        type=int,
        default=DEFAULT_FINA_LIMIT,
        help=f"每只股票同步最近多少期财务数据，默认 {DEFAULT_FINA_LIMIT}",
    )
    parser.add_argument(
        "--skip-limit-list",
        action="store_true",
        help="跳过 limit_list，同步权限不足时也建议开启",
    )
    parser.add_argument("--skip-fina-indicator", action="store_true", help="跳过财务数据同步")
    parser.add_argument("--skip-stock-daily", action="store_true", help="跳过股票日线同步")
    parser.add_argument(
        "--stock-daily-max-gap-segments",
        type=int,
        default=20,
        help="单只股票允许按缺口分段补数的最大分段数，超过则整段重拉",
    )
    parser.add_argument(
        "--index-codes",
        nargs="*",
        default=DEFAULT_CORE_INDEX_CODES,
        help="需要同步的核心指数代码列表",
    )
    return parser


if __name__ == "__main__":
    cli_args = build_parser().parse_args()
    asyncio.run(run(cli_args))
