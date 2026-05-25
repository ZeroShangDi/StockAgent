"""
交割单复盘服务。

第一版能力：
- 交割单分组
- CSV 导入与去重
- 逐笔复盘备注
- 基础统计
- 复盘 K 线上下文
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from core.managers import mongo_manager
from src.analysis.stock_chart_context import (
    build_period_candles,
    calculate_recent_return,
    get_stock_sector_context,
    serialize_daily_record,
)


class TradeReviewService:
    GROUP_COLLECTION = "trade_review_groups"
    BATCH_COLLECTION = "trade_review_import_batches"
    RECORD_COLLECTION = "trade_review_records"
    POSITION_COLLECTION = "trade_review_positions"
    MAX_GROUPS_PER_USER = 500
    MAX_POSITIONS_PER_GROUP = 10000
    MAX_TRADE_RECORDS_FOR_ANALYSIS = 50000
    MAX_IMPORT_DEDUPE_RECORDS = 100000
    MAX_REVIEW_NAV_RECORDS = 10000
    MAX_RELATED_STOCK_RECORDS = 500
    MAX_DAILY_ROWS_PER_STOCK = 6000

    REQUIRED_HEADERS = [
        "日期",
        "业务类型",
        "股东账号",
        "证券代码",
        "证券名称",
        "成交数量",
        "成交均价",
        "佣金",
        "印花税",
        "其他费",
        "过户费",
        "清算费",
        "发生金额",
        "资金余额",
        "币种",
        "备注",
        "数据来源",
    ]

    TRADE_BUY_TYPES = {"证券买入"}
    TRADE_SELL_TYPES = {"证券卖出"}

    def _normalize_result_reasons(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            if "verdict" in value or "reasons" in value:
                verdict = str(value.get("verdict") or "").strip()
                reasons = [str(item).strip() for item in (value.get("reasons") or []) if str(item).strip()]
                return {
                    "verdict": verdict if verdict in {"success", "failure"} else "",
                    "reasons": reasons,
                }

            success = [str(item).strip() for item in (value.get("success") or []) if str(item).strip()]
            failure = [str(item).strip() for item in (value.get("failure") or []) if str(item).strip()]
            if failure:
                return {"verdict": "failure", "reasons": failure}
            if success:
                return {"verdict": "success", "reasons": success}
        return {"verdict": "", "reasons": []}

    def _to_trade_date(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y%m%d")
            except ValueError:
                continue
        return text.replace("-", "").replace("/", "")

    def _safe_float(self, value: Any) -> float:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _safe_int(self, value: Any) -> int:
        return int(round(self._safe_float(value)))

    def _normalize_code(self, value: Any) -> str:
        digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
        return digits.zfill(6) if digits else ""

    def _infer_ts_code(self, code: str) -> str:
        if not code:
            return ""
        if code.startswith(("6", "5", "9")):
            return f"{code}.SH"
        if code.startswith(("8", "4", "92")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    def _classify_record(self, business_type: str) -> Dict[str, Any]:
        if business_type in self.TRADE_BUY_TYPES:
            return {"category": "trade", "side": "buy", "is_trade_record": True}
        if business_type in self.TRADE_SELL_TYPES:
            return {"category": "trade", "side": "sell", "is_trade_record": True}
        if any(token in business_type for token in ["银行", "转存管", "托管"]):
            return {"category": "cash", "side": None, "is_trade_record": False}
        if any(token in business_type for token in ["利息", "股息", "红股"]):
            return {"category": "income", "side": None, "is_trade_record": False}
        if any(token in business_type for token in ["申购", "中签", "新股"]):
            return {"category": "subscription", "side": None, "is_trade_record": False}
        if any(token in business_type for token in ["质押回购", "拆出"]):
            return {"category": "repo", "side": None, "is_trade_record": False}
        return {"category": "other", "side": None, "is_trade_record": False}

    def _legacy_dedupe_key(self, row: Dict[str, Any], code: str, trade_date: str) -> str:
        parts = [
            trade_date,
            row.get("业务类型", "").strip(),
            code,
            row.get("证券名称", "").strip(),
            str(row.get("成交数量", "")).strip(),
            str(row.get("成交均价", "")).strip(),
            str(row.get("发生金额", "")).strip(),
            str(row.get("备注", "")).strip(),
            str(row.get("数据来源", "")).strip(),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def _dedupe_key(self, row: Dict[str, Any], code: str, trade_date: str) -> str:
        normalized_row = {
            str(key).strip(): str(value or "").strip()
            for key, value in sorted(row.items(), key=lambda item: str(item[0]))
        }
        parts = [
            trade_date,
            code,
            json.dumps(normalized_row, ensure_ascii=False, sort_keys=True),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    async def _load_symbol_map(self, codes: List[str]) -> Dict[str, str]:
        if not codes:
            return {}
        docs = await mongo_manager.find_many(
            "stock_basic",
            {"symbol": {"$in": list(sorted(set(codes)))}},
            projection={"symbol": 1, "ts_code": 1},
            limit=len(set(codes)),
        )
        return {
            str(doc.get("symbol", "")).zfill(6): str(doc.get("ts_code", "")).upper()
            for doc in docs
            if doc.get("symbol") and doc.get("ts_code")
        }

    def _serialize_group(self, group: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "group_id": group.get("group_id"),
            "name": group.get("name"),
            "description": group.get("description"),
            "record_count": group.get("record_count", 0),
            "trade_record_count": group.get("trade_record_count", 0),
            "last_imported_at": group.get("last_imported_at"),
            "created_at": group.get("created_at"),
            "updated_at": group.get("updated_at"),
        }

    async def list_groups(self, user_id: str) -> List[Dict[str, Any]]:
        groups = await mongo_manager.find_many(
            self.GROUP_COLLECTION,
            {"user_id": user_id},
            sort=[("updated_at", -1)],
            limit=self.MAX_GROUPS_PER_USER,
        )
        return [self._serialize_group(item) for item in groups]

    async def create_group(self, user_id: str, name: str, description: Optional[str] = None) -> Dict[str, Any]:
        record = {
            "group_id": uuid.uuid4().hex,
            "user_id": user_id,
            "name": name.strip(),
            "description": description.strip() if description else None,
            "record_count": 0,
            "trade_record_count": 0,
            "last_imported_at": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        await mongo_manager.update_one(
            self.GROUP_COLLECTION,
            {"group_id": record["group_id"]},
            {"$set": record},
            upsert=True,
        )
        return self._serialize_group(record)

    async def get_group(self, user_id: str, group_id: str) -> Optional[Dict[str, Any]]:
        group = await mongo_manager.find_one(
            self.GROUP_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
        )
        return self._serialize_group(group) if group else None

    def _trade_fee(self, item: Dict[str, Any]) -> float:
        return round(
            float(item.get("commission", 0) or 0)
            + float(item.get("stamp_tax", 0) or 0)
            + float(item.get("other_fee", 0) or 0)
            + float(item.get("transfer_fee", 0) or 0)
            + float(item.get("clearing_fee", 0) or 0),
            4,
        )

    async def _load_latest_price_map(self, ts_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        if not ts_codes:
            return {}

        pipeline = [
            {"$match": {"ts_code": {"$in": list(sorted(set(ts_codes)))}}},
            {"$sort": {"ts_code": 1, "trade_date": -1}},
            {
                "$group": {
                    "_id": "$ts_code",
                    "close": {"$first": "$close"},
                    "trade_date": {"$first": "$trade_date"},
                }
            },
        ]
        docs = await mongo_manager.aggregate("stock_daily", pipeline, limit=len(set(ts_codes)))
        return {
            str(doc.get("_id")): {
                "latest_price": float(doc.get("close") or 0),
                "latest_trade_date": str(doc.get("trade_date") or ""),
            }
            for doc in docs
            if doc.get("_id")
        }

    async def _load_stock_basic_meta(self, ts_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        if not ts_codes:
            return {}
        docs = await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": list(sorted(set(ts_codes)))}},
            projection={"ts_code": 1, "name": 1, "market": 1},
            limit=len(set(ts_codes)),
        )
        return {
            str(doc.get("ts_code")): {
                "name": doc.get("name"),
                "market": doc.get("market"),
            }
            for doc in docs
            if doc.get("ts_code")
        }

    def _serialize_position(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "position_id": item.get("position_id"),
            "group_id": item.get("group_id"),
            "ts_code": item.get("ts_code"),
            "code": item.get("code"),
            "name": item.get("name"),
            "quantity": int(item.get("quantity", 0) or 0),
            "avg_cost": round(float(item.get("avg_cost", 0) or 0), 4),
            "total_cost": round(float(item.get("total_cost", 0) or 0), 2),
            "latest_price": round(float(item.get("latest_price", 0) or 0), 4) if item.get("latest_price") is not None else None,
            "latest_trade_date": item.get("latest_trade_date"),
            "market_value": round(float(item.get("market_value", 0) or 0), 2),
            "unrealized_pnl": round(float(item.get("unrealized_pnl", 0) or 0), 2),
            "unrealized_pnl_pct": round(float(item.get("unrealized_pnl_pct", 0) or 0), 2),
            "buy_count": int(item.get("buy_count", 0) or 0),
            "sell_count": int(item.get("sell_count", 0) or 0),
            "total_buy_amount": round(float(item.get("total_buy_amount", 0) or 0), 2),
            "total_sell_amount": round(float(item.get("total_sell_amount", 0) or 0), 2),
            "first_trade_date": item.get("first_trade_date"),
            "last_trade_date": item.get("last_trade_date"),
            "price_source": item.get("price_source", "stock_daily_latest_close"),
            "security_type": item.get("security_type", "other"),
            "updated_at": item.get("updated_at"),
        }

    async def rebuild_positions(self, *, user_id: str, group_id: str) -> Dict[str, Any]:
        group = await mongo_manager.find_one(self.GROUP_COLLECTION, {"group_id": group_id, "user_id": user_id})
        if not group:
            raise ValueError("交割单分组不存在")

        trade_record_count = await mongo_manager.count(
            self.RECORD_COLLECTION,
            {
                "group_id": group_id,
                "user_id": user_id,
                "is_trade_record": True,
                "side": {"$in": ["buy", "sell"]},
                "ts_code": {"$ne": ""},
            },
        )
        if trade_record_count > self.MAX_TRADE_RECORDS_FOR_ANALYSIS:
            raise ValueError("交割单交易记录过多，请先按账户或时间拆分后再重建持仓")

        trade_records = await mongo_manager.find_many(
            self.RECORD_COLLECTION,
            {
                "group_id": group_id,
                "user_id": user_id,
                "is_trade_record": True,
                "side": {"$in": ["buy", "sell"]},
                "ts_code": {"$ne": ""},
            },
            projection={
                "ts_code": 1,
                "code": 1,
                "security_name": 1,
                "trade_date": 1,
                "side": 1,
                "quantity": 1,
                "amount": 1,
                "commission": 1,
                "stamp_tax": 1,
                "other_fee": 1,
                "transfer_fee": 1,
                "clearing_fee": 1,
                "_id": 0,
            },
            sort=[("trade_date", 1), ("row_no", 1)],
            limit=self.MAX_TRADE_RECORDS_FOR_ANALYSIS,
        )

        buckets: Dict[str, Dict[str, Any]] = {}
        for item in trade_records:
            ts_code = str(item.get("ts_code") or "").upper().strip()
            if not ts_code:
                continue

            state = buckets.setdefault(
                ts_code,
                {
                    "position_id": uuid.uuid4().hex,
                    "group_id": group_id,
                    "user_id": user_id,
                    "ts_code": ts_code,
                    "code": item.get("code"),
                    "name": item.get("security_name") or item.get("code"),
                    "quantity": 0,
                    "total_cost": 0.0,
                    "buy_count": 0,
                    "sell_count": 0,
                    "total_buy_amount": 0.0,
                    "total_sell_amount": 0.0,
                    "first_trade_date": item.get("trade_date"),
                    "last_trade_date": item.get("trade_date"),
                },
            )

            quantity = abs(int(item.get("quantity", 0) or 0))
            if quantity <= 0:
                continue

            amount = abs(float(item.get("amount", 0) or 0))
            fee = self._trade_fee(item)
            state["last_trade_date"] = item.get("trade_date")
            if not state.get("first_trade_date"):
                state["first_trade_date"] = item.get("trade_date")

            if item.get("side") == "buy":
                state["quantity"] += quantity
                state["total_cost"] += amount + fee
                state["buy_count"] += 1
                state["total_buy_amount"] += amount
            elif item.get("side") == "sell":
                state["sell_count"] += 1
                state["total_sell_amount"] += amount
                current_qty = int(state.get("quantity", 0) or 0)
                if current_qty <= 0:
                    state["quantity"] = 0
                    state["total_cost"] = 0.0
                    continue
                avg_cost = float(state.get("total_cost", 0) or 0) / current_qty if current_qty else 0.0
                reduce_qty = min(current_qty, quantity)
                state["quantity"] = current_qty - reduce_qty
                state["total_cost"] = max(0.0, float(state.get("total_cost", 0) or 0) - avg_cost * reduce_qty)

        active_positions = [item for item in buckets.values() if int(item.get("quantity", 0) or 0) > 0]
        latest_price_map = await self._load_latest_price_map([item["ts_code"] for item in active_positions])
        stock_basic_meta = await self._load_stock_basic_meta([item["ts_code"] for item in active_positions])

        now = datetime.now(UTC)
        position_docs: List[Dict[str, Any]] = []
        total_cost = 0.0
        total_market_value = 0.0
        profitable_count = 0
        loss_count = 0
        latest_valuation_date = ""

        for item in active_positions:
            latest_info = latest_price_map.get(item["ts_code"], {})
            latest_price = latest_info.get("latest_price")
            latest_trade_date = latest_info.get("latest_trade_date")
            latest_valuation_date = max(latest_valuation_date, latest_trade_date or "")
            quantity = int(item.get("quantity", 0) or 0)
            current_total_cost = round(float(item.get("total_cost", 0) or 0), 2)
            avg_cost = round(current_total_cost / quantity, 4) if quantity > 0 else 0.0
            market_value = round((latest_price or 0.0) * quantity, 2) if latest_price else 0.0
            unrealized_pnl = round(market_value - current_total_cost, 2) if latest_price else 0.0
            unrealized_pnl_pct = round((unrealized_pnl / current_total_cost * 100), 2) if latest_price and current_total_cost > 0 else 0.0
            if latest_price:
                if unrealized_pnl > 0:
                    profitable_count += 1
                elif unrealized_pnl < 0:
                    loss_count += 1
            total_cost += current_total_cost
            total_market_value += market_value

            position_docs.append(
                {
                    **item,
                    "name": stock_basic_meta.get(item["ts_code"], {}).get("name") or item.get("name"),
                    "avg_cost": avg_cost,
                    "total_cost": current_total_cost,
                    "latest_price": latest_price,
                    "latest_trade_date": latest_trade_date,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "price_source": "stock_daily_latest_close",
                    "security_type": "stock" if item["ts_code"] in stock_basic_meta else "other",
                    "updated_at": now,
                }
            )

        await mongo_manager.delete_many(self.POSITION_COLLECTION, {"group_id": group_id, "user_id": user_id})
        if position_docs:
            await mongo_manager.insert_many(self.POSITION_COLLECTION, position_docs)

        summary = {
            "position_count": len(position_docs),
            "total_cost": round(total_cost, 2),
            "total_market_value": round(total_market_value, 2),
            "total_unrealized_pnl": round(total_market_value - total_cost, 2),
            "total_unrealized_pnl_pct": round(((total_market_value - total_cost) / total_cost * 100), 2) if total_cost > 0 else 0.0,
            "profitable_count": profitable_count,
            "loss_count": loss_count,
            "latest_valuation_date": latest_valuation_date or None,
            "updated_at": now,
        }

        await mongo_manager.update_one(
            self.GROUP_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
            {
                "$set": {
                    "position_summary": summary,
                    "positions_updated_at": now,
                    "updated_at": now,
                }
            },
        )

        refreshed_group = await mongo_manager.find_one(self.GROUP_COLLECTION, {"group_id": group_id, "user_id": user_id})
        return {
            "group": self._serialize_group(refreshed_group or group),
            "summary": summary,
            "items": [self._serialize_position(item) for item in sorted(position_docs, key=lambda doc: float(doc.get("market_value", 0) or 0), reverse=True)],
        }

    async def get_positions(self, *, user_id: str, group_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        group = await mongo_manager.find_one(self.GROUP_COLLECTION, {"group_id": group_id, "user_id": user_id})
        if not group:
            raise ValueError("交割单分组不存在")

        if force_refresh:
            return await self.rebuild_positions(user_id=user_id, group_id=group_id)

        docs = await mongo_manager.find_many(
            self.POSITION_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
            sort=[("market_value", -1), ("unrealized_pnl_pct", -1)],
            limit=self.MAX_POSITIONS_PER_GROUP,
        )
        if not docs and int(group.get("trade_record_count", 0) or 0) > 0:
            return await self.rebuild_positions(user_id=user_id, group_id=group_id)

        return {
            "group": self._serialize_group(group),
            "summary": group.get("position_summary") or {
                "position_count": 0,
                "total_cost": 0.0,
                "total_market_value": 0.0,
                "total_unrealized_pnl": 0.0,
                "total_unrealized_pnl_pct": 0.0,
                "profitable_count": 0,
                "loss_count": 0,
                "latest_valuation_date": None,
                "updated_at": group.get("positions_updated_at"),
            },
            "items": [self._serialize_position(item) for item in docs],
        }

    async def import_csv(
        self,
        *,
        user_id: str,
        group_id: str,
        filename: str,
        content: bytes,
    ) -> Dict[str, Any]:
        group = await mongo_manager.find_one(
            self.GROUP_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
        )
        if not group:
            raise ValueError("交割单分组不存在")

        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        missing_headers = [header for header in self.REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            raise ValueError(f"CSV 缺少必要列：{', '.join(missing_headers)}")

        raw_rows = [row for row in reader]
        codes = [self._normalize_code(row.get("证券代码")) for row in raw_rows if self._normalize_code(row.get("证券代码"))]
        symbol_map = await self._load_symbol_map(codes)

        prepared_records: List[Dict[str, Any]] = []
        for idx, row in enumerate(raw_rows, start=2):
            code = self._normalize_code(row.get("证券代码"))
            trade_date = self._to_trade_date(row.get("日期", ""))
            business_type = str(row.get("业务类型", "")).strip()
            ts_code = symbol_map.get(code) or self._infer_ts_code(code) if code else ""
            classification = self._classify_record(business_type)
            dedupe_key = self._dedupe_key(row, code, trade_date)
            legacy_dedupe_key = self._legacy_dedupe_key(row, code, trade_date)

            prepared_records.append(
                {
                    "record_id": uuid.uuid4().hex,
                    "group_id": group_id,
                    "user_id": user_id,
                    "row_no": idx,
                    "trade_date": trade_date,
                    "business_type": business_type,
                    "shareholder_account": str(row.get("股东账号", "")).strip() or None,
                    "code": code,
                    "ts_code": ts_code,
                    "security_name": str(row.get("证券名称", "")).strip() or None,
                    "quantity": abs(self._safe_int(row.get("成交数量"))) if classification["is_trade_record"] else self._safe_int(row.get("成交数量")),
                    "price": self._safe_float(row.get("成交均价")),
                    "commission": self._safe_float(row.get("佣金")),
                    "stamp_tax": self._safe_float(row.get("印花税")),
                    "other_fee": self._safe_float(row.get("其他费")),
                    "transfer_fee": self._safe_float(row.get("过户费")),
                    "clearing_fee": self._safe_float(row.get("清算费")),
                    "amount": self._safe_float(row.get("发生金额")),
                    "balance": self._safe_float(row.get("资金余额")),
                    "currency": str(row.get("币种", "")).strip() or None,
                    "remark": str(row.get("备注", "")).strip() or None,
                    "source_label": str(row.get("数据来源", "")).strip() or None,
                    "category": classification["category"],
                    "side": classification["side"],
                    "is_trade_record": classification["is_trade_record"],
                    "reviewed": False,
                    "operation_reason": "",
                    "mindset": "",
                    "market_context": "",
                    "result_reasons": {"verdict": "", "reasons": []},
                    "dedupe_key": dedupe_key,
                    "legacy_dedupe_key": legacy_dedupe_key,
                    "raw_row": row,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            )

        deduped_prepared_records: List[Dict[str, Any]] = []
        seen_keys = set()
        duplicate_in_file = 0
        for item in prepared_records:
            if item["dedupe_key"] in seen_keys:
                duplicate_in_file += 1
                continue
            seen_keys.add(item["dedupe_key"])
            deduped_prepared_records.append(item)

        existing_count = await mongo_manager.count(self.RECORD_COLLECTION, {"group_id": group_id})
        if existing_count > self.MAX_IMPORT_DEDUPE_RECORDS:
            raise ValueError("交割单历史记录过多，请先拆分交割单分组后再继续导入")

        existing_docs = await mongo_manager.find_many(
            self.RECORD_COLLECTION,
            {"group_id": group_id},
            projection={
                "dedupe_key": 1,
                "legacy_dedupe_key": 1,
                "raw_row": 1,
                "code": 1,
                "trade_date": 1,
            },
            limit=self.MAX_IMPORT_DEDUPE_RECORDS,
        )
        existing_exact_keys = set()
        existing_legacy_counts = defaultdict(int)
        for doc in existing_docs:
            raw_row = doc.get("raw_row") or {}
            existing_code = self._normalize_code(doc.get("code"))
            existing_trade_date = str(doc.get("trade_date") or "")
            existing_exact_key = self._dedupe_key(raw_row, existing_code, existing_trade_date)
            existing_legacy_key = str(doc.get("legacy_dedupe_key") or "").strip() or self._legacy_dedupe_key(
                raw_row,
                existing_code,
                existing_trade_date,
            )
            if existing_exact_key:
                existing_exact_keys.add(existing_exact_key)
            if existing_legacy_key:
                existing_legacy_counts[existing_legacy_key] += 1

        matched_existing_by_legacy = defaultdict(int)
        new_records: List[Dict[str, Any]] = []
        duplicate_existing = 0
        for item in deduped_prepared_records:
            exact_key = item["dedupe_key"]
            legacy_key = item["legacy_dedupe_key"]

            if exact_key in existing_exact_keys:
                matched_existing_by_legacy[legacy_key] += 1
                duplicate_existing += 1
                continue

            legacy_quota = existing_legacy_counts.get(legacy_key, 0)
            if matched_existing_by_legacy[legacy_key] < legacy_quota:
                matched_existing_by_legacy[legacy_key] += 1
                duplicate_existing += 1
                continue

            new_records.append(item)

        batch_id = uuid.uuid4().hex
        if new_records:
            for item in new_records:
                item["batch_id"] = batch_id
            await mongo_manager.insert_many(self.RECORD_COLLECTION, new_records)

        batch_record = {
            "batch_id": batch_id,
            "group_id": group_id,
            "user_id": user_id,
            "filename": filename,
            "imported_at": datetime.now(UTC),
            "total_rows": len(prepared_records),
            "imported_rows": len(new_records),
            "duplicate_rows": duplicate_in_file + duplicate_existing,
            "trade_rows": sum(1 for item in new_records if item["is_trade_record"]),
        }
        await mongo_manager.update_one(
            self.BATCH_COLLECTION,
            {"batch_id": batch_id},
            {"$set": batch_record},
            upsert=True,
        )

        total_record_count = await mongo_manager.count(self.RECORD_COLLECTION, {"group_id": group_id})
        total_trade_count = await mongo_manager.count(self.RECORD_COLLECTION, {"group_id": group_id, "is_trade_record": True})
        await mongo_manager.update_one(
            self.GROUP_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
            {
                "$set": {
                    "record_count": total_record_count,
                    "trade_record_count": total_trade_count,
                    "last_imported_at": batch_record["imported_at"],
                }
            },
        )

        await self.rebuild_positions(user_id=user_id, group_id=group_id)

        return {
            "batch_id": batch_id,
            "group": await self.get_group(user_id, group_id),
            "total_rows": len(prepared_records),
            "imported_rows": len(new_records),
            "duplicate_rows": duplicate_in_file + duplicate_existing,
            "trade_rows": sum(1 for item in new_records if item["is_trade_record"]),
        }

    async def list_records(
        self,
        *,
        user_id: str,
        group_id: str,
        category: str = "trade",
        skip: int = 0,
        limit: int = 200,
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        filter_query: Dict[str, Any] = {"group_id": group_id, "user_id": user_id}
        if category != "all":
            filter_query["category"] = category
        if keyword:
            filter_query["$or"] = [
                {"security_name": {"$regex": keyword, "$options": "i"}},
                {"code": {"$regex": keyword, "$options": "i"}},
                {"ts_code": {"$regex": keyword.upper(), "$options": "i"}},
                {"business_type": {"$regex": keyword, "$options": "i"}},
            ]

        total = await mongo_manager.count(self.RECORD_COLLECTION, filter_query)
        records = await mongo_manager.find_many(
            self.RECORD_COLLECTION,
            filter_query,
            projection={
                "record_id": 1,
                "group_id": 1,
                "batch_id": 1,
                "trade_date": 1,
                "business_type": 1,
                "shareholder_account": 1,
                "code": 1,
                "ts_code": 1,
                "security_name": 1,
                "quantity": 1,
                "price": 1,
                "commission": 1,
                "stamp_tax": 1,
                "other_fee": 1,
                "transfer_fee": 1,
                "clearing_fee": 1,
                "amount": 1,
                "balance": 1,
                "currency": 1,
                "remark": 1,
                "source_label": 1,
                "category": 1,
                "side": 1,
                "security_type": 1,
                "is_trade_record": 1,
                "reviewed": 1,
                "operation_reason": 1,
                "mindset": 1,
                "market_context": 1,
                "result_reasons": 1,
                "updated_at": 1,
                "created_at": 1,
                "_id": 0,
            },
            sort=[("trade_date", -1), ("row_no", -1)],
            skip=skip,
            limit=limit,
        )
        return {
            "items": [self._serialize_record(item) for item in records],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    def _serialize_record(self, item: Dict[str, Any]) -> Dict[str, Any]:
        is_trade_record = bool(item.get("is_trade_record"))
        quantity = int(item.get("quantity", 0) or 0)
        return {
            "record_id": item.get("record_id"),
            "group_id": item.get("group_id"),
            "batch_id": item.get("batch_id"),
            "trade_date": item.get("trade_date"),
            "business_type": item.get("business_type"),
            "shareholder_account": item.get("shareholder_account"),
            "code": item.get("code"),
            "ts_code": item.get("ts_code"),
            "security_name": item.get("security_name"),
            "quantity": abs(quantity) if is_trade_record else quantity,
            "price": item.get("price", 0),
            "commission": item.get("commission", 0),
            "stamp_tax": item.get("stamp_tax", 0),
            "other_fee": item.get("other_fee", 0),
            "transfer_fee": item.get("transfer_fee", 0),
            "clearing_fee": item.get("clearing_fee", 0),
            "amount": item.get("amount", 0),
            "balance": item.get("balance", 0),
            "currency": item.get("currency"),
            "remark": item.get("remark"),
            "source_label": item.get("source_label"),
            "category": item.get("category"),
            "side": item.get("side"),
            "security_type": item.get("security_type", "other"),
            "is_trade_record": is_trade_record,
            "reviewed": bool(item.get("reviewed")),
            "operation_reason": item.get("operation_reason", ""),
            "mindset": item.get("mindset", ""),
            "market_context": item.get("market_context", ""),
            "result_reasons": self._normalize_result_reasons(item.get("result_reasons")),
            "updated_at": item.get("updated_at"),
            "created_at": item.get("created_at"),
        }

    async def update_review(
        self,
        *,
        user_id: str,
        record_id: str,
        operation_reason: str,
        mindset: str,
        market_context: str,
        result_reasons: Dict[str, Any],
    ) -> Dict[str, Any]:
        record = await mongo_manager.find_one(
            self.RECORD_COLLECTION,
            {"record_id": record_id, "user_id": user_id},
        )
        if not record:
            raise ValueError("交割单记录不存在")

        verdict = str(result_reasons.get("verdict") or "").strip()
        reasons = [str(item).strip() for item in (result_reasons.get("reasons") or []) if str(item).strip()]
        normalized_result_reasons = {
            "verdict": verdict if verdict in {"success", "failure"} else "",
            "reasons": reasons,
        }
        payload = {
            "operation_reason": operation_reason.strip(),
            "mindset": mindset.strip(),
            "market_context": market_context.strip(),
            "result_reasons": normalized_result_reasons,
            "reviewed": bool(
                operation_reason.strip()
                or mindset.strip()
                or market_context.strip()
                or normalized_result_reasons["verdict"]
                or normalized_result_reasons["reasons"]
            ),
        }
        await mongo_manager.update_one(
            self.RECORD_COLLECTION,
            {"record_id": record_id, "user_id": user_id},
            {"$set": payload},
        )
        updated = await mongo_manager.find_one(self.RECORD_COLLECTION, {"record_id": record_id, "user_id": user_id})
        return self._serialize_record(updated or {**record, **payload})

    async def get_stats(self, *, user_id: str, group_id: str) -> Dict[str, Any]:
        record_count = await mongo_manager.count(
            self.RECORD_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
        )
        if record_count > self.MAX_TRADE_RECORDS_FOR_ANALYSIS:
            raise ValueError("交割单记录过多，请先拆分交割单后再进行统计分析")

        records = await mongo_manager.find_many(
            self.RECORD_COLLECTION,
            {"group_id": group_id, "user_id": user_id},
            projection={
                "trade_date": 1,
                "category": 1,
                "business_type": 1,
                "security_name": 1,
                "code": 1,
                "ts_code": 1,
                "is_trade_record": 1,
                "reviewed": 1,
                "side": 1,
                "quantity": 1,
                "amount": 1,
                "commission": 1,
                "stamp_tax": 1,
                "other_fee": 1,
                "transfer_fee": 1,
                "clearing_fee": 1,
                "result_reasons": 1,
                "_id": 0,
            },
            sort=[("trade_date", 1)],
            limit=self.MAX_TRADE_RECORDS_FOR_ANALYSIS,
        )
        total_records = len(records)
        trade_records = [item for item in records if item.get("is_trade_record")]
        reviewed_count = sum(1 for item in trade_records if item.get("reviewed"))
        buy_records = [item for item in trade_records if item.get("side") == "buy"]
        sell_records = [item for item in trade_records if item.get("side") == "sell"]

        category_counts = Counter(item.get("category", "other") for item in records)
        business_type_counts = Counter(item.get("business_type", "未知") for item in records)
        stock_trade_counts = Counter(
            f"{item.get('security_name') or item.get('code') or '未知'} ({item.get('ts_code') or item.get('code') or '-'})"
            for item in trade_records
        )
        monthly_trade_counts = Counter((item.get("trade_date") or "")[:6] for item in trade_records if item.get("trade_date"))
        stock_pnl_buckets: Dict[str, Dict[str, Any]] = {}

        reason_counts: Dict[str, Counter[str]] = {"success": Counter(), "failure": Counter()}
        for item in trade_records:
            reasons = self._normalize_result_reasons(item.get("result_reasons"))
            verdict = reasons.get("verdict")
            if verdict in reason_counts:
                reason_counts[verdict].update(reasons.get("reasons") or [])

            ts_code = str(item.get("ts_code") or "").upper().strip()
            if not ts_code:
                continue

            bucket = stock_pnl_buckets.setdefault(
                ts_code,
                {
                    "ts_code": ts_code,
                    "code": item.get("code") or ts_code.split(".")[0],
                    "name": item.get("security_name") or item.get("code") or ts_code,
                    "quantity": 0,
                    "total_cost": 0.0,
                    "buy_count": 0,
                    "sell_count": 0,
                    "trade_count": 0,
                    "total_buy_amount": 0.0,
                    "total_sell_amount": 0.0,
                    "total_fee": 0.0,
                    "realized_pnl": 0.0,
                    "first_trade_date": item.get("trade_date"),
                    "last_trade_date": item.get("trade_date"),
                },
            )

            quantity = abs(int(item.get("quantity", 0) or 0))
            if quantity <= 0:
                continue

            amount = abs(float(item.get("amount", 0) or 0))
            fee = self._trade_fee(item)
            bucket["trade_count"] += 1
            bucket["total_fee"] += fee
            bucket["last_trade_date"] = item.get("trade_date")
            if not bucket.get("first_trade_date"):
                bucket["first_trade_date"] = item.get("trade_date")

            if item.get("side") == "buy":
                bucket["quantity"] += quantity
                bucket["total_cost"] += amount + fee
                bucket["buy_count"] += 1
                bucket["total_buy_amount"] += amount
            elif item.get("side") == "sell":
                bucket["sell_count"] += 1
                bucket["total_sell_amount"] += amount
                current_qty = int(bucket.get("quantity", 0) or 0)
                if current_qty <= 0:
                    bucket["quantity"] = 0
                    bucket["total_cost"] = 0.0
                    continue

                avg_cost = float(bucket.get("total_cost", 0) or 0) / current_qty if current_qty else 0.0
                reduce_qty = min(current_qty, quantity)
                realized_pnl = amount - fee - avg_cost * reduce_qty
                bucket["realized_pnl"] += realized_pnl
                bucket["quantity"] = current_qty - reduce_qty
                bucket["total_cost"] = max(0.0, float(bucket.get("total_cost", 0) or 0) - avg_cost * reduce_qty)

        latest_price_map = await self._load_latest_price_map(list(stock_pnl_buckets.keys()))
        stock_basic_meta = await self._load_stock_basic_meta(list(stock_pnl_buckets.keys()))
        stock_pnl_ranking: List[Dict[str, Any]] = []
        for item in stock_pnl_buckets.values():
            latest_info = latest_price_map.get(item["ts_code"], {})
            latest_price = latest_info.get("latest_price")
            latest_trade_date = latest_info.get("latest_trade_date")
            quantity = int(item.get("quantity", 0) or 0)
            current_total_cost = round(float(item.get("total_cost", 0) or 0), 2)
            market_value = round((latest_price or 0.0) * quantity, 2) if quantity > 0 and latest_price else 0.0
            unrealized_pnl = round(market_value - current_total_cost, 2) if quantity > 0 and latest_price else 0.0
            realized_pnl = round(float(item.get("realized_pnl", 0) or 0), 2)
            net_pnl = round(realized_pnl + unrealized_pnl, 2)
            base_amount = float(item.get("total_buy_amount", 0) or 0)
            stock_pnl_ranking.append(
                {
                    "ts_code": item["ts_code"],
                    "code": item.get("code") or item["ts_code"].split(".")[0],
                    "name": stock_basic_meta.get(item["ts_code"], {}).get("name") or item.get("name"),
                    "trade_count": int(item.get("trade_count", 0) or 0),
                    "buy_count": int(item.get("buy_count", 0) or 0),
                    "sell_count": int(item.get("sell_count", 0) or 0),
                    "position_quantity": quantity,
                    "total_buy_amount": round(float(item.get("total_buy_amount", 0) or 0), 2),
                    "total_sell_amount": round(float(item.get("total_sell_amount", 0) or 0), 2),
                    "total_fee": round(float(item.get("total_fee", 0) or 0), 2),
                    "realized_pnl": realized_pnl,
                    "unrealized_pnl": unrealized_pnl,
                    "net_pnl": net_pnl,
                    "net_pnl_pct": round((net_pnl / base_amount * 100), 2) if base_amount > 0 else 0.0,
                    "market_value": market_value,
                    "latest_price": latest_price,
                    "latest_trade_date": latest_trade_date,
                    "first_trade_date": item.get("first_trade_date"),
                    "last_trade_date": item.get("last_trade_date"),
                }
            )
        stock_pnl_ranking.sort(key=lambda item: (item.get("net_pnl", 0), item.get("realized_pnl", 0)), reverse=True)

        return {
            "summary": {
                "total_records": total_records,
                "trade_records": len(trade_records),
                "buy_count": len(buy_records),
                "sell_count": len(sell_records),
                "reviewed_count": reviewed_count,
                "review_coverage_pct": round((reviewed_count / len(trade_records) * 100), 1) if trade_records else 0.0,
                "total_buy_amount": round(sum(abs(item.get("amount", 0)) for item in buy_records), 2),
                "total_sell_amount": round(sum(abs(item.get("amount", 0)) for item in sell_records), 2),
                "total_fee": round(sum(
                    item.get("commission", 0)
                    + item.get("stamp_tax", 0)
                    + item.get("other_fee", 0)
                    + item.get("transfer_fee", 0)
                    + item.get("clearing_fee", 0)
                    for item in trade_records
                ), 2),
                "net_cash_flow": round(sum(item.get("amount", 0) for item in trade_records), 2),
            },
            "category_counts": [{"name": key, "count": value} for key, value in category_counts.most_common()],
            "business_type_counts": [{"name": key, "count": value} for key, value in business_type_counts.most_common()],
            "top_stocks": [{"name": key, "count": value} for key, value in stock_trade_counts.most_common(12)],
            "monthly_trade_counts": [{"month": key, "count": value} for key, value in sorted(monthly_trade_counts.items())],
            "stock_pnl_ranking": stock_pnl_ranking,
            "reason_counts": {
                reason_type: [{"name": key, "count": value} for key, value in counter.most_common(20)]
                for reason_type, counter in reason_counts.items()
            },
        }

    async def get_kline_context(
        self,
        *,
        user_id: str,
        record_id: str,
        window: int = 50,
        category: str = "trade",
        keyword: Optional[str] = None,
        anchor_record_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = await mongo_manager.find_one(
            self.RECORD_COLLECTION,
            {"record_id": record_id, "user_id": user_id},
        )
        if not record:
            raise ValueError("交割单记录不存在")

        navigation_filter: Dict[str, Any] = {
            "group_id": record.get("group_id"),
            "user_id": user_id,
            "is_trade_record": True,
        }
        if category != "all":
            navigation_filter["category"] = category
        if keyword:
            navigation_filter["$or"] = [
                {"security_name": {"$regex": keyword, "$options": "i"}},
                {"code": {"$regex": keyword, "$options": "i"}},
                {"ts_code": {"$regex": keyword.upper(), "$options": "i"}},
                {"business_type": {"$regex": keyword, "$options": "i"}},
            ]

        navigation_records = await mongo_manager.find_many(
            self.RECORD_COLLECTION,
            navigation_filter,
            sort=[("trade_date", 1), ("row_no", 1)],
            projection={"record_id": 1},
            limit=self.MAX_REVIEW_NAV_RECORDS,
        )
        navigation_ids = [str(item.get("record_id")) for item in navigation_records if item.get("record_id")]
        fallback_anchor = anchor_record_id or record_id
        if fallback_anchor not in navigation_ids:
            fallback_anchor = record_id
        if fallback_anchor not in navigation_ids and navigation_ids:
            fallback_anchor = navigation_ids[0]
        current_index = navigation_ids.index(fallback_anchor) if fallback_anchor in navigation_ids else -1

        ts_code = record.get("ts_code")
        same_stock_records = await mongo_manager.find_many(
            self.RECORD_COLLECTION,
            {
                "group_id": record.get("group_id"),
                "user_id": user_id,
                "ts_code": ts_code,
                "is_trade_record": True,
            } if ts_code else {
                "record_id": record_id,
                "user_id": user_id,
            },
            sort=[("trade_date", 1), ("row_no", 1)],
            projection={
                "record_id": 1,
                "trade_date": 1,
                "business_type": 1,
                "shareholder_account": 1,
                "code": 1,
                "ts_code": 1,
                "security_name": 1,
                "quantity": 1,
                "price": 1,
                "commission": 1,
                "stamp_tax": 1,
                "other_fee": 1,
                "transfer_fee": 1,
                "clearing_fee": 1,
                "amount": 1,
                "balance": 1,
                "currency": 1,
                "remark": 1,
                "source_label": 1,
                "category": 1,
                "side": 1,
                "security_type": 1,
                "is_trade_record": 1,
                "reviewed": 1,
                "operation_reason": 1,
                "mindset": 1,
                "market_context": 1,
                "result_reasons": 1,
                "updated_at": 1,
                "created_at": 1,
                "_id": 0,
            },
            limit=self.MAX_RELATED_STOCK_RECORDS,
        )

        markers = [
            {
                "record_id": item.get("record_id"),
                "trade_date": item.get("trade_date"),
                "price": item.get("price"),
                "side": item.get("side"),
                "label": f"{'买' if item.get('side') == 'buy' else '卖'} {item.get('price', 0)}",
                "is_current": item.get("record_id") == record_id,
            }
            for item in same_stock_records
            if item.get("trade_date") and item.get("price")
        ]

        stock_basic = await mongo_manager.find_one(
            "stock_basic",
            {"ts_code": ts_code},
            projection={"name": 1, "ts_code": 1, "industry": 1, "market": 1, "list_date": 1},
        ) if ts_code else None

        load_error: Optional[str] = None
        daily: List[Dict[str, Any]] = []
        weekly: List[Dict[str, Any]] = []
        monthly: List[Dict[str, Any]] = []
        recent_30d_pct_chg: Optional[float] = None
        sector_context: Dict[str, Any] = {"concepts": [], "sectors": []}
        latest_daily: Dict[str, Any] = {}
        zoom_start = 0.0
        zoom_end = 100.0

        if not ts_code:
            load_error = "该记录不是股票或没有可用股票代码，暂时无法展示 K 线"
        else:
            try:
                daily = await mongo_manager.find_many(
                    "stock_daily",
                    {"ts_code": ts_code},
                    projection={"_id": 0},
                    sort=[("trade_date", 1)],
                    limit=self.MAX_DAILY_ROWS_PER_STOCK,
                )
                if not daily:
                    load_error = "本地没有该股票的日线数据"
                else:
                    trade_dates = [item.get("trade_date") for item in daily]
                    target_trade_date = record.get("trade_date")
                    try:
                        target_index = trade_dates.index(target_trade_date)
                    except ValueError:
                        target_index = max(0, len(trade_dates) - 1)

                    start_index = max(0, target_index - window)
                    end_index = min(len(trade_dates) - 1, target_index + window)
                    zoom_start = round(start_index / max(1, len(trade_dates)) * 100, 2)
                    zoom_end = round((end_index + 1) / max(1, len(trade_dates)) * 100, 2)
                    weekly = build_period_candles(daily, "weekly")
                    monthly = build_period_candles(daily, "monthly")
                    recent_30d_pct_chg = calculate_recent_return(daily, days=30)
                    latest_daily = daily[-1]
                    try:
                        sector_context = await get_stock_sector_context(ts_code)
                    except Exception:
                        sector_context = {"concepts": [], "sectors": []}
            except Exception as exc:
                load_error = f"加载股票图表数据失败：{exc}"
                daily = []
                weekly = []
                monthly = []
                latest_daily = {}

        return {
            "record": self._serialize_record(record),
            "stock": {
                "ts_code": ts_code or "",
                "name": stock_basic.get("name") if stock_basic else record.get("security_name"),
                "industry": stock_basic.get("industry") if stock_basic else None,
                "market": stock_basic.get("market") if stock_basic else None,
                "list_date": stock_basic.get("list_date") if stock_basic else None,
                "latest_trade_date": latest_daily.get("trade_date"),
                "latest_price": latest_daily.get("close"),
                "latest_pct_chg": latest_daily.get("pct_chg"),
                "recent_30d_pct_chg": recent_30d_pct_chg,
                "concepts": sector_context.get("concepts", []),
                "sectors": sector_context.get("sectors", []),
            },
            "daily": [serialize_daily_record(item) for item in daily],
            "weekly": weekly,
            "monthly": monthly,
            "markers": markers,
            "related_records": [self._serialize_record(item) for item in same_stock_records],
            "navigation": {
                "anchor_record_id": fallback_anchor,
                "previous_record_id": navigation_ids[current_index - 1] if current_index > 0 else None,
                "next_record_id": navigation_ids[current_index + 1] if 0 <= current_index < len(navigation_ids) - 1 else None,
                "position": current_index + 1 if current_index >= 0 else 0,
                "total": len(navigation_ids),
            },
            "zoom": {
                "start": zoom_start,
                "end": zoom_end,
                "window": window,
            },
            "load_error": load_error,
        }


trade_review_service = TradeReviewService()
