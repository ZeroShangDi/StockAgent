"""
采集器基类

用于从外部数据源采集数据的任务。
提供通用的同步范围计算、交易日历获取、批量写入、失败重试等功能。
"""

import asyncio
import logging
import math
import time
from abc import abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Callable, TypeVar

from common.logger import log_event
from .scheduled_job import ScheduledJob

T = TypeVar("T")


class BaseCollector(ScheduledJob):
    """
    采集器基类

    用于从外部数据源采集数据。

    提供的通用功能:
    - _get_trade_dates: 获取日期范围内的交易日列表
    - _determine_sync_range: 确定同步日期范围（支持历史/增量同步）
    - _write_buffer: 批量写入数据到 MongoDB
    - _parallel_collect: 并行采集多个项目（带失败重试）
    - _record_failure / _get_pending_failures / _clear_failures: 失败记录管理

    Example:
        class StockBasicCollector(BaseCollector):
            name = "stock_basic"
            description = "采集股票基础信息"
            default_schedule = "0 9 * * 1-5"

            async def collect(self) -> dict:
                data = await data_source_manager.get_stock_basic()
                await mongo_manager.bulk_upsert("stock_basic", data)
                return {"count": len(data)}
    """

    _log_prefix = "collector"

    # 子类可覆盖的默认配置
    HISTORY_START_DATE: str = "20180101"
    HISTORY_SYNC_DAYS_THRESHOLD: int = 30
    INITIAL_SYNC_DAYS: int = 30
    WRITE_BATCH_SIZE: int = 1000
    MAX_RETRY_COUNT: int = 3
    BAD_RECORD_SAMPLE_LIMIT: int = 5
    DEAD_LETTER_BUFFER_LIMIT: int = 20
    CORE_RECORD_SCHEMAS: Dict[str, Dict[str, Any]] = {
        "stock_daily": {
            "required": ["ts_code", "trade_date", "open", "high", "low", "close"],
            "date_fields": ["trade_date"],
            "float_fields": ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
        },
        "index_daily": {
            "required": ["ts_code", "trade_date", "open", "high", "low", "close"],
            "date_fields": ["trade_date"],
            "float_fields": ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
        },
        "daily_basic": {
            "required": ["ts_code", "trade_date"],
            "date_fields": ["trade_date"],
            "float_fields": [
                "close", "turnover_rate", "turnover_rate_f", "volume_ratio",
                "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
                "total_share", "float_share", "free_share", "total_mv", "circ_mv",
            ],
        },
        "limit_list": {
            "required": ["ts_code", "trade_date", "limit"],
            "date_fields": ["trade_date"],
            "float_fields": [
                "close", "pct_chg", "amount", "limit_amount", "float_mv",
                "total_mv", "turnover_ratio", "fd_amount",
            ],
            "int_fields": ["open_times", "limit_times"],
        },
        "moneyflow_industry": {
            "required": ["ts_code", "trade_date", "name"],
            "date_fields": ["trade_date"],
            "float_fields": [
                "pct_change", "close", "net_amount", "net_amount_rate",
                "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount",
            ],
        },
        "moneyflow_concept": {
            "required": ["ts_code", "trade_date", "name"],
            "date_fields": ["trade_date"],
            "float_fields": [
                "pct_change", "close", "net_amount", "net_amount_rate",
                "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount",
            ],
        },
    }

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._write_results: List[Dict[str, Any]] = []

    @abstractmethod
    async def collect(self) -> Dict[str, Any]:
        """
        执行采集

        Returns:
            采集结果，至少包含 count 字段
        """
        raise NotImplementedError

    async def _do_work(self) -> Dict[str, Any]:
        """内部调用 collect()"""
        self._write_results = []
        result = await self.collect()
        if isinstance(result, dict) and self._write_results:
            result.setdefault("write_results", self._write_results)
        return result

    # ==================== 通用方法 ====================

    async def _get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """
        获取日期范围内的交易日列表

        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            交易日列表，按日期升序排列
        """
        # 直接从子模块导入单例，避免 package 同名属性被子模块对象覆盖。
        from core.managers.data_source_manager import data_source_manager

        try:
            trade_dates, _ = await data_source_manager.get_trade_calendar(
                start_date=start_date,
                end_date=end_date,
            )
            return sorted(trade_dates) if trade_dates else []
        except Exception as e:
            self.logger.warning(f"Failed to get trade calendar: {e}, falling back to weekdays")
            # 降级：生成工作日列表（排除周末）
            dates = []
            current = datetime.strptime(start_date, "%Y%m%d")
            end = datetime.strptime(end_date, "%Y%m%d")
            while current <= end:
                if current.weekday() < 5:
                    dates.append(current.strftime("%Y%m%d"))
                current += timedelta(days=1)
            return dates

    async def _determine_sync_range(
        self,
        latest_trade_date: str,
        history_start_date: Optional[str] = None,
        history_threshold_days: Optional[int] = None,
    ) -> Optional[Tuple[str, str, bool]]:
        """
        确定同步日期范围和同步类型

        Args:
            latest_trade_date: 最新交易日
            history_start_date: 历史数据起始日期，默认使用 self.HISTORY_START_DATE
            history_threshold_days: 历史同步阈值天数，默认使用 self.HISTORY_SYNC_DAYS_THRESHOLD

        Returns:
            (start_date, end_date, is_history_sync) 元组
            is_history_sync: True 表示历史同步（数据量大）
            如果不需要同步返回 None
        """
        from core.managers.mongo_manager import mongo_manager

        history_start = history_start_date or self.HISTORY_START_DATE
        threshold = history_threshold_days or self.HISTORY_SYNC_DAYS_THRESHOLD

        last_sync_date = await mongo_manager.get_last_sync_date(self.name)

        if last_sync_date is None:
            try:
                from core.settings import settings
                if settings.data_sync.prevent_initial_history_sync:
                    self.logger.warning(
                        f"First sync protected for {self.name}: only syncing latest trade date {latest_trade_date}"
                    )
                    return (latest_trade_date, latest_trade_date, False)
            except Exception:
                pass

            self.logger.info(f"First sync, starting from {history_start}")
            return (history_start, latest_trade_date, True)

        if last_sync_date >= latest_trade_date:
            return None

        last_sync_dt = datetime.strptime(last_sync_date, "%Y%m%d")
        latest_dt = datetime.strptime(latest_trade_date, "%Y%m%d")
        days_diff = (latest_dt - last_sync_dt).days

        is_history_sync = days_diff > threshold
        next_day = (last_sync_dt + timedelta(days=1)).strftime("%Y%m%d")

        sync_type = "历史" if is_history_sync else "增量"
        self.logger.info(
            f"{sync_type}同步: last_sync={last_sync_date}, "
            f"syncing {next_day} -> {latest_trade_date} ({days_diff} days)"
        )

        return (next_day, latest_trade_date, is_history_sync)

    async def _determine_sync_range_simple(
        self,
        latest_trade_date: str,
        initial_sync_days: Optional[int] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        确定简单同步范围（不区分历史/增量，用于 limit_list 等场景）

        Args:
            latest_trade_date: 最新交易日
            initial_sync_days: 首次同步天数，默认使用 self.INITIAL_SYNC_DAYS

        Returns:
            (start_date, end_date) 元组，不需要同步返回 None
        """
        from core.managers.mongo_manager import mongo_manager

        initial_days = initial_sync_days or self.INITIAL_SYNC_DAYS

        last_sync_date = await mongo_manager.get_last_sync_date(self.name)

        if last_sync_date is None:
            try:
                from core.settings import settings
                if settings.data_sync.prevent_initial_history_sync:
                    self.logger.warning(
                        f"First sync protected for {self.name}: only syncing latest trade date {latest_trade_date}"
                    )
                    return (latest_trade_date, latest_trade_date)
                initial_days = min(initial_days, max(1, settings.data_sync.initial_backfill_days))
            except Exception:
                pass

            start_dt = datetime.now() - timedelta(days=initial_days)
            start_date = start_dt.strftime("%Y%m%d")
            self.logger.info(f"First sync, starting from {start_date} (last {initial_days} days)")
            return (start_date, latest_trade_date)

        if last_sync_date >= latest_trade_date:
            return None

        last_sync_dt = datetime.strptime(last_sync_date, "%Y%m%d")
        next_day = (last_sync_dt + timedelta(days=1)).strftime("%Y%m%d")

        self.logger.info(f"Incremental sync: {next_day} -> {latest_trade_date}")

        return (next_day, latest_trade_date)

    async def _write_buffer(
        self,
        buffer: List[Dict[str, Any]],
        collection: str,
        key_fields: List[str],
        batch_size: Optional[int] = None,
    ) -> int:
        """
        批量写入数据到 MongoDB

        Args:
            buffer: 待写入的数据列表
            collection: 目标集合名
            key_fields: 唯一键字段列表
            batch_size: 批次大小，默认使用 self.WRITE_BATCH_SIZE

        Returns:
            实际写入的记录数 (upserted + modified)
        """
        from core.managers.mongo_manager import mongo_manager

        if not buffer:
            return 0
        buffer, bad_records = self._validate_records_with_dead_letters(buffer, collection)
        if bad_records:
            await self._record_dead_letters(collection, bad_records)
        if not buffer:
            self.logger.warning(f"Bulk write [{collection}] skipped: no valid records after validation")
            return 0

        try:
            from core.settings import settings
            default_batch = settings.data_sync.bulk_upsert_batch_size
        except Exception:
            default_batch = self.WRITE_BATCH_SIZE
        batch = batch_size or min(self.WRITE_BATCH_SIZE, default_batch)

        t_start = time.time()
        result = await mongo_manager.bulk_upsert_batched(
            collection=collection,
            documents=buffer,
            key_fields=key_fields,
            batch_size=batch,
        )
        t_end = time.time()

        self.logger.info(
            f"Bulk write [{collection}]: {len(buffer)} records in {t_end-t_start:.2f}s, "
            f"upserted={result['upserted']}, modified={result['modified']}, failed={result['failed']}"
        )

        self._write_results.append(
            {
                "collection": collection,
                "matched": result.get("matched", 0),
                "modified": result.get("modified", 0),
                "inserted": result.get("inserted", result.get("upserted", 0)),
                "upserted": result.get("upserted", 0),
                "failed": result.get("failed", 0),
                "total": result.get("total", len(buffer)),
                "batch_count": result.get("batch_count", 0),
                "batch_size": result.get("batch_size", batch),
                "batch_size_history": result.get("batch_size_history", []),
                "adaptive_batching": result.get("adaptive_batching"),
            }
        )

        return result["upserted"] + result["modified"]

    def _validate_records_for_collection(
        self,
        records: List[Dict[str, Any]],
        collection: str,
    ) -> List[Dict[str, Any]]:
        valid_records, _ = self._validate_records_with_dead_letters(records, collection)
        return valid_records

    def _validate_records_with_dead_letters(
        self,
        records: List[Dict[str, Any]],
        collection: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """核心集合入库前的轻量校验与清洗。

        这里只做最小刚性规则：必填字段、日期标准化、数值安全转换。
        不猜测缺失价格，也不做复杂结构修复。
        """
        schema = self.CORE_RECORD_SCHEMAS.get(collection)
        if not schema:
            return records, []

        valid_records: List[Dict[str, Any]] = []
        bad_samples: List[Dict[str, Any]] = []
        dead_letters: List[Dict[str, Any]] = []
        bad_sample_limit = self._get_bad_record_log_sample_limit()
        required = list(schema.get("required") or [])
        date_fields = set(schema.get("date_fields") or [])
        float_fields = set(schema.get("float_fields") or [])
        int_fields = set(schema.get("int_fields") or [])

        for index, record in enumerate(records):
            cleaned = dict(record)
            reasons: List[str] = []

            for field in date_fields:
                if field in cleaned:
                    normalized_date = self._normalize_yyyymmdd(cleaned.get(field))
                    if normalized_date is None:
                        reasons.append(f"invalid_date:{field}")
                    else:
                        cleaned[field] = normalized_date

            for field in float_fields:
                if field not in cleaned or cleaned.get(field) is None or cleaned.get(field) == "":
                    continue
                value = self._safe_float(cleaned.get(field))
                if value is None:
                    if field in required:
                        reasons.append(f"invalid_float:{field}")
                    else:
                        cleaned.pop(field, None)
                else:
                    cleaned[field] = value

            for field in int_fields:
                if field not in cleaned or cleaned.get(field) is None or cleaned.get(field) == "":
                    continue
                value = self._safe_int(cleaned.get(field))
                if value is None:
                    if field in required:
                        reasons.append(f"invalid_int:{field}")
                    else:
                        cleaned.pop(field, None)
                else:
                    cleaned[field] = value

            for field in required:
                value = cleaned.get(field)
                if value is None or value == "":
                    reasons.append(f"missing_required:{field}")

            if reasons:
                compact_sample = self._compact_bad_record_sample(record)
                if len(bad_samples) < bad_sample_limit:
                    sample = {
                        "index": index,
                        "reasons": reasons,
                        "raw_item": compact_sample,
                    }
                    bad_samples.append(sample)
                if len(dead_letters) < self.DEAD_LETTER_BUFFER_LIMIT:
                    dead_letters.append({
                        "index": index,
                        "reason": ",".join(reasons),
                        "error_type": "validation_failed",
                        "raw_item": compact_sample,
                    })
                continue

            valid_records.append(cleaned)

        bad_count = len(records) - len(valid_records)
        if bad_count > 0:
            log_event(
                self.logger,
                logging.WARNING,
                "datasync_validation_dropped_records",
                job=self.name,
                collection=collection,
                bad_count=bad_count,
                total_count=len(records),
                sample_limit=bad_sample_limit,
                samples=bad_samples,
            )
        return valid_records, dead_letters

    def _get_bad_record_log_sample_limit(self) -> int:
        """Resolve bounded bad-record sample count from OBS config."""
        try:
            from core.settings import settings

            value = int(settings.observability.log_sample_limit)
        except Exception:
            value = int(self.BAD_RECORD_SAMPLE_LIMIT)
        return max(0, min(value, int(self.DEAD_LETTER_BUFFER_LIMIT)))

    async def _record_dead_letters(
        self,
        collection: str,
        bad_records: List[Dict[str, Any]],
    ) -> None:
        if not bad_records:
            return
        try:
            from core.managers.mongo_manager import mongo_manager
            from core.settings import settings

            written = await mongo_manager.record_dead_letters(
                job_name=self.name,
                collection=collection,
                records=bad_records,
                max_records=settings.data_sync.dead_letter_max_records_per_batch,
            )
            if written:
                self.logger.warning(
                    "Recorded %s dead-letter samples for [%s] from job [%s]",
                    written,
                    collection,
                    self.name,
                )
        except Exception as exc:
            self.logger.warning(
                "Failed to record dead-letter samples for [%s] from job [%s]: %s",
                collection,
                self.name,
                exc,
            )

    async def _get_checkpoint(
        self,
        target_trade_date: str,
        window: str,
    ) -> Optional[Dict[str, Any]]:
        """读取当前采集器指定窗口的续跑游标。"""
        try:
            from core.managers.mongo_manager import mongo_manager

            return await mongo_manager.get_checkpoint(
                job_name=self.name,
                target_trade_date=target_trade_date,
                window=window,
            )
        except Exception as exc:
            self.logger.warning(
                "Failed to read checkpoint for job [%s] window [%s]: %s",
                self.name,
                window,
                exc,
            )
            return None

    async def _update_checkpoint(
        self,
        target_trade_date: str,
        window: str,
        *,
        cursor: Optional[Any] = None,
        last_success_key: Optional[str] = None,
        status: str = "running",
        details: Optional[dict] = None,
    ) -> None:
        """更新当前采集器指定窗口的续跑游标。"""
        try:
            from core.managers.mongo_manager import mongo_manager

            await mongo_manager.upsert_checkpoint(
                job_name=self.name,
                target_trade_date=target_trade_date,
                window=window,
                cursor=cursor,
                last_success_key=last_success_key,
                status=status,
                details=details,
            )
        except Exception as exc:
            self.logger.warning(
                "Failed to update checkpoint for job [%s] window [%s]: %s",
                self.name,
                window,
                exc,
            )

    async def _mark_checkpoint_done(
        self,
        target_trade_date: str,
        window: str,
        *,
        details: Optional[dict] = None,
    ) -> None:
        """标记当前采集器指定窗口已经完整完成。"""
        await self._update_checkpoint(
            target_trade_date,
            window,
            status="done",
            details=details or {},
        )

    @staticmethod
    def _normalize_yyyymmdd(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) >= 10 and "-" in text[:10]:
            text = text[:10].replace("-", "")
        if len(text) >= 8 and text[:8].isdigit():
            return text[:8]
        return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        return number

    @staticmethod
    def _compact_bad_record_sample(record: Dict[str, Any]) -> Dict[str, Any]:
        sample: Dict[str, Any] = {}
        for key in list(record.keys())[:12]:
            value = record.get(key)
            if isinstance(value, str) and len(value) > 120:
                sample[key] = f"{value[:120]}..."
            else:
                sample[key] = value
        return sample

    # ==================== 并行采集与失败重试 ====================

    async def _parallel_collect(
        self,
        items: List[T],
        collect_func: Callable[[T], Any],
        max_concurrent: int = 3,
        retry_failures: bool = True,
        item_id_func: Optional[Callable[[T], str]] = None,
    ) -> Dict[str, Any]:
        """
        并行采集多个项目，支持失败记录和自动重试

        Args:
            items: 待采集的项目列表（如日期列表、股票代码列表）
            collect_func: 单个项目的采集函数，签名: async def func(item) -> result
            max_concurrent: 最大并发数
            retry_failures: 是否自动重试之前失败的项目
            item_id_func: 从项目获取唯一标识的函数，默认使用 str(item)

        Returns:
            {
                "total": 总数,
                "success": 成功数,
                "failed": 失败数,
                "results": [结果列表],
                "failed_items": [失败项目列表]
            }
        """
        get_id = item_id_func or str
        try:
            from core.settings import settings
            max_concurrent = min(
                max(1, int(max_concurrent or 1)),
                max(1, int(settings.data_sync.max_parallel_collect_concurrency)),
            )
        except Exception:
            max_concurrent = max(1, int(max_concurrent or 1))

        # 1. 先重试之前失败的项目
        if retry_failures:
            pending_failures = await self._get_pending_failures()
            if pending_failures:
                self.logger.info(f"Retrying {len(pending_failures)} previously failed items...")
                # 将失败项加入队列头部
                failed_ids = {f["item_id"] for f in pending_failures}
                # 过滤掉已在 items 中的
                new_items = [item for item in items if get_id(item) not in failed_ids]
                # 从失败记录中恢复原始项目（如果是简单类型如日期字符串）
                retry_items = [f["item_id"] for f in pending_failures]
                items = retry_items + new_items

        semaphore = asyncio.Semaphore(max_concurrent)
        results = []
        failed_items = []
        success_count = 0
        completed = 0
        total = len(items)

        async def process_item(item: T) -> Dict[str, Any]:
            nonlocal success_count, completed
            item_id = get_id(item)

            async with semaphore:
                try:
                    result = await collect_func(item)
                    success_count += 1
                    # 清除该项的失败记录（如果有）
                    await self._clear_failure(item_id)
                    return {"item_id": item_id, "success": True, "result": result}
                except Exception as e:
                    self.logger.warning(f"Failed to collect {item_id}: {e}")
                    # 记录失败
                    await self._record_failure(item_id, str(e))
                    return {"item_id": item_id, "success": False, "error": str(e)}
                finally:
                    completed += 1
                    if completed % max(1, total // 10) == 0 or completed == total:
                        self.logger.info(f"Progress: {completed}/{total}")

        tasks = [process_item(item) for item in items]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in task_results:
            if isinstance(r, Exception):
                failed_items.append({"error": str(r)})
            elif isinstance(r, dict):
                results.append(r)
                if not r.get("success"):
                    failed_items.append(r)

        return {
            "total": total,
            "success": success_count,
            "failed": len(failed_items),
            "results": results,
            "failed_items": failed_items,
        }

    async def _record_failure(
        self,
        item_id: str,
        error_msg: str,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录采集失败的项目

        Args:
            item_id: 项目唯一标识（如日期、股票代码）
            error_msg: 错误信息
            extra_data: 额外数据
        """
        from core.managers.mongo_manager import mongo_manager

        try:
            db = mongo_manager.db
            collection = db["sync_failures"]

            doc = {
                "collector": self.name,
                "item_id": item_id,
                "error": error_msg,
                "retry_count": 0,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            if extra_data:
                doc["extra"] = extra_data

            # 更新或插入
            await collection.update_one(
                {"collector": self.name, "item_id": item_id},
                {
                    "$set": {
                        "error": error_msg,
                        "updated_at": datetime.now(UTC),
                    },
                    "$inc": {"retry_count": 1},
                    "$setOnInsert": {
                        "collector": self.name,
                        "item_id": item_id,
                        "created_at": datetime.now(UTC),
                    },
                },
                upsert=True,
            )

            # 确保索引
            await collection.create_index([("collector", 1), ("item_id", 1)], unique=True)
            await collection.create_index("created_at")

        except Exception as e:
            self.logger.error(f"Failed to record failure for {item_id}: {e}")

    async def _get_pending_failures(
        self,
        max_retry: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取待重试的失败项目

        Args:
            max_retry: 最大重试次数，超过则不再重试，默认使用 self.MAX_RETRY_COUNT

        Returns:
            失败记录列表
        """
        from core.managers.mongo_manager import mongo_manager

        max_count = max_retry or self.MAX_RETRY_COUNT

        try:
            db = mongo_manager.db
            collection = db["sync_failures"]

            cursor = collection.find({
                "collector": self.name,
                "retry_count": {"$lt": max_count},
            }).sort("created_at", 1)

            return await cursor.to_list(None)

        except Exception as e:
            self.logger.error(f"Failed to get pending failures: {e}")
            return []

    async def _clear_failure(self, item_id: str) -> None:
        """
        清除指定项目的失败记录

        Args:
            item_id: 项目唯一标识
        """
        from core.managers.mongo_manager import mongo_manager

        try:
            db = mongo_manager.db
            await db["sync_failures"].delete_one({
                "collector": self.name,
                "item_id": item_id,
            })
        except Exception as e:
            self.logger.error(f"Failed to clear failure for {item_id}: {e}")

    async def _clear_all_failures(self) -> int:
        """
        清除该采集器的所有失败记录

        Returns:
            删除的记录数
        """
        from core.managers.mongo_manager import mongo_manager

        try:
            db = mongo_manager.db
            result = await db["sync_failures"].delete_many({"collector": self.name})
            return result.deleted_count
        except Exception as e:
            self.logger.error(f"Failed to clear all failures: {e}")
            return 0

    async def _get_failure_stats(self) -> Dict[str, Any]:
        """
        获取该采集器的失败统计

        Returns:
            {
                "total": 总失败数,
                "pending": 待重试数,
                "exhausted": 已耗尽重试次数的数量
            }
        """
        from core.managers import mongo_manager

        try:
            db = mongo_manager.db
            collection = db["sync_failures"]

            total = await collection.count_documents({"collector": self.name})
            pending = await collection.count_documents({
                "collector": self.name,
                "retry_count": {"$lt": self.MAX_RETRY_COUNT},
            })

            return {
                "total": total,
                "pending": pending,
                "exhausted": total - pending,
            }
        except Exception as e:
            self.logger.error(f"Failed to get failure stats: {e}")
            return {"total": 0, "pending": 0, "exhausted": 0}
