"""
日线数据采集器

支持增量同步和失败重试：
- 首次同步：从 2003-01-27 开始同步所有历史数据
- 增量同步：从上次同步日期同步到今天
- 已同步：如果今天已同步则跳过

注意：Tushare API 每次调用最多返回 6000 条数据，
历史数据（20多年）可能接近此限制，因此首次同步需要逐只股票获取。
"""

from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta

from core.base import BaseCollector
from core.settings import settings
from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from nodes.data_sync.services.recovery_contract import (
    build_recovery_warnings,
    extract_sources_from_parallel_result,
    primary_source,
    skipped_recovery_result,
    validate_recovery_trade_date,
)
from .focus_universe import get_focus_stock_codes


class StockDailyCollector(BaseCollector):
    """
    日线数据采集器

    采集所有股票的日线行情数据。支持失败自动重试。

    Tushare API 限制:
    - 每次调用最多返回 6000 条数据
    - 历史数据跨度大时，需要单只股票逐个获取
    - 增量同步（少量天数）可以批量获取

    调度时间:
    - 可通过 SYNC_STOCK_DAILY_SCHEDULE 环境变量配置
    - 默认: 每个交易日 15:30 (收盘后)
    """

    name = "stock_daily"
    description = "采集股票日线数据"
    default_schedule = "30 15 * * 1-5"
    dataset_name = "stock_daily"
    resource_class = "core"
    target_collections = ("stock_daily",)
    dependencies = ("stock_basic", "trade_calendar")
    source_chain_keys = ("get_latest_trade_date", "get_daily.full_market", "get_daily.single")
    supports_backfill = True
    quality_checks = ("required_fields:ts_code,trade_date,open,high,low,close", "dedupe_key:ts_code,trade_date")

    # 配置（覆盖基类默认值）
    HISTORY_START_DATE = "20030127"
    HISTORY_SYNC_DAYS_THRESHOLD = 30
    WRITE_BATCH_SIZE = 1000

    # 批次大小 - 根据同步类型动态调整
    FETCH_BATCH_SIZE_HISTORY = 1       # 历史同步：每批 1 只股票（数据量大）
    FETCH_BATCH_SIZE_INCREMENTAL = 500 # 增量同步：每批 500 只股票

    @property
    def schedule(self) -> str:
        return settings.data_sync.stock_daily_schedule or self.default_schedule

    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        focus_mode = await self._should_use_focus_mode()
        sync_marker = self._get_sync_marker(focus_mode)
        already_synced = await mongo_manager.is_synced(sync_marker, latest_trade_date)
        coverage_ok = await self._has_trade_date_coverage(latest_trade_date, focus_mode)

        if already_synced and coverage_ok:
            self.logger.info(f"Stock daily {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}

        if already_synced and not coverage_ok:
            self.logger.warning(
                f"Sync marker {sync_marker} already points to {latest_trade_date}, "
                "but stock_daily coverage is incomplete; forcing latest-date resync"
            )
            sync_info = (latest_trade_date, latest_trade_date, False)
        else:
            sync_info = await self._determine_sync_range_for(sync_marker, latest_trade_date)

        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}

        start_date, end_date, is_history_sync = sync_info

        sync_type_desc = "重点股同步" if focus_mode else ("历史同步" if is_history_sync else "增量同步")

        if focus_mode:
            focus_codes = await get_focus_stock_codes()
            if not focus_codes:
                return {"count": 0, "message": "Focus stock sync enabled, but no watchlist/subscription stocks found"}

            self.logger.info(
                f"[{sync_type_desc}] Syncing stock daily: {start_date} -> {end_date} "
                f"({len(focus_codes)} focus stocks)"
            )
            total_count, result = await self._collect_focus_stocks(
                ts_codes=focus_codes,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            # 获取所有股票代码
            stocks = await mongo_manager.find_many(
                "stock_basic",
                {"list_status": "L"},
                projection={"ts_code": 1},
            )

            if not stocks:
                return {"count": 0, "message": "No stocks found"}

            ts_codes = [s["ts_code"] for s in stocks]
            fetch_batch_size = (
                self.FETCH_BATCH_SIZE_HISTORY
                if is_history_sync
                else self.FETCH_BATCH_SIZE_INCREMENTAL
            )

            self.logger.info(
                f"[{sync_type_desc}] Syncing stock daily: {start_date} -> {end_date} "
                f"({len(ts_codes)} stocks, batch_size={fetch_batch_size})"
            )

            if not is_history_sync:
                trade_dates = await self._get_trade_dates(start_date, end_date)
                if not trade_dates:
                    return {"count": 0, "message": f"No trade dates in {start_date} -> {end_date}"}

                total_count, result = await self._collect_incremental_by_trade_date(trade_dates)
            else:
                total_count, result = await self._collect_history_by_stock(
                    ts_codes=ts_codes,
                    start_date=start_date,
                    end_date=end_date,
                    fetch_batch_size=fetch_batch_size,
                )

        if await self._has_trade_date_coverage(end_date, focus_mode):
            await mongo_manager.record_sync(
                sync_type=sync_marker,
                sync_date=end_date,
                count=total_count,
            )
        else:
            self.logger.warning(
                f"Skip recording sync marker for {sync_marker}: stock_daily still lacks {end_date} coverage"
            )

        return {
            "count": total_count,
            "start_date": start_date,
            "end_date": end_date,
            "sync_type": sync_type_desc,
            "success_batches": result["success"],
            "failed_batches": result["failed"],
            "message": f"[{sync_type_desc}] Synced {total_count} records ({result['success']}/{result['total']} items)",
        }

    async def recover_trade_date(self, trade_date: str) -> Dict[str, Any]:
        """定向补指定交易日的日线数据，不回退 sync marker。"""
        guard = await validate_recovery_trade_date(trade_date)
        if not guard["ok"]:
            return skipped_recovery_result(self.name, guard)

        trade_date = guard["trade_date"]
        focus_mode = await self._should_use_focus_mode()
        if focus_mode:
            focus_codes = await get_focus_stock_codes()
            if not focus_codes:
                return {
                    "success": True,
                    "count": 0,
                    "trade_date": trade_date,
                    "skipped": True,
                    "reason": "no_focus_stocks",
                    "source": guard.get("source"),
                    "sources": [guard.get("source")] if guard.get("source") else [],
                    "warnings": build_recovery_warnings(guard),
                    "message": "No focus stocks to recover",
                }
            total_count, result = await self._collect_focus_stocks(
                ts_codes=focus_codes,
                start_date=trade_date,
                end_date=trade_date,
            )
        else:
            total_count, result = await self._collect_incremental_by_trade_date([trade_date])

        sources = extract_sources_from_parallel_result(result, default=guard.get("source") or "unknown")
        return {
            "success": result.get("failed", 0) == 0,
            "count": total_count,
            "trade_date": trade_date,
            "source": primary_source(sources),
            "sources": sources,
            "warnings": build_recovery_warnings(
                guard,
                failed_count=result.get("failed", 0),
                failed_items=result.get("failed_items", []),
            ),
            "success_batches": result.get("success", 0),
            "failed_batches": result.get("failed", 0),
            "failed_items": result.get("failed_items", []),
            "message": f"Recovered stock_daily for {trade_date}",
        }

    async def _should_use_focus_mode(self) -> bool:
        """是否启用重点股票同步模式。"""
        if settings.data_sync.focus_stocks_only:
            return True

        has_tushare = data_source_manager.get_adapter("tushare") is not None
        has_coze = data_source_manager.get_adapter("coze") is not None
        return has_coze and not has_tushare

    def _get_sync_marker(self, focus_mode: bool) -> str:
        return f"{self.name}_focus" if focus_mode else self.name

    async def _has_trade_date_coverage(self, trade_date: str, focus_mode: bool) -> bool:
        """检查目标交易日是否已真正写入本地库。"""
        if focus_mode:
            focus_codes = await get_focus_stock_codes()
            if not focus_codes:
                return False
            rows = await mongo_manager.find_many(
                "stock_daily",
                {"trade_date": trade_date, "ts_code": {"$in": focus_codes}},
                projection={"ts_code": 1},
            )
            covered = {row.get("ts_code") for row in rows if row.get("ts_code")}
            return all(code in covered for code in focus_codes)

        rows = await mongo_manager.find_many(
            "stock_daily",
            {"trade_date": trade_date},
            projection={"ts_code": 1},
            limit=1,
        )
        return bool(rows)

    async def _determine_sync_range_for(
        self,
        sync_type: str,
        latest_trade_date: str,
    ) -> Tuple[str, str, bool] | None:
        last_sync_date = await mongo_manager.get_last_sync_date(sync_type)

        if last_sync_date is None:
            self.logger.info(f"First sync ({sync_type}), starting from {self.HISTORY_START_DATE}")
            return (self.HISTORY_START_DATE, latest_trade_date, True)

        if last_sync_date >= latest_trade_date:
            return None

        last_sync_dt = datetime.strptime(last_sync_date, "%Y%m%d")
        latest_dt = datetime.strptime(latest_trade_date, "%Y%m%d")
        days_diff = (latest_dt - last_sync_dt).days

        is_history_sync = days_diff > self.HISTORY_SYNC_DAYS_THRESHOLD
        next_day = (last_sync_dt + timedelta(days=1)).strftime("%Y%m%d")

        sync_type_desc = "历史" if is_history_sync else "增量"
        self.logger.info(
            f"{sync_type_desc}同步({sync_type}): last_sync={last_sync_date}, "
            f"syncing {next_day} -> {latest_trade_date} ({days_diff} days)"
        )
        return (next_day, latest_trade_date, is_history_sync)

    async def _collect_incremental_by_trade_date(
        self,
        trade_dates: List[str],
    ) -> Tuple[int, Dict[str, Any]]:
        """
        增量同步：按交易日整市场抓取。

        这样可以把一次增量同步压缩成“每个交易日 1 次请求”，
        避免原先按股票分批导致的 Tushare `daily` 频率超限。
        """
        total_count = 0
        results: List[Dict[str, Any]] = []
        failed_items: List[Dict[str, Any]] = []
        checkpoint_window = "incremental_by_trade_date"
        checkpoint_target = trade_dates[-1]
        checkpoint = await self._get_checkpoint(checkpoint_target, checkpoint_window)
        last_success_key = str((checkpoint or {}).get("last_success_key") or "")
        skipped_by_checkpoint = 0

        if last_success_key:
            original_total = len(trade_dates)
            trade_dates = [trade_date for trade_date in trade_dates if trade_date > last_success_key]
            skipped_by_checkpoint = original_total - len(trade_dates)
            if skipped_by_checkpoint:
                self.logger.info(
                    "Resume stock_daily incremental from checkpoint %s: skipped=%s, remaining=%s",
                    last_success_key,
                    skipped_by_checkpoint,
                    len(trade_dates),
                )
        if not trade_dates:
            await self._mark_checkpoint_done(
                checkpoint_target,
                checkpoint_window,
                details={
                    "last_success_key": last_success_key,
                    "skipped_by_checkpoint": skipped_by_checkpoint,
                },
            )
            return 0, {
                "total": skipped_by_checkpoint,
                "success": skipped_by_checkpoint,
                "failed": 0,
                "results": [],
                "failed_items": [],
                "skipped_by_checkpoint": skipped_by_checkpoint,
                "checkpoint_window": checkpoint_window,
            }

        for idx, trade_date in enumerate(trade_dates, 1):
            try:
                records, source = await data_source_manager.get_daily(
                    trade_date=trade_date,
                )
                if not records:
                    self.logger.warning(f"[{idx}/{len(trade_dates)}] {trade_date}: no daily records")
                    failed_items.append({"item_id": trade_date, "success": False, "error": "no_data"})
                    continue

                count = await self._write_buffer(
                    buffer=records,
                    collection="stock_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                source_name = source or "unknown"
                self.logger.info(
                    f"[{idx}/{len(trade_dates)}] {trade_date}: {len(records)} rows from {source_name}, synced={count}"
                )
                results.append({"item_id": trade_date, "success": True, "source": source_name, "count": count})
                await self._update_checkpoint(
                    checkpoint_target,
                    checkpoint_window,
                    cursor=trade_date,
                    last_success_key=trade_date,
                    details={
                        "processed": idx,
                        "remaining_total": len(trade_dates),
                        "skipped_by_checkpoint": skipped_by_checkpoint,
                    },
                )
            except Exception as e:
                self.logger.warning(f"[{idx}/{len(trade_dates)}] {trade_date}: {e}")
                failed_items.append({"item_id": trade_date, "success": False, "error": str(e)})

        if not failed_items:
            await self._mark_checkpoint_done(
                checkpoint_target,
                checkpoint_window,
                details={
                    "processed": len(trade_dates),
                    "skipped_by_checkpoint": skipped_by_checkpoint,
                    "last_success_key": trade_dates[-1],
                },
            )

        return total_count, {
            "total": len(trade_dates) + skipped_by_checkpoint,
            "success": len(results) + skipped_by_checkpoint,
            "failed": len(failed_items),
            "results": results,
            "failed_items": failed_items,
            "skipped_by_checkpoint": skipped_by_checkpoint,
            "checkpoint_window": checkpoint_window,
        }

    async def _collect_history_by_stock(
        self,
        ts_codes: List[str],
        start_date: str,
        end_date: str,
        fetch_batch_size: int,
    ) -> Tuple[int, Dict[str, Any]]:
        """历史同步：按股票抓取，保留单股 Coze 优先的能力。"""
        ts_codes = sorted(ts_codes)
        batches = [
            ts_codes[i:i + fetch_batch_size]
            for i in range(0, len(ts_codes), fetch_batch_size)
        ]
        checkpoint_window = f"history_by_stock:{start_date}:{end_date}"
        checkpoint = await self._get_checkpoint(end_date, checkpoint_window)
        last_success_key = str((checkpoint or {}).get("last_success_key") or "")
        skipped_by_checkpoint = 0

        if last_success_key:
            original_total = len(batches)
            batches = [batch for batch in batches if batch[-1] > last_success_key]
            skipped_by_checkpoint = original_total - len(batches)
            if skipped_by_checkpoint:
                self.logger.info(
                    "Resume stock_daily history from checkpoint %s: skipped_batches=%s, remaining_batches=%s",
                    last_success_key,
                    skipped_by_checkpoint,
                    len(batches),
                )
        if not batches:
            await self._mark_checkpoint_done(
                end_date,
                checkpoint_window,
                details={
                    "last_success_key": last_success_key,
                    "skipped_by_checkpoint": skipped_by_checkpoint,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            return 0, {
                "total": skipped_by_checkpoint,
                "success": skipped_by_checkpoint,
                "failed": 0,
                "results": [],
                "failed_items": [],
                "skipped_by_checkpoint": skipped_by_checkpoint,
                "checkpoint_window": checkpoint_window,
            }

        total_count = 0
        processed_batches = 0

        async def collect_batch(batch: List[str]) -> int:
            nonlocal total_count, processed_batches
            ts_code_str = ",".join(batch)
            records, source = await data_source_manager.get_daily(
                ts_code=ts_code_str,
                start_date=start_date,
                end_date=end_date,
            )
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="stock_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                self.logger.info(
                    f"History batch {batch[0]}..: {len(records)} rows from {source or 'unknown'}, synced={count}"
                )
                processed_batches += 1
                await self._update_checkpoint(
                    end_date,
                    checkpoint_window,
                    cursor=batch[-1],
                    last_success_key=batch[-1],
                    details={
                        "processed_batches": processed_batches,
                        "remaining_total": len(batches),
                        "skipped_by_checkpoint": skipped_by_checkpoint,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )
                return count
            processed_batches += 1
            await self._update_checkpoint(
                end_date,
                checkpoint_window,
                cursor=batch[-1],
                last_success_key=batch[-1],
                details={
                    "processed_batches": processed_batches,
                    "remaining_total": len(batches),
                    "skipped_by_checkpoint": skipped_by_checkpoint,
                    "start_date": start_date,
                    "end_date": end_date,
                    "empty_batch": True,
                },
            )
            return 0

        result = await self._parallel_collect(
            items=batches,
            collect_func=collect_batch,
            max_concurrent=1,
            retry_failures=False,
            item_id_func=lambda b: f"batch_{b[0]}",
        )
        if not result.get("failed"):
            await self._mark_checkpoint_done(
                end_date,
                checkpoint_window,
                details={
                    "processed_batches": processed_batches,
                    "skipped_by_checkpoint": skipped_by_checkpoint,
                    "start_date": start_date,
                    "end_date": end_date,
                    "last_success_key": batches[-1][-1],
                },
            )
        result["total"] = result.get("total", 0) + skipped_by_checkpoint
        result["success"] = result.get("success", 0) + skipped_by_checkpoint
        result["skipped_by_checkpoint"] = skipped_by_checkpoint
        result["checkpoint_window"] = checkpoint_window
        return total_count, result

    async def _collect_focus_stocks(
        self,
        ts_codes: List[str],
        start_date: str,
        end_date: str,
    ) -> Tuple[int, Dict[str, Any]]:
        """重点股票同步：逐股抓取并落库，优先适配 Coze 单股能力。"""
        total_count = 0

        async def collect_single_stock(ts_code: str) -> int:
            nonlocal total_count
            records, source = await data_source_manager.get_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="stock_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                self.logger.info(
                    f"Focus stock {ts_code}: {len(records)} rows from {source or 'unknown'}, synced={count}"
                )
                return count
            return 0

        result = await self._parallel_collect(
            items=ts_codes,
            collect_func=collect_single_stock,
            max_concurrent=3,
            retry_failures=True,
        )
        return total_count, result
