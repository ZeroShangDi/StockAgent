"""
市场晴雨表服务。

职责：
- 调用 Coze 市场晴雨表工作流
- 解析并标准化日度结果
- 计算交易信号
- 将数据持久化到 MongoDB
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from core.managers import data_source_manager, mongo_manager
from core.settings import settings

from .coze_workflow_client import CozeWorkflowClient


class MarketWeatherService:
    COLLECTION = "market_weather_daily"

    def __init__(
        self,
        workflow_id: Optional[str] = None,
        client: Optional[CozeWorkflowClient] = None,
    ) -> None:
        self._workflow_id = workflow_id or settings.coze.market_indicator_workflow_id
        self._client = client or CozeWorkflowClient()

    @staticmethod
    def _to_trade_date(value: str) -> str:
        return value.replace("-", "").strip()

    @staticmethod
    def _to_display_date(value: str) -> str:
        trade_date = value.replace("-", "").strip()
        if len(trade_date) == 8:
            return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        return value

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _parse_indicator(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        decoded = self._client.decode_json_like(payload.get("data"))
        if not isinstance(decoded, dict):
            raise RuntimeError("市场晴雨表返回格式异常")
        indicator = self._client.decode_json_like(decoded.get("getMarketIndicator"))
        if not isinstance(indicator, dict) or not indicator:
            raise RuntimeError("市场晴雨表返回空结果")
        return indicator

    def _build_signal(self, indicator: Dict[str, Any]) -> Dict[str, Any]:
        temp = self._safe_float(indicator.get("市场温度指数"))
        limit = self._safe_float(indicator.get("涨停溢价延续因子"))
        trend = self._safe_float(indicator.get("趋势惯性累积因子"))
        volume = self._safe_float(indicator.get("量价共振强度因子"))
        breadth = self._safe_float(indicator.get("市场广度扩散因子"))
        momentum = self._safe_float(indicator.get("多空动能极化因子"))

        position = temp * 0.4
        position += limit * 20
        position += (trend * 0.6 + volume * 0.4) * 20
        position -= ((1 - breadth) * 0.6 + (1 - momentum) * 0.4) * 15

        if temp > 70 and momentum > 0.7:
            position += 5
        elif temp < 30 and momentum < 0.3:
            position -= 5

        position = max(10, min(90, round(position)))

        if position <= 30:
            action = "持币"
        elif position <= 45:
            action = "观望"
        elif position <= 65:
            action = "持筹"
        else:
            action = "积极"

        if (temp < 35 and limit < 0.5 and momentum < 0.4) or (temp < 40 and volume > 0.7 and momentum < 0.5):
            strategy = "低吸"
        elif (limit > 0.7 and trend > 0.6 and temp > 60) or (temp > 65 and breadth > 0.7 and momentum > 0.6):
            strategy = "追高"
        elif trend > 0.45 and volume > 0.45:
            strategy = "波段"
        else:
            strategy = "防守"

        if action == "持币":
            note = f"市场偏冷（{int(temp)} 度），建议持币等待转暖"
            if strategy == "低吸":
                note += "，仅小仓位低吸超跌品种"
        elif action == "观望":
            note = f"市场温度 {int(temp)} 度，方向不明，建议观望为主"
            if strategy == "低吸":
                note += "，可轻仓低吸试错"
            elif strategy == "防守":
                note += "，适当控制仓位"
        elif action == "持筹":
            note = f"市场温度适中（{int(temp)} 度），可适度参与"
            if strategy == "波段":
                note += "，进行波段操作"
            elif strategy == "低吸":
                note += "，逢低吸纳"
        else:
            note = f"市场活跃（{int(temp)} 度），可积极操作"
            if strategy == "追高":
                note += "，追高强势品种"
            elif strategy == "波段":
                note += "，把握波段机会"

        if breadth < 0.4:
            note += f"，注意市场广度不足（{breadth * 100:.1f}%）"
        if momentum < 0.3:
            note += f"，多空动能偏弱（{momentum * 100:.1f}%）"
        if volume > 0.85 and trend < 0.5:
            note += "，注意量价背离风险"
        if limit > 0.8 and breadth < 0.5:
            note += "，提防高溢价陷阱"

        return {
            "做不做": action,
            "做多少": position,
            "做什么": strategy,
            "说明": note,
        }

    def rebuild_signal_for_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        indicator = record.get("indicator")
        if isinstance(indicator, dict) and indicator:
            return self._build_signal(indicator)
        return record.get("signal") or {}

    def _build_record(self, indicator: Dict[str, Any], raw_payload: Dict[str, Any], source: str = "coze") -> Dict[str, Any]:
        display_date = str(indicator.get("数据截止日期") or "").strip()
        if not display_date:
            raise RuntimeError("市场晴雨表缺少数据截止日期")
        trade_date = self._to_trade_date(display_date)
        signal = self._build_signal(indicator)
        return {
            "trade_date": trade_date,
            "display_trade_date": self._to_display_date(display_date),
            "source": source,
            "workflow_id": self._workflow_id,
            "indicator": indicator,
            "signal": signal,
            "temperature_index": self._safe_float(indicator.get("市场温度指数")),
            "limit_premium_factor": self._safe_float(indicator.get("涨停溢价延续因子")),
            "trend_factor": self._safe_float(indicator.get("趋势惯性累积因子")),
            "volume_factor": self._safe_float(indicator.get("量价共振强度因子")),
            "breadth_factor": self._safe_float(indicator.get("市场广度扩散因子")),
            "momentum_factor": self._safe_float(indicator.get("多空动能极化因子")),
            "raw_payload": raw_payload,
            "synced_at": datetime.now(UTC),
        }

    async def fetch_one(self, trade_date: Optional[str] = None) -> Dict[str, Any]:
        if not self._workflow_id:
            raise RuntimeError("COZE_MARKET_INDICATOR_WORKFLOW_ID 未配置")
        params: Dict[str, Any] = {"type": "市场晴雨表"}
        if trade_date:
            params["date"] = self._to_display_date(trade_date)
        payload = await self._client.run(self._workflow_id, params)
        indicator = self._parse_indicator(payload)
        return self._build_record(indicator, payload)

    async def store_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        await mongo_manager.update_one(
            self.COLLECTION,
            {"trade_date": record["trade_date"]},
            {"$set": record},
            upsert=True,
        )
        return record

    async def ensure_latest(self) -> Dict[str, Any]:
        latest = await mongo_manager.find_one(
            self.COLLECTION,
            {},
            sort=[("trade_date", -1)],
        )
        if latest:
            return latest
        record = await self.fetch_one()
        return await self.store_record(record)

    async def list_history(self, days: int = 30) -> List[Dict[str, Any]]:
        history = await mongo_manager.find_many(
            self.COLLECTION,
            {},
            sort=[("trade_date", -1)],
            limit=days,
        )
        history.reverse()
        return history

    async def list_history_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 0,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        trade_date_query: Dict[str, str] = {}
        if start_date:
            trade_date_query["$gte"] = self._to_trade_date(start_date)
        if end_date:
            trade_date_query["$lte"] = self._to_trade_date(end_date)
        if trade_date_query:
            query["trade_date"] = trade_date_query

        history = await mongo_manager.find_many(
            self.COLLECTION,
            query,
            sort=[("trade_date", 1)],
            limit=limit,
        )
        return history

    async def get_trade_dates_between(self, start_date: str, end_date: str) -> List[str]:
        if not await data_source_manager.health_check():
            await data_source_manager.initialize()
        trade_dates, _ = await data_source_manager.get_trade_calendar(
            self._to_trade_date(start_date),
            self._to_trade_date(end_date),
        )
        return trade_dates or []

    async def get_recent_trade_dates(self, days: int = 30) -> List[str]:
        if not await data_source_manager.health_check():
            await data_source_manager.initialize()
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        if not latest_trade_date:
            raise RuntimeError("无法获取最近交易日")
        start_date = (datetime.strptime(latest_trade_date, "%Y%m%d") - timedelta(days=max(days * 3, 30))).strftime("%Y%m%d")
        trade_dates, _ = await data_source_manager.get_trade_calendar(start_date, latest_trade_date)
        if not trade_dates:
            return [latest_trade_date]
        return trade_dates[-days:]

    async def sync_trade_dates(self, trade_dates: List[str], overwrite: bool = False) -> Dict[str, Any]:
        if not await data_source_manager.health_check():
            await data_source_manager.initialize()

        success = 0
        skipped = 0
        failed = 0
        errors: List[Dict[str, str]] = []
        records: List[Dict[str, Any]] = []
        pending_dates: List[str] = []

        for trade_date in trade_dates:
            if not overwrite:
                existing = await mongo_manager.find_one(self.COLLECTION, {"trade_date": trade_date}, projection={"trade_date": 1})
                if existing:
                    skipped += 1
                    continue
            pending_dates.append(trade_date)

        semaphore = asyncio.Semaphore(4)

        async def _fetch(trade_date: str) -> Dict[str, Any]:
            async with semaphore:
                return await self.fetch_one(trade_date)

        tasks = {trade_date: asyncio.create_task(_fetch(trade_date)) for trade_date in pending_dates}
        for trade_date, task in tasks.items():
            try:
                records.append(await task)
                success += 1
            except Exception as exc:
                failed += 1
                errors.append({"trade_date": trade_date, "error": str(exc)})

        if records:
            await mongo_manager.bulk_upsert(
                self.COLLECTION,
                records,
                key_fields=["trade_date"],
                batch_size=200,
            )

        return {
            "requested": len(trade_dates),
            "success": success,
            "skipped": skipped,
            "failed": failed,
            "errors": errors[:20],
        }

    async def sync_recent(self, days: int = 30, overwrite: bool = False) -> Dict[str, Any]:
        trade_dates = await self.get_recent_trade_dates(days)
        return await self.sync_trade_dates(trade_dates, overwrite=overwrite)

    async def sync_range(
        self,
        start_date: str,
        end_date: str,
        overwrite: bool = False,
        descending: bool = True,
        sleep_seconds: float = 0.35,
        stop_on_empty_streak: Optional[int] = 30,
        request_timeout_seconds: float = 12.0,
    ) -> Dict[str, Any]:
        trade_dates = await self.get_trade_dates_between(start_date, end_date)
        if descending:
            trade_dates = list(reversed(trade_dates))

        success = 0
        skipped = 0
        failed = 0
        empty = 0
        empty_streak = 0
        stopped_early = False
        stop_reason = ""
        first_success: Optional[str] = None
        last_success: Optional[str] = None
        errors: List[Dict[str, str]] = []

        for trade_date in trade_dates:
            if not overwrite:
                existing = await mongo_manager.find_one(
                    self.COLLECTION,
                    {"trade_date": trade_date},
                    projection={"trade_date": 1},
                )
                if existing:
                    skipped += 1
                    continue

            try:
                record = await asyncio.wait_for(
                    self.fetch_one(trade_date),
                    timeout=request_timeout_seconds,
                )
                await self.store_record(record)
                success += 1
                empty_streak = 0
                if not first_success:
                    first_success = record["trade_date"]
                last_success = record["trade_date"]
            except Exception as exc:
                if isinstance(exc, TimeoutError):
                    message = f"请求超时（>{request_timeout_seconds:.1f}s）"
                else:
                    message = str(exc)
                errors.append({"trade_date": trade_date, "error": message})
                if "返回空结果" in message:
                    empty += 1
                    empty_streak += 1
                    if stop_on_empty_streak and empty_streak >= stop_on_empty_streak:
                        stopped_early = True
                        stop_reason = f"连续 {empty_streak} 个交易日返回空结果，推测已超出 Coze 历史可用范围"
                        break
                else:
                    failed += 1
                    empty_streak = 0

            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

        return {
            "requested": len(trade_dates),
            "success": success,
            "skipped": skipped,
            "failed": failed,
            "empty": empty,
            "stopped_early": stopped_early,
            "stop_reason": stop_reason,
            "first_success": first_success,
            "last_success": last_success,
            "errors": errors[:50],
        }

    async def get_coverage_summary(self) -> Dict[str, Any]:
        collection = mongo_manager.db[self.COLLECTION]
        count = await collection.count_documents({})
        earliest = await mongo_manager.find_one(self.COLLECTION, {}, sort=[("trade_date", 1)])
        latest = await mongo_manager.find_one(self.COLLECTION, {}, sort=[("trade_date", -1)])
        return {
            "count": count,
            "earliest_trade_date": earliest.get("trade_date") if earliest else None,
            "latest_trade_date": latest.get("trade_date") if latest else None,
            "earliest_display_trade_date": earliest.get("display_trade_date") if earliest else None,
            "latest_display_trade_date": latest.get("display_trade_date") if latest else None,
        }


market_weather_service = MarketWeatherService()
