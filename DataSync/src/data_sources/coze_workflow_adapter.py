"""
Coze 工作流数据源适配器

通过统一的 Coze Workflow 调用股票插件能力，并映射为项目内部标准数据结构。
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import (
    AsyncDataSourceAdapter,
    DataSourceCapability,
    DataSourceType,
    DailyRecord,
    IndexDailyRecord,
    RealtimeQuoteRecord,
    StockBasicRecord,
)
from .http_client import UnifiedHttpClient


class CozeWorkflowAdapter(AsyncDataSourceAdapter):
    """基于 Coze 工作流的股票数据源适配器"""

    MAX_STOCK_K_RANGE_DAYS = 700

    CORE_INDEX_CODES = {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
    }

    PERIOD_TO_K_TYPE = {
        "day": 1,
        "week": 2,
        "month": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
    }

    ADJ_TO_COZE = {
        None: 1,
        "": 1,
        "qfq": 1,
        "hfq": 2,
        "none": 0,
        "bfq": 0,
    }

    def __init__(
        self,
        api_token: Optional[str] = None,
        workflow_id: Optional[str] = None,
        api_base: Optional[str] = None,
        space_id: Optional[str] = None,
        app_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        timeout: float = 30.0,
    ):
        super().__init__()
        self._api_token = api_token
        self._workflow_id = workflow_id
        self._api_base = api_base
        self._space_id = space_id
        self._app_id = app_id
        self._bot_id = bot_id
        self._timeout = timeout
        self._max_retries = 2
        self._retry_backoff_seconds = 0.5
        self._retry_backoff_max_seconds = 5.0
        self._http_client: Optional[UnifiedHttpClient] = None

    @property
    def name(self) -> str:
        return "coze"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.COZE

    @property
    def capability(self) -> DataSourceCapability:
        return DataSourceCapability(
            stock_basic=True,
            daily_quotes=True,
            daily_basic=True,
            realtime_quotes=True,
            financial_data=True,
            money_flow=False,
            limit_data=False,
            index_data=True,
            trade_calendar=True,
            news=False,
            kline=True,
        )

    def _get_default_priority(self) -> int:
        return 90

    async def initialize(self) -> None:
        """初始化 Coze 工作流连接"""
        if self._initialized:
            return

        try:
            from core.settings import settings

            config = settings.coze
            if not self._api_token:
                self._api_token = config.api_token.get_secret_value()
            if not self._workflow_id:
                self._workflow_id = config.workflow_id
            if not self._api_base:
                self._api_base = config.api_base
            if not self._space_id:
                self._space_id = config.space_id
            if not self._app_id:
                self._app_id = config.app_id
            if not self._bot_id:
                self._bot_id = config.bot_id
            if self._timeout == 30.0:
                self._timeout = config.timeout
            self._max_retries = config.max_retries
            self._retry_backoff_seconds = config.retry_backoff_seconds
            self._retry_backoff_max_seconds = config.retry_backoff_max_seconds
        except Exception:
            pass

        if not self._api_token or not self._workflow_id:
            self.logger.warning("Coze workflow config incomplete, skipping initialization")
            return

        self._api_base = (self._api_base or "https://api.coze.cn").rstrip("/")
        self._http_client = UnifiedHttpClient(
            source=self.name,
            timeout=self._timeout,
            retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
            max_backoff_seconds=self._retry_backoff_max_seconds,
            headers={
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            },
        )
        self._initialized = True
        self.logger.info(
            "Coze workflow adapter initialized ✓ (workflow_id=%s, space_id=%s)",
            self._workflow_id,
            self._space_id or "N/A",
        )

    async def shutdown(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
        self._http_client = None
        self._initialized = False
        self.logger.info("Coze workflow adapter shutdown")

    async def is_available(self) -> bool:
        return self._initialized and self._http_client is not None

    async def health_check(self) -> bool:
        if not await self.is_available():
            return False
        try:
            payload = await self._run_plugin("stock_current", {"stock_code": "000001"})
            record = self._extract_first_record(payload)
            return bool(record and record.get("stock_code") == "000001")
        except Exception as e:
            self.logger.warning("Coze workflow health check failed: %s", e)
            return False

    async def _run_plugin(self, plugin: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not await self.is_available():
            raise RuntimeError("Coze workflow adapter not initialized")

        assert self._http_client is not None
        body: Dict[str, Any] = {
            "workflow_id": self._workflow_id,
            "parameters": {
                "plugin": plugin,
                "params": params or {},
            },
        }
        if self._app_id:
            body["app_id"] = self._app_id
        if self._bot_id:
            body["bot_id"] = self._bot_id

        payload = await self._http_client.request_json(
            "POST",
            f"{self._api_base}/v1/workflow/run",
            json=body,
        )
        debug_url = payload.get("debug_url")
        code = payload.get("code", 0)
        msg = payload.get("msg") or payload.get("error_message") or ""
        if code and int(code) > 0:
            raise RuntimeError(f"Coze plugin {plugin} failed: code={code}, msg={msg}, debug_url={debug_url}")

        data = self._decode_json_like(payload.get("data"))
        if isinstance(data, dict):
            return data
        if data is None:
            return {}
        return {"data": data}

    def _decode_json_like(self, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return self._decode_json_like(json.loads(stripped))
                except json.JSONDecodeError:
                    return value
            return value
        if isinstance(value, list):
            return [self._decode_json_like(item) for item in value]
        if isinstance(value, dict):
            return {key: self._decode_json_like(item) for key, item in value.items()}
        return value

    def _extract_data_list(self, payload: Any, preferred_keys: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        keys = preferred_keys or []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            value = payload.get("data")
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return self._extract_data_list(value, preferred_keys=preferred_keys)
        return []

    def _extract_first_record(self, payload: Any, preferred_keys: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        items = self._extract_data_list(payload, preferred_keys=preferred_keys)
        return items[0] if items else None

    def _plugin_stock_code(self, ts_code: str) -> str:
        return self._extract_code(self._normalize_ts_code(ts_code))

    def _plugin_index_code(self, ts_code: str) -> str:
        return self._extract_code(ts_code.upper())

    def _normalize_exchange(self, exchange: Optional[str], code: str) -> str:
        exchange = (exchange or "").upper()
        if exchange in {"SH", "SZ", "BJ"}:
            return exchange
        normalized = self._normalize_ts_code(code)
        return normalized.split(".")[1]

    def _format_coze_date(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        value = str(value).strip()
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        return value

    def _normalize_trade_date(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            # 时间戳（秒/毫秒）常见于实时接口
            timestamp = float(value)
            if timestamp >= 100_000_000_000:
                timestamp /= 1000.0
            try:
                return datetime.fromtimestamp(timestamp).strftime("%Y%m%d")
            except (ValueError, OSError):
                return None

        text = str(value).strip()
        if not text:
            return None
        if len(text) >= 10 and "-" in text[:10]:
            return text[:10].replace("-", "")
        if len(text) == 8 and text.isdigit():
            return text
        if text.isdigit() and len(text) == 13:
            return self._normalize_trade_date(int(text))
        return None

    def _normalize_list_date(self, value: Any) -> str:
        trade_date = self._normalize_trade_date(value)
        return trade_date or ""

    def _parse_ymd(self, value: Optional[str]) -> Optional[datetime]:
        normalized = self._normalize_trade_date(value)
        if not normalized:
            return None
        return datetime.strptime(normalized, "%Y%m%d")

    def _split_date_windows(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        max_days: int,
    ) -> List[tuple[Optional[str], Optional[str]]]:
        start_dt = self._parse_ymd(start_date)
        end_dt = self._parse_ymd(end_date)

        if not start_dt or not end_dt or start_dt > end_dt:
            return [(start_date, end_date)]

        windows: List[tuple[Optional[str], Optional[str]]] = []
        current = start_dt
        while current <= end_dt:
            window_end = min(current + timedelta(days=max_days - 1), end_dt)
            windows.append((current.strftime("%Y%m%d"), window_end.strftime("%Y%m%d")))
            current = window_end + timedelta(days=1)
        return windows

    async def _fetch_stock_k_items(
        self,
        normalized_ts_code: str,
        *,
        k_type: int,
        adjust_type: int,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> List[Dict[str, Any]]:
        windows = self._split_date_windows(
            start_date=start_date,
            end_date=end_date,
            max_days=self.MAX_STOCK_K_RANGE_DAYS,
        )
        items: List[Dict[str, Any]] = []
        seen = set()

        for window_start, window_end in windows:
            payload = await self._run_plugin(
                "stock_k",
                {
                    "stock_code": self._plugin_stock_code(normalized_ts_code),
                    "k_type": k_type,
                    "adjust_type": adjust_type,
                    "start_date": self._format_coze_date(window_start),
                    "end_date": self._format_coze_date(window_end),
                },
            )
            for item in self._extract_data_list(payload):
                trade_date = self._normalize_trade_date(
                    item.get("trade_date") or item.get("trade_time") or item.get("time")
                )
                unique_key = trade_date or json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                items.append(item)

        items.sort(
            key=lambda item: self._normalize_trade_date(
                item.get("trade_date") or item.get("trade_time") or item.get("time")
            ) or ""
        )
        return items

    def _parse_stock_basic_item(self, item: Dict[str, Any]) -> Optional[StockBasicRecord]:
        code = str(item.get("stock_code") or item.get("code") or item.get("symbol") or "").strip()
        if not code:
            return None
        exchange = self._normalize_exchange(item.get("exchange"), code)
        ts_code = f"{code.zfill(6)}.{exchange}"
        return {
            "ts_code": ts_code,
            "symbol": code.zfill(6),
            "name": str(item.get("short_name") or item.get("name") or ""),
            "area": str(item.get("area") or ""),
            "industry": str(item.get("industry") or ""),
            "market": str(item.get("market") or exchange),
            "list_date": self._normalize_list_date(item.get("list_date")),
            "list_status": "L",
        }

    def _build_minimal_stock_basic(self, ts_code: str, name: str = "") -> StockBasicRecord:
        normalized_ts_code = self._normalize_ts_code(ts_code)
        symbol = self._extract_code(normalized_ts_code)
        market = normalized_ts_code.split(".")[1]
        return {
            "ts_code": normalized_ts_code,
            "symbol": symbol,
            "name": name or normalized_ts_code,
            "area": "",
            "industry": "",
            "market": market,
            "list_date": "",
            "list_status": "L",
        }

    def _parse_daily_item(self, item: Dict[str, Any], ts_code: str) -> Optional[DailyRecord]:
        trade_date = self._normalize_trade_date(item.get("trade_date") or item.get("trade_time") or item.get("time"))
        if not trade_date:
            return None
        record: DailyRecord = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": self._safe_float(item.get("open")),
            "high": self._safe_float(item.get("high")),
            "low": self._safe_float(item.get("low")),
            "close": self._safe_float(item.get("close") or item.get("price")),
            "pre_close": self._safe_float(item.get("pre_close")),
            "change": self._safe_float(item.get("change")),
            "pct_chg": self._safe_float(item.get("change_pct") or item.get("pct_chg")),
            "vol": self._safe_float(item.get("volume") or item.get("vol")),
            "amount": self._safe_float(item.get("amount")),
        }
        return record

    def _parse_realtime_item(self, item: Dict[str, Any], ts_code: str, name: str = "") -> RealtimeQuoteRecord:
        price = self._safe_float(item.get("price") or item.get("close"))
        return {
            "ts_code": ts_code,
            "name": name or str(item.get("short_name") or item.get("name") or ts_code),
            "price": price,
            "close": price,
            "open": self._safe_float(item.get("open")),
            "high": self._safe_float(item.get("high")),
            "low": self._safe_float(item.get("low")),
            "pre_close": self._safe_float(item.get("pre_close")),
            "change": self._safe_float(item.get("change")),
            "pct_chg": self._safe_float(item.get("change_pct") or item.get("pct_chg")),
            "vol": self._safe_float(item.get("volume") or item.get("vol")),
            "amount": self._safe_float(item.get("amount")),
            "trade_date": self._normalize_trade_date(item.get("trade_date") or item.get("trade_time")),
        }

    async def get_stock_basic(
        self,
        ts_code: Optional[str] = None,
        list_status: str = "L",
    ) -> List[StockBasicRecord]:
        if list_status != "L":
            return []

        payload = await self._run_plugin("info_all_code")
        items = self._extract_data_list(payload, preferred_keys=["stock_code_list"])

        results: List[StockBasicRecord] = []
        target_ts_code = self._normalize_ts_code(ts_code) if ts_code else None
        for item in items:
            parsed = self._parse_stock_basic_item(item)
            if not parsed:
                continue
            if target_ts_code and parsed["ts_code"] != target_ts_code:
                continue
            results.append(parsed)

        if target_ts_code and not results:
            try:
                payload = await self._run_plugin(
                    "stock_current",
                    {"stock_code": self._plugin_stock_code(target_ts_code)},
                )
                item = self._extract_first_record(payload)
                if item:
                    results.append(
                        self._build_minimal_stock_basic(
                            ts_code=target_ts_code,
                            name=str(item.get("short_name") or item.get("name") or ""),
                        )
                    )
            except Exception as e:
                self.logger.warning("Coze stock_basic fallback failed for %s: %s", target_ts_code, e)
        return results

    async def get_daily(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adj: str = "qfq",
    ) -> List[DailyRecord]:
        if not ts_code or "," in ts_code:
            return []

        normalized_ts_code = self._normalize_ts_code(ts_code)
        if trade_date:
            start_date = trade_date
            end_date = trade_date

        items = await self._fetch_stock_k_items(
            normalized_ts_code,
            k_type=1,
            adjust_type=self.ADJ_TO_COZE.get((adj or "").lower(), 1),
            start_date=start_date,
            end_date=end_date,
        )
        results = [record for item in items if (record := self._parse_daily_item(item, normalized_ts_code))]
        results.sort(key=lambda item: item["trade_date"])
        return results

    async def get_realtime_quotes(
        self,
        ts_codes: Optional[List[str]] = None,
        batch_size: int = 8,
        timeout: float = 10.0,
    ) -> Dict[str, RealtimeQuoteRecord]:
        if not ts_codes:
            return {}

        semaphore = asyncio.Semaphore(max(1, batch_size))

        async def fetch_one(raw_code: str) -> Optional[tuple[str, RealtimeQuoteRecord]]:
            normalized_ts_code = self._normalize_ts_code(raw_code)
            async with semaphore:
                payload = await self._run_plugin(
                    "stock_current",
                    {"stock_code": self._plugin_stock_code(normalized_ts_code)},
                )
            item = self._extract_first_record(payload)
            if not item:
                return None
            return normalized_ts_code, self._parse_realtime_item(item, normalized_ts_code)

        tasks = [fetch_one(code) for code in ts_codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        quotes: Dict[str, RealtimeQuoteRecord] = {}
        for result in results:
            if isinstance(result, Exception):
                self.logger.warning("Coze realtime quote fetch failed: %s", result)
                continue
            if result is None:
                continue
            ts_code, quote = result
            quotes[ts_code] = quote
        return quotes

    async def get_daily_basic(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not ts_code or "," in ts_code:
            return []

        normalized_ts_code = self._normalize_ts_code(ts_code)
        if trade_date:
            start_date = trade_date
            end_date = trade_date

        daily_items = await self._fetch_stock_k_items(
            normalized_ts_code,
            k_type=1,
            adjust_type=1,
            start_date=start_date,
            end_date=end_date,
        )
        if not daily_items:
            return []

        shares_payload = await self._run_plugin(
            "stock_shares",
            {"stock_code": self._plugin_stock_code(normalized_ts_code)},
        )
        shares_item = self._extract_first_record(shares_payload)

        financial_records = await self.get_financial_indicator(normalized_ts_code, limit=1)
        financial_item = financial_records[0] if financial_records else {}

        total_share = self._safe_float((shares_item or {}).get("total_shares"))
        float_share = self._safe_float((shares_item or {}).get("list_a_shares"))
        basic_eps = self._safe_float(financial_item.get("basic_eps"))
        net_asset_ps = self._safe_float(financial_item.get("net_asset_ps"))

        result: List[Dict[str, Any]] = []
        for item in daily_items:
            trade_date_normalized = self._normalize_trade_date(item.get("trade_date") or item.get("trade_time"))
            if not trade_date_normalized:
                continue

            close = self._safe_float(item.get("close") or item.get("price"))
            total_mv = None
            circ_mv = None
            pe = None
            pb = None

            if close is not None:
                if total_share is not None:
                    total_mv = close * total_share / 100000000
                if float_share is not None:
                    circ_mv = close * float_share / 100000000
                if basic_eps not in (None, 0):
                    pe = close / basic_eps
                if net_asset_ps not in (None, 0):
                    pb = close / net_asset_ps

            result.append(
                {
                    "ts_code": normalized_ts_code,
                    "trade_date": trade_date_normalized,
                    "close": close,
                    "turnover_rate": self._safe_float(item.get("turnover_ratio") or item.get("turnover_rate")),
                    "pe": pe,
                    "pb": pb,
                    "total_share": total_share,
                    "float_share": float_share,
                    "total_mv": total_mv,
                    "circ_mv": circ_mv,
                }
            )
        return result

    async def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        payload = await self._run_plugin(
            "stock_fin_data",
            {"stock_code": self._plugin_stock_code(ts_code)},
        )
        items = self._extract_data_list(payload)

        normalized_ts_code = self._normalize_ts_code(ts_code)
        results: List[Dict[str, Any]] = []
        for item in items:
            row = dict(item)
            row["ts_code"] = normalized_ts_code
            if "report_date" in row:
                row["end_date"] = self._normalize_trade_date(row["report_date"])
            if "notice_date" in row:
                row["ann_date"] = self._normalize_trade_date(row["notice_date"])
            results.append(row)

        if period:
            results = [row for row in results if row.get("end_date") == period]
        if limit is not None:
            results = results[:limit]
        return results

    async def get_financial_data(
        self,
        ts_code: str,
        limit: int = 4,
    ) -> Dict[str, Any]:
        indicators = await self.get_financial_indicator(ts_code=ts_code, limit=limit)
        return {"fina_indicator": indicators}

    async def get_index_basic(
        self,
        market: str = "SSE",
        ts_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records = [
            {
                "ts_code": "000001.SH",
                "name": "上证指数",
                "fullname": "上证综合指数",
                "market": "SSE",
                "publisher": "上海证券交易所",
                "index_type": "综合指数",
                "category": "宽基",
                "base_date": "19901219",
                "base_point": 100.0,
                "list_date": "19910715",
            },
            {
                "ts_code": "399001.SZ",
                "name": "深证成指",
                "fullname": "深证成份指数",
                "market": "SZSE",
                "publisher": "深圳证券交易所",
                "index_type": "成份指数",
                "category": "宽基",
                "base_date": "19940720",
                "base_point": 1000.0,
                "list_date": "19950123",
            },
            {
                "ts_code": "399006.SZ",
                "name": "创业板指",
                "fullname": "创业板指数",
                "market": "SZSE",
                "publisher": "深圳证券交易所",
                "index_type": "成份指数",
                "category": "成长",
                "base_date": "20100531",
                "base_point": 1000.0,
                "list_date": "20100601",
            },
        ]

        if ts_code:
            normalized = ts_code.upper()
            return [record for record in records if record["ts_code"] == normalized]

        if market and market.upper() in {"SSE", "SH"}:
            return [record for record in records if record["ts_code"].endswith(".SH")]
        if market and market.upper() in {"SZSE", "SZ"}:
            return [record for record in records if record["ts_code"].endswith(".SZ")]
        return records

    async def get_realtime_index_quotes(self) -> Dict[str, RealtimeQuoteRecord]:
        results: Dict[str, RealtimeQuoteRecord] = {}

        for ts_code, name in self.CORE_INDEX_CODES.items():
            payload = await self._run_plugin(
                "index_current_data",
                {"index_code": self._plugin_index_code(ts_code)},
            )
            item = self._extract_first_record(payload)
            if not item:
                continue
            results[ts_code] = self._parse_realtime_item(item, ts_code, name=name)
        return results

    async def get_index_daily(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[IndexDailyRecord]:
        payload = await self._run_plugin(
            "index_k",
            {
                "index_code": self._plugin_index_code(ts_code),
                "k_type": 1,
                "start_date": self._format_coze_date(start_date),
            },
        )
        items = self._extract_data_list(payload)
        results: List[IndexDailyRecord] = []
        normalized_ts_code = ts_code.upper()
        end_date_normalized = self._normalize_trade_date(end_date) if end_date else None

        for item in items:
            parsed = self._parse_daily_item(item, normalized_ts_code)
            if not parsed:
                continue
            if end_date_normalized and parsed["trade_date"] > end_date_normalized:
                continue
            results.append(parsed)  # type: ignore[arg-type]

        results.sort(key=lambda item: item["trade_date"])
        return results

    async def get_latest_trade_date(self) -> Optional[str]:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        records = await self.get_daily(
            ts_code="000001.SZ",
            start_date=start_date,
            end_date=datetime.now().strftime("%Y%m%d"),
        )
        if not records:
            return None
        return records[-1]["trade_date"]

    async def get_trade_calendar(
        self,
        start_date: str,
        end_date: str,
    ) -> List[str]:
        records = await self.get_daily(
            ts_code="000001.SZ",
            start_date=start_date,
            end_date=end_date,
        )
        dates = [record["trade_date"] for record in records if record.get("trade_date")]
        return sorted(set(dates))

    async def get_kline(
        self,
        code: str,
        period: str = "day",
        limit: int = 120,
        adj: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_code = code.upper()
        start_date = (datetime.now() - timedelta(days=max(limit * 3, 30))).strftime("%Y%m%d")
        k_type = self.PERIOD_TO_K_TYPE.get(period, 1)

        if normalized_code in self.CORE_INDEX_CODES or normalized_code.startswith("399"):
            payload = await self._run_plugin(
                "index_k",
                {
                    "index_code": self._plugin_index_code(normalized_code),
                    "k_type": k_type if k_type in {1, 2, 3} else 1,
                    "start_date": self._format_coze_date(start_date),
                },
            )
            items = self._extract_data_list(payload)
            result: List[Dict[str, Any]] = []
            for item in items[-limit:]:
                trade_date = item.get("trade_date") or item.get("trade_time") or item.get("time")
                result.append(
                    {
                        "time": str(trade_date),
                        "open": self._safe_float(item.get("open")),
                        "high": self._safe_float(item.get("high")),
                        "low": self._safe_float(item.get("low")),
                        "close": self._safe_float(item.get("close") or item.get("price")),
                        "volume": self._safe_float(item.get("volume") or item.get("vol")),
                        "amount": self._safe_float(item.get("amount")),
                    }
                )
            return result

        payload = await self._run_plugin(
            "stock_k",
            {
                "stock_code": self._plugin_stock_code(normalized_code),
                "k_type": k_type,
                "adjust_type": self.ADJ_TO_COZE.get((adj or "").lower(), 1),
                "start_date": self._format_coze_date(start_date),
            },
        )
        items = self._extract_data_list(payload)
        result = []
        for item in items[-limit:]:
            result.append(
                {
                    "time": str(item.get("trade_time") or item.get("trade_date") or ""),
                    "open": self._safe_float(item.get("open")),
                    "high": self._safe_float(item.get("high")),
                    "low": self._safe_float(item.get("low")),
                    "close": self._safe_float(item.get("close") or item.get("price")),
                    "volume": self._safe_float(item.get("volume") or item.get("vol")),
                    "amount": self._safe_float(item.get("amount")),
                }
            )
        return result
