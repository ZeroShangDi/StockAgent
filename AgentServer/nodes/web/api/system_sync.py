"""系统页手动补漏同步后台任务。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from core.managers import (
    analysis_manager,
    data_source_manager,
    mongo_manager,
    stock_relation_manager,
)
from nodes.data_sync.collectors.stock.daily_basic import _clean_daily_basic_record
from scripts.sync_stock_daily import (
    sync_index_daily_for_date,
    sync_limit_list_for_date,
    sync_stock_daily_for_date,
)


_RUNTIME_TASKS: set[asyncio.Task] = set()
_TASK_TYPE = "system_gap_fill_sync"
_CORE_INDEX_CODES = ("000001.SH", "399001.SZ", "399006.SZ")


async def create_manual_gap_fill_task(user_id: str, lookback_days: int = 3) -> Dict[str, Any]:
    """创建最近交易日补漏同步任务。"""
    normalized_days = max(1, min(int(lookback_days or 3), 10))

    existing_task = await mongo_manager.find_one(
        "tasks",
        {
            "user_id": user_id,
            "task_type": _TASK_TYPE,
            "status": {"$in": ["pending", "queued", "running"]},
        },
        sort=[("created_at", -1)],
    )
    if existing_task:
        return existing_task

    now = datetime.now(UTC)
    task_id = uuid.uuid4().hex
    task_doc = {
        "task_id": task_id,
        "trace_id": uuid.uuid4().hex,
        "task_type": _TASK_TYPE,
        "status": "queued",
        "progress": 0,
        "current_step": "排队中",
        "message": f"已创建最近 {normalized_days} 个交易日的轻量补漏同步任务",
        "params": {
            "mode": "gap_fill_recent_days",
            "lookback_days": normalized_days,
        },
        "user_id": user_id,
        "node_id": "web",
        "ts_codes": [],
        "stock_names": [],
        "query": None,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error_message": None,
        "execution_time_ms": 0,
        "created_at": now,
    }
    await mongo_manager.insert_one("tasks", task_doc)

    runtime_task = asyncio.create_task(
        _run_manual_gap_fill_task(task_id=task_id, user_id=user_id, lookback_days=normalized_days)
    )
    _RUNTIME_TASKS.add(runtime_task)
    runtime_task.add_done_callback(_RUNTIME_TASKS.discard)
    return task_doc


async def get_manual_gap_fill_task(user_id: str, task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """查询手动补漏同步任务状态。"""
    query: Dict[str, Any] = {
        "user_id": user_id,
        "task_type": _TASK_TYPE,
    }
    if task_id:
        query["task_id"] = task_id
        return await mongo_manager.find_one("tasks", query)
    return await mongo_manager.find_one("tasks", query, sort=[("created_at", -1)])


async def _run_manual_gap_fill_task(task_id: str, user_id: str, lookback_days: int) -> None:
    started_at = datetime.now(UTC)
    initialized_managers: List[Any] = []
    step_errors: List[Dict[str, str]] = []
    completed_dates: List[str] = []

    async def step(progress: int, current_step: str, message: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "status": "running",
            "progress": progress,
            "current_step": current_step,
            "started_at": started_at,
        }
        if message is not None:
            payload["message"] = message
        await _update_manual_gap_fill_task(task_id, **payload)

    try:
        await step(5, "初始化依赖", "正在准备数据源与分析管理器")
        initialized_managers = await _initialize_optional_managers()

        trade_dates = await _get_recent_trade_dates(lookback_days)
        await step(12, "检查缺口", f"正在检查最近 {len(trade_dates)} 个交易日的数据完整性")

        if not trade_dates:
            await _finalize_manual_gap_fill_task(
                task_id,
                status="completed",
                started_at=started_at,
                message="最近交易日列表为空，无需补漏",
                result={
                    "lookback_days": lookback_days,
                    "checked_dates": [],
                    "pending_dates": [],
                    "completed_dates": [],
                    "step_errors": [],
                },
            )
            return

        active_stock_count = await mongo_manager.count("stock_basic", {"list_status": "L"})
        gap_plans = []
        for trade_date in trade_dates:
            plan = await _inspect_gap_for_trade_date(trade_date, active_stock_count)
            if plan["required_steps"]:
                gap_plans.append(plan)

        if not gap_plans:
            await _finalize_manual_gap_fill_task(
                task_id,
                status="completed",
                started_at=started_at,
                message=f"最近 {len(trade_dates)} 个交易日未发现明显缺口",
                result={
                    "lookback_days": lookback_days,
                    "checked_dates": trade_dates,
                    "pending_dates": [],
                    "completed_dates": [],
                    "step_errors": [],
                },
            )
            return

        total_dates = len(gap_plans)
        for index, plan in enumerate(gap_plans, start=1):
            trade_date = plan["trade_date"]
            required_steps = plan["required_steps"]
            base_progress = 15 + int(((index - 1) / max(total_dates, 1)) * 70)
            await step(
                base_progress,
                f"补最近交易日 ({index}/{total_dates})",
                f"{trade_date} 待补步骤：{' / '.join(required_steps)}",
            )

            date_errors = await _sync_trade_date_gap(trade_date, plan)
            if date_errors:
                step_errors.extend(date_errors)
            else:
                completed_dates.append(trade_date)

        has_partial_errors = bool(step_errors)
        summary_message = (
            f"补漏完成，成功处理 {len(completed_dates)} 个交易日"
            if not has_partial_errors
            else f"补漏完成，但仍有 {len(step_errors)} 个步骤失败"
        )
        await _finalize_manual_gap_fill_task(
            task_id,
            status="completed",
            started_at=started_at,
            message=summary_message,
            result={
                "lookback_days": lookback_days,
                "checked_dates": trade_dates,
                "pending_dates": [plan["trade_date"] for plan in gap_plans],
                "completed_dates": completed_dates,
                "step_errors": step_errors,
                "plans": [
                    {
                        "trade_date": plan["trade_date"],
                        "required_steps": plan["required_steps"],
                    }
                    for plan in gap_plans
                ],
            },
        )
    except Exception as exc:
        await _finalize_manual_gap_fill_task(
            task_id,
            status="failed",
            started_at=started_at,
            message="补漏同步失败",
            error_message=str(exc),
            result={
                "lookback_days": lookback_days,
                "completed_dates": completed_dates,
                "step_errors": step_errors,
            },
        )
    finally:
        await _shutdown_optional_managers(initialized_managers)


async def _initialize_optional_managers() -> List[Any]:
    initialized_managers: List[Any] = []
    for manager in (data_source_manager, analysis_manager, stock_relation_manager):
        if getattr(manager, "_initialized", False):
            continue
        await manager.initialize()
        initialized_managers.append(manager)
    return initialized_managers


async def _shutdown_optional_managers(managers: List[Any]) -> None:
    for manager in reversed(managers):
        try:
            await manager.shutdown()
        except Exception:
            continue


async def _update_manual_gap_fill_task(task_id: str, **fields: Any) -> None:
    await mongo_manager.update_one("tasks", {"task_id": task_id}, {"$set": fields})


async def _finalize_manual_gap_fill_task(
    task_id: str,
    status: str,
    started_at: datetime,
    message: str,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    completed_at = datetime.now(UTC)
    execution_time_ms = int((completed_at - started_at).total_seconds() * 1000)
    payload: Dict[str, Any] = {
        "status": status,
        "progress": 100,
        "current_step": "完成" if status == "completed" else "失败",
        "message": message,
        "completed_at": completed_at,
        "execution_time_ms": execution_time_ms,
        "result": result,
        "error_message": error_message,
    }
    await _update_manual_gap_fill_task(task_id, **payload)


async def _get_recent_trade_dates(days: int) -> List[str]:
    latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
    if not latest_trade_date:
        return []

    latest_dt = datetime.strptime(latest_trade_date, "%Y%m%d")
    start_date = (latest_dt - timedelta(days=max(days, 1) * 3)).strftime("%Y%m%d")
    trade_dates, _ = await data_source_manager.get_trade_calendar(start_date, latest_trade_date)
    if not trade_dates:
        return []
    sorted_dates = sorted(trade_dates)
    return sorted_dates[-days:]


async def _inspect_gap_for_trade_date(trade_date: str, active_stock_count: int) -> Dict[str, Any]:
    stock_threshold = max(int(active_stock_count * 0.7), 1000) if active_stock_count else 1000
    basic_threshold = max(int(active_stock_count * 0.6), 1000) if active_stock_count else 1000

    stock_daily_count = await mongo_manager.count("stock_daily", {"trade_date": trade_date})
    daily_basic_count = await mongo_manager.count("daily_basic", {"trade_date": trade_date})
    index_daily_count = await mongo_manager.count(
        "index_daily",
        {"trade_date": trade_date, "ts_code": {"$in": list(_CORE_INDEX_CODES)}},
    )
    limit_list_count = await mongo_manager.count("limit_list", {"trade_date": trade_date})
    daily_stats_count = await mongo_manager.count("daily_stats", {"trade_date": trade_date})
    market_analysis_count = await mongo_manager.count("market_analysis", {"trade_date": trade_date})
    relation_count = await mongo_manager.count(
        "stock_relations",
        {"source": "limit_list", "source_trade_date": trade_date},
    )

    required_steps: List[str] = []
    if stock_daily_count < stock_threshold:
        required_steps.append("stock_daily")
    if daily_basic_count < basic_threshold:
        required_steps.append("daily_basic")
    if index_daily_count < len(_CORE_INDEX_CODES):
        required_steps.append("index_daily")
    if limit_list_count <= 0:
        required_steps.append("limit_list")
    if daily_stats_count <= 0:
        required_steps.append("daily_stats")
    if market_analysis_count <= 0:
        required_steps.append("market_analysis")
    if limit_list_count > 0 and relation_count <= 0:
        required_steps.append("stock_relations")

    return {
        "trade_date": trade_date,
        "required_steps": required_steps,
        "counts": {
            "stock_daily": stock_daily_count,
            "daily_basic": daily_basic_count,
            "index_daily": index_daily_count,
            "limit_list": limit_list_count,
            "daily_stats": daily_stats_count,
            "market_analysis": market_analysis_count,
            "stock_relations": relation_count,
        },
    }


async def _sync_trade_date_gap(trade_date: str, plan: Dict[str, Any]) -> List[Dict[str, str]]:
    required_steps = plan["required_steps"]
    errors: List[Dict[str, str]] = []
    failed_steps: set[str] = set()

    async def run_step(step_name: str, coro: Any) -> None:
        try:
            result = await coro
            if step_name in {"stock_daily", "index_daily", "limit_list"}:
                count = int(result.get("count", 0) or 0)
                if count > 0:
                    await mongo_manager.record_sync(step_name, trade_date, count=count)
            elif step_name == "daily_basic":
                count = int(result.get("count", 0) or 0)
                if count > 0:
                    await mongo_manager.record_sync("daily_basic", trade_date, count=count)
            elif step_name == "daily_stats":
                await mongo_manager.record_sync("daily_stats", trade_date, count=1)
            elif step_name == "market_analysis":
                await mongo_manager.record_sync("market_analysis", trade_date, count=1)
            elif step_name == "stock_relations":
                count = int(result.get("dynamic_docs", 0) or 0) + int(result.get("static_docs", 0) or 0)
                if count > 0:
                    await mongo_manager.record_sync("stock_relations", trade_date, count=count)
        except Exception as exc:
            failed_steps.add(step_name)
            errors.append(
                {
                    "trade_date": trade_date,
                    "step": step_name,
                    "error": str(exc),
                }
            )

    if "stock_daily" in required_steps:
        await run_step("stock_daily", sync_stock_daily_for_date(trade_date))
    if "daily_basic" in required_steps:
        await run_step("daily_basic", _sync_daily_basic_for_date(trade_date))
    if "index_daily" in required_steps:
        await run_step("index_daily", sync_index_daily_for_date(trade_date))
    if "limit_list" in required_steps:
        await run_step("limit_list", sync_limit_list_for_date(trade_date))
    if "daily_stats" in required_steps and not (failed_steps & {"stock_daily", "index_daily", "limit_list"}):
        await run_step("daily_stats", _recalc_daily_stats_for_date(trade_date))
    elif "daily_stats" in required_steps:
        errors.append(
            {
                "trade_date": trade_date,
                "step": "daily_stats",
                "error": "前置数据同步失败，已跳过 daily_stats 重算",
            }
        )
        failed_steps.add("daily_stats")
    if "market_analysis" in required_steps and "daily_stats" not in failed_steps:
        await run_step("market_analysis", _recalc_market_analysis_for_date(trade_date))
    elif "market_analysis" in required_steps:
        errors.append(
            {
                "trade_date": trade_date,
                "step": "market_analysis",
                "error": "daily_stats 重算未完成，已跳过 market_analysis 重算",
            }
        )
        failed_steps.add("market_analysis")
    if (("stock_relations" in required_steps) or ("limit_list" in required_steps)) and "limit_list" not in failed_steps:
        await run_step("stock_relations", stock_relation_manager.sync_relations(snapshot_trade_date=trade_date))
    elif ("stock_relations" in required_steps) or ("limit_list" in required_steps):
        errors.append(
            {
                "trade_date": trade_date,
                "step": "stock_relations",
                "error": "limit_list 同步未完成，已跳过股票关系快照同步",
            }
        )

    return errors


async def _sync_daily_basic_for_date(trade_date: str) -> Dict[str, Any]:
    records, source = await data_source_manager.get_daily_basic(
        trade_date=trade_date,
        preferred_source="tushare",
    )
    if not records:
        return {"date": trade_date, "count": 0, "source": source}

    cleaned_records: List[Dict[str, Any]] = []
    now = datetime.now(UTC)
    for record in records:
        cleaned = _clean_daily_basic_record(record)
        if not cleaned.get("trade_date") or not cleaned.get("ts_code"):
            continue
        cleaned["updated_at"] = now
        cleaned_records.append(cleaned)

    if not cleaned_records:
        return {"date": trade_date, "count": 0, "source": source}

    result = await mongo_manager.bulk_upsert(
        collection="daily_basic",
        documents=cleaned_records,
        key_fields=["ts_code", "trade_date"],
        batch_size=5000,
    )
    count = result.get("upserted", 0) + result.get("modified", 0)
    return {"date": trade_date, "count": count, "source": source}


async def _recalc_daily_stats_for_date(trade_date: str) -> Dict[str, Any]:
    from scripts.recalc_daily_stats import compute_daily_stats_for_date

    stats = await compute_daily_stats_for_date(trade_date)
    stats["updated_at"] = datetime.utcnow()
    await mongo_manager.update_one(
        "daily_stats",
        {"trade_date": trade_date},
        {"$set": stats},
        upsert=True,
    )
    return {"trade_date": trade_date, "count": 1}


async def _recalc_market_analysis_for_date(trade_date: str) -> Dict[str, Any]:
    stats = await mongo_manager.find_one("daily_stats", {"trade_date": trade_date})
    if not stats:
        raise ValueError(f"{trade_date} 缺少 daily_stats，无法重算 market_analysis")

    prev_stats = await mongo_manager.find_one(
        "daily_stats",
        {"trade_date": {"$lt": trade_date}},
        sort=[("trade_date", -1)],
    )
    await analysis_manager.analyze_and_store(
        stats=stats,
        prev_stats=prev_stats,
        mongo_manager=mongo_manager,
    )
    return {"trade_date": trade_date, "count": 1}
