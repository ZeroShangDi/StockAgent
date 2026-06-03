"""
股票关联关系管理器

统一维护股票与行业、板块、题材等关联边，为后续题材分析、主线跟踪、
复盘补充信息等场景提供稳定的数据底座。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from core.base import BaseManager
from .mongo_manager import mongo_manager


class StockRelationManager(BaseManager):
    """股票关联关系管理器。"""

    COLLECTION = "stock_relations"
    STATIC_SOURCES = ("stock_basic", "ths_sector")

    async def initialize(self) -> None:
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized

    async def sync_relations(self, snapshot_trade_date: Optional[str] = None) -> Dict[str, Any]:
        """
        同步股票关联关系。

        当前写入三类关系：
        - stock_basic 提供的稳定行业关系
        - ths_sector / stock_sector_map 提供的板块、概念映射
        - limit_list 提供的按交易日快照的涨停来源行业关系
        """
        self._ensure_initialized()

        now = datetime.now(UTC)
        static_docs, stock_index = await self._build_static_relation_docs(now)

        deleted_static = await mongo_manager.delete_many(
            self.COLLECTION,
            {"source": {"$in": list(self.STATIC_SOURCES)}},
        )

        static_result = {"upserted": 0, "modified": 0}
        if static_docs:
            static_result = await mongo_manager.bulk_upsert(
                collection=self.COLLECTION,
                documents=static_docs,
                key_fields=["ts_code", "source", "relation_type", "relation_key", "source_trade_date"],
            )

        limit_trade_date = snapshot_trade_date or await self._get_latest_limit_trade_date()
        dynamic_docs: List[Dict[str, Any]] = []
        deleted_dynamic = 0
        dynamic_result = {"upserted": 0, "modified": 0}

        if limit_trade_date:
            dynamic_docs = await self._build_limit_relation_docs(
                trade_date=limit_trade_date,
                stock_index=stock_index,
                now=now,
            )
            deleted_dynamic = await mongo_manager.delete_many(
                self.COLLECTION,
                {"source": "limit_list", "source_trade_date": limit_trade_date},
            )
            if dynamic_docs:
                dynamic_result = await mongo_manager.bulk_upsert(
                    collection=self.COLLECTION,
                    documents=dynamic_docs,
                    key_fields=["ts_code", "source", "relation_type", "relation_key", "source_trade_date"],
                )

        sync_date = limit_trade_date or now.strftime("%Y%m%d")
        await mongo_manager.record_sync(
            sync_type="stock_relations",
            sync_date=sync_date,
            count=len(static_docs) + len(dynamic_docs),
        )

        return {
            "trade_date": limit_trade_date,
            "static_docs": len(static_docs),
            "dynamic_docs": len(dynamic_docs),
            "deleted_static": deleted_static,
            "deleted_dynamic": deleted_dynamic,
            "written_static": static_result["upserted"] + static_result["modified"],
            "written_dynamic": dynamic_result["upserted"] + dynamic_result["modified"],
        }

    async def get_stock_relations(
        self,
        ts_code: str,
        relation_types: Optional[List[str]] = None,
        trade_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """读取单只股票的关联关系。"""
        self._ensure_initialized()

        normalized_ts_code = str(ts_code or "").strip().upper()
        if not normalized_ts_code:
            return []

        query: Dict[str, Any] = {"ts_code": normalized_ts_code}
        if relation_types:
            query["relation_type"] = {"$in": relation_types}
        if trade_date:
            query["$or"] = [
                {"source_trade_date": None},
                {"source_trade_date": trade_date},
            ]

        return await mongo_manager.find_many(
            self.COLLECTION,
            query,
            projection={"_id": 0},
            sort=[("relation_type", 1), ("source_trade_date", -1), ("relation_name", 1)],
        )

    async def _build_static_relation_docs(
        self,
        now: datetime,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        stocks = await mongo_manager.find_many(
            "stock_basic",
            {},
            projection={
                "ts_code": 1,
                "symbol": 1,
                "name": 1,
                "industry": 1,
                "market": 1,
                "exchange": 1,
                "_id": 0,
            },
        )

        stock_index: Dict[str, Dict[str, Any]] = {}
        relation_docs: List[Dict[str, Any]] = []

        for stock in stocks:
            ts_code = str(stock.get("ts_code") or "").strip().upper()
            symbol = str(stock.get("symbol") or "").strip()
            if not ts_code or not symbol:
                continue
            stock_index[symbol] = stock

            industry = str(stock.get("industry") or "").strip()
            if industry:
                relation_docs.append(
                    self._build_relation_doc(
                        stock=stock,
                        relation_type="industry",
                        relation_name=industry,
                        relation_key=industry,
                        source="stock_basic",
                        source_trade_date=None,
                        is_dynamic=False,
                        metadata={
                            "market": stock.get("market"),
                            "exchange": stock.get("exchange"),
                        },
                        now=now,
                    )
                )

        stock_sector_maps = await mongo_manager.find_many(
            "stock_sector_map",
            {},
            projection={"code": 1, "sectors": 1, "_id": 0},
        )

        sector_codes = sorted({
            str(item.get("ts_code") or "").strip()
            for mapping in stock_sector_maps
            for item in (mapping.get("sectors") or [])
            if str(item.get("ts_code") or "").strip()
        })

        sector_meta_map: Dict[str, Dict[str, Any]] = {}
        if sector_codes:
            meta_records = await mongo_manager.find_many(
                "ths_sectors",
                {"ts_code": {"$in": sector_codes}},
                projection={"ts_code": 1, "name": 1, "sector_type": 1, "type_name": 1, "_id": 0},
            )
            sector_meta_map = {
                str(item.get("ts_code") or "").strip(): item
                for item in meta_records
                if str(item.get("ts_code") or "").strip()
            }

        for mapping in stock_sector_maps:
            stock_code = str(mapping.get("code") or "").strip()
            if not stock_code:
                continue
            stock = stock_index.get(stock_code)
            if not stock:
                continue

            for sector in mapping.get("sectors") or []:
                sector_code = str(sector.get("ts_code") or "").strip()
                if not sector_code:
                    continue

                meta = sector_meta_map.get(sector_code, {})
                sector_name = str(sector.get("name") or meta.get("name") or sector_code).strip()
                sector_type = str(meta.get("sector_type") or "").strip()
                relation_type = "concept" if sector_type == "N" else "sector"

                relation_docs.append(
                    self._build_relation_doc(
                        stock=stock,
                        relation_type=relation_type,
                        relation_name=sector_name,
                        relation_key=sector_code,
                        source="ths_sector",
                        source_trade_date=None,
                        is_dynamic=False,
                        metadata={
                            "relation_code": sector_code,
                            "sector_type": sector_type,
                            "type_name": meta.get("type_name"),
                        },
                        now=now,
                    )
                )

        return relation_docs, stock_index

    async def _build_limit_relation_docs(
        self,
        trade_date: str,
        stock_index: Dict[str, Dict[str, Any]],
        now: datetime,
    ) -> List[Dict[str, Any]]:
        limit_records = await mongo_manager.find_many(
            "limit_list",
            {"trade_date": trade_date},
            projection={
                "ts_code": 1,
                "name": 1,
                "industry": 1,
                "limit": 1,
                "limit_times": 1,
                "first_time": 1,
                "last_time": 1,
                "fd_amount": 1,
                "_id": 0,
            },
        )

        relation_docs: List[Dict[str, Any]] = []
        for item in limit_records:
            ts_code = str(item.get("ts_code") or "").strip().upper()
            industry = str(item.get("industry") or "").strip()
            if not ts_code or not industry:
                continue

            symbol = ts_code.split(".")[0]
            stock = stock_index.get(symbol) or {
                "ts_code": ts_code,
                "symbol": symbol,
                "name": item.get("name"),
            }

            relation_docs.append(
                self._build_relation_doc(
                    stock=stock,
                    relation_type="limit_industry",
                    relation_name=industry,
                    relation_key=industry,
                    source="limit_list",
                    source_trade_date=trade_date,
                    is_dynamic=True,
                    metadata={
                        "limit": item.get("limit"),
                        "limit_times": item.get("limit_times"),
                        "first_time": item.get("first_time"),
                        "last_time": item.get("last_time"),
                        "fd_amount": item.get("fd_amount"),
                    },
                    now=now,
                )
            )

        return relation_docs

    async def _get_latest_limit_trade_date(self) -> Optional[str]:
        latest = await mongo_manager.find_one(
            "limit_list",
            {},
            projection={"trade_date": 1, "_id": 0},
            sort=[("trade_date", -1)],
        )
        return str(latest.get("trade_date") or "").strip() or None if latest else None

    def _build_relation_doc(
        self,
        stock: Dict[str, Any],
        relation_type: str,
        relation_name: str,
        relation_key: str,
        source: str,
        source_trade_date: Optional[str],
        is_dynamic: bool,
        metadata: Optional[Dict[str, Any]],
        now: datetime,
    ) -> Dict[str, Any]:
        return {
            "ts_code": str(stock.get("ts_code") or "").strip().upper(),
            "symbol": str(stock.get("symbol") or "").strip(),
            "stock_name": str(stock.get("name") or "").strip(),
            "relation_type": relation_type,
            "relation_name": relation_name,
            "relation_key": relation_key,
            "source": source,
            "source_trade_date": source_trade_date,
            "is_dynamic": is_dynamic,
            "metadata": metadata or {},
            "updated_at": now,
        }


stock_relation_manager = StockRelationManager()
