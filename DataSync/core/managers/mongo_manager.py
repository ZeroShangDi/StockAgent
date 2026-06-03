"""
MongoDB 管理器

负责:
- 业务数据 CRUD
- 索引管理 (ensure_indexes)
- 高性能批量写入 (BulkWrite)
- 聚合查询
"""

from typing import Optional, Any, List, Dict, Tuple
from datetime import UTC, datetime
import asyncio
import copy
import os
import time
import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel, UpdateOne, InsertOne
from pymongo.errors import OperationFailure

from core.base import BaseManager
from ..settings import settings, normalize_local_service_host


class BulkUpsertBatchError(RuntimeError):
    """批量 upsert 失败时携带已完成批次和失败批次信息。"""

    def __init__(self, collection: str, result: Dict[str, Any]):
        super().__init__(f"bulk_upsert_batched failed for {collection}: {result.get('batch_errors')}")
        self.collection = collection
        self.result = result


class MongoManager(BaseManager):
    """
    MongoDB 资源管理器

    特性:
    - 连接池管理 (默认 max_pool_size=100)
    - 索引自动创建
    - 高性能批量写入
    """
    CORE_INDEX_COLLECTIONS = {
        "stock_basic",
        "stock_daily",
        "index_basic",
        "index_daily",
        "daily_basic",
        "moneyflow_industry",
        "moneyflow_concept",
        "limit_list",
        "stock_relations",
        "sector_ranking",
        "daily_stats",
        "market_analysis",
        "market_weather_daily",
        "sync_records",
        "job_execution_records",
        "readiness_markers",
        "ops_events",
        "datasync_dead_letters",
        "datasync_checkpoints",
        "datasync_backfill_jobs",
        "datasync_backfill_budgets",
    }

    def __init__(self):
        super().__init__()
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._config = settings.mongo
        self._mirror_client: Optional[AsyncIOMotorClient] = None
        self._mirror_db: Optional[AsyncIOMotorDatabase] = None
        self._mirror_config = settings.mongo_mirror
        self._mirror_write_success_count = 0
        self._mirror_write_failure_count = 0
        self._last_mirror_write_success_at: Optional[datetime] = None
        self._last_mirror_write_error: Optional[str] = None
        self._last_mirror_write_error_at: Optional[datetime] = None
        self._mirror_degraded_since: Optional[datetime] = None
        self._last_mirror_recovered_at: Optional[datetime] = None
        self._index_create_timeout_seconds = max(1, self._config.index_create_timeout_seconds)
        self._active_index_scope = "all"
        self._active_index_collections: Optional[set[str]] = None

    def _get_timeout_ms(self, env_key: str, default_ms: int) -> int:
        value = os.getenv(env_key)
        if value is None or value == "":
            return default_ms
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default_ms
        except ValueError:
            return default_ms

    def _build_client_kwargs(self, prefix: str = "MONGO") -> tuple[int, int, int, dict]:
        connect_timeout_ms = self._get_timeout_ms(f"{prefix}_CONNECT_TIMEOUT_MS", 5000)
        server_selection_timeout_ms = self._get_timeout_ms(f"{prefix}_SERVER_SELECTION_TIMEOUT_MS", 5000)
        socket_timeout_ms = self._get_timeout_ms(f"{prefix}_SOCKET_TIMEOUT_MS", 5000)
        kwargs = {
            "connectTimeoutMS": connect_timeout_ms,
            "serverSelectionTimeoutMS": server_selection_timeout_ms,
            "socketTimeoutMS": socket_timeout_ms,
        }
        return connect_timeout_ms, server_selection_timeout_ms, socket_timeout_ms, kwargs

    async def initialize(self) -> None:
        """初始化 MongoDB 连接"""
        if self._initialized:
            return

        self._config.host = normalize_local_service_host(self._config.host, "mongo")
        self._mirror_config.host = normalize_local_service_host(self._mirror_config.host, "mongo")

        self.logger.info(
            f"Connecting to MongoDB: {self._config.host}:{self._config.port} "
            f"(pool_size={self._config.max_pool_size})"
        )

        # NOTE: 在受限 sandbox 环境里，localhost 可能被禁用；需要更短的超时避免长时间挂起。
        # 可通过环境变量覆盖：
        # - MONGO_CONNECT_TIMEOUT_MS
        # - MONGO_SERVER_SELECTION_TIMEOUT_MS
        # - MONGO_SOCKET_TIMEOUT_MS
        connect_timeout_ms, server_selection_timeout_ms, socket_timeout_ms, client_kwargs = self._build_client_kwargs("MONGO")

        self._client = AsyncIOMotorClient(
            self._config.url,
            maxPoolSize=self._config.max_pool_size,
            **client_kwargs,
        )
        self._db = self._client[self._config.database]

        # 测试连接
        ping_timeout = max(connect_timeout_ms, server_selection_timeout_ms, socket_timeout_ms) / 1000.0 + 0.5
        await asyncio.wait_for(self._client.admin.command("ping"), timeout=ping_timeout)

        if self._config.ensure_indexes:
            await self._ensure_indexes(scope=self._config.index_startup_scope)
        else:
            self.logger.info("MongoDB index ensuring skipped by MONGO_ENSURE_INDEXES=false")

        if self._mirror_config.enabled:
            try:
                await self._initialize_mirror()
            except Exception as exc:
                self._mirror_client = None
                self._mirror_db = None
                self.logger.warning(f"Mongo mirror initialization failed, continuing with primary only: {exc}")

        self._initialized = True
        self.logger.info(f"MongoDB connected, database: {self._config.database} ✓")

    async def _initialize_mirror(self) -> None:
        """初始化可选镜像 Mongo 连接。"""
        connect_timeout_ms, server_selection_timeout_ms, socket_timeout_ms, client_kwargs = self._build_client_kwargs("MONGO_MIRROR")
        self.logger.info(
            f"Connecting to Mongo mirror: {self._mirror_config.host}:{self._mirror_config.port} "
            f"(pool_size={self._mirror_config.max_pool_size})"
        )
        self._mirror_client = AsyncIOMotorClient(
            self._mirror_config.url,
            maxPoolSize=self._mirror_config.max_pool_size,
            **client_kwargs,
        )
        self._mirror_db = self._mirror_client[self._mirror_config.database]
        ping_timeout = max(connect_timeout_ms, server_selection_timeout_ms, socket_timeout_ms) / 1000.0 + 0.5
        await asyncio.wait_for(self._mirror_client.admin.command("ping"), timeout=ping_timeout)
        self.logger.info(f"Mongo mirror connected, database: {self._mirror_config.database} ✓")

    async def shutdown(self) -> None:
        """关闭连接"""
        if self._mirror_client:
            self._mirror_client.close()
            self._mirror_client = None
            self._mirror_db = None

        if self._client:
            self._client.close()
            self._client = None
            self._db = None

        self._initialized = False
        self.logger.info("MongoDB disconnected")

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            if self._client:
                await self._client.admin.command("ping")
                if self._mirror_config.enabled and self._mirror_client:
                    await self._mirror_client.admin.command("ping")
                return True
        except Exception:
            pass
        return False

    @property
    def mirror_enabled(self) -> bool:
        return bool(self._mirror_config.enabled and self._mirror_db is not None)

    async def get_target_status(self) -> dict:
        """获取主库与镜像库的连接状态。"""
        primary_healthy = False
        mirror_healthy: Optional[bool] = None

        if self._client:
            try:
                await self._client.admin.command("ping")
                primary_healthy = True
            except Exception:
                primary_healthy = False

        if self._mirror_config.enabled:
            if self._mirror_client:
                try:
                    await self._mirror_client.admin.command("ping")
                    mirror_healthy = True
                except Exception:
                    mirror_healthy = False
            else:
                mirror_healthy = False

        return {
            "primary": {
                "enabled": True,
                "healthy": primary_healthy,
                "host": self._config.host,
                "port": self._config.port,
                "database": self._config.database,
            },
            "mirror": {
                "enabled": bool(self._mirror_config.enabled),
                "healthy": mirror_healthy,
                "connected": self._mirror_db is not None,
                "host": self._mirror_config.host,
                "port": self._mirror_config.port,
                "database": self._mirror_config.database,
                "write_success_count": self._mirror_write_success_count,
                "write_failure_count": self._mirror_write_failure_count,
                "last_write_success_at": self._last_mirror_write_success_at.isoformat() if self._last_mirror_write_success_at else None,
                "last_write_error": self._last_mirror_write_error,
                "last_write_error_at": self._last_mirror_write_error_at.isoformat() if self._last_mirror_write_error_at else None,
                "degraded_since": self._mirror_degraded_since.isoformat() if self._mirror_degraded_since else None,
                "last_recovered_at": self._last_mirror_recovered_at.isoformat() if self._last_mirror_recovered_at else None,
            },
        }

    def get_status(self) -> dict:
        status = super().get_status()
        status.update(
            {
                "primary_host": self._config.host,
                "primary_port": self._config.port,
                "primary_database": self._config.database,
                "mirror_enabled": bool(self._mirror_config.enabled),
                "mirror_connected": self._mirror_db is not None,
                "mirror_host": self._mirror_config.host if self._mirror_config.enabled else None,
                "mirror_port": self._mirror_config.port if self._mirror_config.enabled else None,
                "mirror_database": self._mirror_config.database if self._mirror_config.enabled else None,
                "mirror_write_success_count": self._mirror_write_success_count,
                "mirror_write_failure_count": self._mirror_write_failure_count,
                "last_mirror_write_success_at": self._last_mirror_write_success_at.isoformat() if self._last_mirror_write_success_at else None,
                "last_mirror_write_error": self._last_mirror_write_error,
                "last_mirror_write_error_at": self._last_mirror_write_error_at.isoformat() if self._last_mirror_write_error_at else None,
                "mirror_degraded_since": self._mirror_degraded_since.isoformat() if self._mirror_degraded_since else None,
                "last_mirror_recovered_at": self._last_mirror_recovered_at.isoformat() if self._last_mirror_recovered_at else None,
            }
        )
        return status

    async def _mirror_write(self, action: str, func) -> None:
        """最佳努力镜像写入，不阻断主链路。"""
        if not self.mirror_enabled:
            return
        try:
            now = datetime.now(UTC)
            await func()
            self._mirror_write_success_count += 1
            self._last_mirror_write_success_at = now
            if self._mirror_degraded_since is not None:
                self._last_mirror_recovered_at = now
                self.logger.info(
                    "Mongo mirror write path recovered after degradation: action=%s degraded_since=%s",
                    action,
                    self._mirror_degraded_since.isoformat(),
                )
            self._mirror_degraded_since = None
            self._last_mirror_write_error = None
            self._last_mirror_write_error_at = None
        except Exception as exc:
            now = datetime.now(UTC)
            self._mirror_write_failure_count += 1
            self._last_mirror_write_error = f"{action}: {exc}"
            self._last_mirror_write_error_at = now
            if self._mirror_degraded_since is None:
                self._mirror_degraded_since = now
            self.logger.warning(f"Mongo mirror {action} failed: {exc}")

    @property
    def db(self) -> AsyncIOMotorDatabase:
        """获取数据库实例"""
        self._ensure_initialized()
        return self._db

    @staticmethod
    def _normalize_index_scope(scope: Optional[str]) -> str:
        normalized = (scope or "core").strip().lower()
        if normalized in {"all", "full"}:
            return "all"
        if normalized in {"none", "skip", "off"}:
            return "none"
        return "core"

    def _should_ensure_index_collection(self, collection_name: str) -> bool:
        if self._active_index_scope == "none":
            return False
        if self._active_index_collections is not None:
            return collection_name in self._active_index_collections
        if self._active_index_scope == "core":
            return collection_name in self.CORE_INDEX_COLLECTIONS
        return True

    @staticmethod
    def _index_model_name(index_model: IndexModel) -> str:
        explicit_name = index_model.document.get("name")
        if explicit_name:
            return str(explicit_name)
        keys = index_model.document.get("key") or {}
        return "_".join(f"{key}_{value}" for key, value in keys.items())

    async def _filter_missing_indexes(self, collection_name: str, indexes: List[IndexModel]) -> List[IndexModel]:
        collection = self._db[collection_name]
        try:
            existing_names = {
                item.get("name")
                async for item in collection.list_indexes()
                if item.get("name")
            }
        except Exception as exc:
            self.logger.warning(
                "List indexes for %s failed, falling back to create_indexes: %s",
                collection_name,
                exc,
            )
            return indexes

        return [
            index_model
            for index_model in indexes
            if self._index_model_name(index_model) not in existing_names
        ]

    async def _safe_create_indexes(self, collection_name: str, indexes: List[IndexModel]) -> None:
        """安全创建索引，处理索引冲突

        当已存在同名但属性不同的索引时，先删除旧索引再创建新索引。
        """
        if not self._should_ensure_index_collection(collection_name):
            return

        collection = self._db[collection_name]
        indexes_to_create = await self._filter_missing_indexes(collection_name, indexes)
        if not indexes_to_create:
            return

        try:
            await asyncio.wait_for(
                collection.create_indexes(indexes_to_create),
                timeout=self._index_create_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Create indexes for %s timed out after %ss, skipping this collection",
                collection_name,
                self._index_create_timeout_seconds,
            )
        except OperationFailure as e:
            if e.code == 86:  # IndexKeySpecsConflict
                self.logger.warning(f"Index conflict in {collection_name}, recreating...")
                for idx in indexes_to_create:
                    idx_name = idx.document.get("name")
                    if not idx_name:
                        keys = idx.document.get("key")
                        if keys:
                            idx_name = "_".join(f"{k}_{v}" for k, v in keys.items())
                    if idx_name:
                        try:
                            await asyncio.wait_for(
                                collection.drop_index(idx_name),
                                timeout=self._index_create_timeout_seconds,
                            )
                            self.logger.info(f"Dropped conflicting index: {idx_name}")
                        except (OperationFailure, asyncio.TimeoutError):
                            pass
                try:
                    await asyncio.wait_for(
                        collection.create_indexes(indexes_to_create),
                        timeout=self._index_create_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "Recreate indexes for %s timed out after %ss, skipping this collection",
                        collection_name,
                        self._index_create_timeout_seconds,
                    )
            else:
                raise

    async def create_index(
        self,
        collection_name: str,
        keys: List[Tuple[str, int]],
        unique: bool = False,
        **kwargs
    ) -> str:
        """
        创建单个索引

        Args:
            collection_name: 集合名称
            keys: 索引键列表，如 [("ts_code", 1), ("trade_date", -1)]
            unique: 是否唯一索引
            **kwargs: 其他索引选项

        Returns:
            索引名称
        """
        self._ensure_initialized()
        collection = self._db[collection_name]

        index_model = IndexModel(keys, unique=unique, **kwargs)
        try:
            result = await asyncio.wait_for(
                collection.create_indexes([index_model]),
                timeout=self._index_create_timeout_seconds,
            )
            return result[0] if result else ""
        except asyncio.TimeoutError:
            self.logger.warning(
                "Create index for %s timed out after %ss",
                collection_name,
                self._index_create_timeout_seconds,
            )
            return ""
        except OperationFailure as e:
            if e.code == 86:  # IndexKeySpecsConflict
                idx_name = "_".join(f"{k}_{v}" for k, v in keys)
                try:
                    await asyncio.wait_for(
                        collection.drop_index(idx_name),
                        timeout=self._index_create_timeout_seconds,
                    )
                    self.logger.info(f"Dropped conflicting index: {idx_name}")
                except (OperationFailure, asyncio.TimeoutError):
                    pass
                try:
                    result = await asyncio.wait_for(
                        collection.create_indexes([index_model]),
                        timeout=self._index_create_timeout_seconds,
                    )
                    return result[0] if result else ""
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "Recreate index for %s timed out after %ss",
                        collection_name,
                        self._index_create_timeout_seconds,
                    )
                    return ""
            else:
                raise

    async def ensure_indexes(
        self,
        *,
        scope: str = "core",
        collections: Optional[List[str]] = None,
    ) -> dict:
        """手动创建索引，可用于 CLI 在闲时补齐非核心索引。"""
        self._ensure_initialized()
        return await self._ensure_indexes(scope=scope, collections=collections)

    async def _ensure_indexes(
        self,
        *,
        scope: str = "core",
        collections: Optional[List[str]] = None,
    ) -> dict:
        """
        确保索引存在

        在初始化时自动调用，为所有业务表创建必要的索引。
        """
        previous_scope = self._active_index_scope
        previous_collections = self._active_index_collections
        normalized_scope = self._normalize_index_scope(scope)
        normalized_collections = {
            item.strip()
            for item in (collections or [])
            if item and item.strip()
        } or None
        self._active_index_scope = normalized_scope
        self._active_index_collections = normalized_collections
        self.logger.info(
            "Ensuring MongoDB indexes (scope=%s, collections=%s)...",
            normalized_scope,
            sorted(normalized_collections) if normalized_collections else "auto",
        )
        if normalized_scope == "none" and not normalized_collections:
            self.logger.info("MongoDB index ensuring skipped by scope=none")
            self._active_index_scope = previous_scope
            self._active_index_collections = previous_collections
            return {"success": True, "scope": normalized_scope, "collections": []}

        # 用户表
        await self._safe_create_indexes("users", [
            IndexModel([("username", ASCENDING)], unique=True),
            IndexModel([("email", ASCENDING)], unique=True),
        ])

        # 任务表
        await self._safe_create_indexes("tasks", [
            IndexModel([("task_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("trace_id", ASCENDING)]),
            IndexModel([("node_id", ASCENDING)]),
        ])

        # 智能工作台
        await self._safe_create_indexes("assistant_conversations", [
            IndexModel([("conversation_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING), ("updated_at", DESCENDING)]),
            IndexModel([("last_message_at", DESCENDING)]),
        ])
        await self._safe_create_indexes("assistant_artifacts", [
            IndexModel([("artifact_id", ASCENDING)], unique=True),
            IndexModel([("conversation_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
        ])

        # 股票基础信息表
        await self._safe_create_indexes("stock_basic", [
            IndexModel([("ts_code", ASCENDING)], unique=True),
            IndexModel([("name", ASCENDING)]),
            IndexModel([("industry", ASCENDING)]),
            IndexModel([("list_status", ASCENDING)]),
            IndexModel([("total_mv", -1)]),
            IndexModel([("pe", 1)]),
            IndexModel([("pb", 1)]),
        ])

        # 日线数据表 (高频查询)
        await self._safe_create_indexes("stock_daily", [
            IndexModel(
                [("ts_code", ASCENDING), ("trade_date", DESCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
        ])

        # 指数基础信息表
        await self._safe_create_indexes("index_basic", [
            IndexModel([("ts_code", ASCENDING)], unique=True),
            IndexModel([("name", ASCENDING)]),
            IndexModel([("market", ASCENDING)]),
            IndexModel([("index_type", ASCENDING)]),
        ])

        # 指数日线数据表 (高频查询)
        await self._safe_create_indexes("index_daily", [
            IndexModel(
                [("ts_code", ASCENDING), ("trade_date", DESCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
        ])

        # 行业资金流向表
        await self._safe_create_indexes("moneyflow_industry", [
            IndexModel(
                [("ts_code", ASCENDING), ("trade_date", DESCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
            IndexModel([("name", ASCENDING)]),
            IndexModel([("net_amount", DESCENDING)]),
        ])

        # 概念板块资金流向表
        await self._safe_create_indexes("moneyflow_concept", [
            IndexModel(
                [("ts_code", ASCENDING), ("trade_date", DESCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
            IndexModel([("name", ASCENDING)]),
            IndexModel([("net_amount", DESCENDING)]),
        ])

        # 涨跌停数据表
        await self._safe_create_indexes("limit_list", [
            IndexModel(
                [("ts_code", ASCENDING), ("trade_date", DESCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
            IndexModel([("limit", ASCENDING)]),
            IndexModel([("industry", ASCENDING)]),
            IndexModel([("limit_times", DESCENDING)]),
        ])

        # 板块/行业排名表
        await self._safe_create_indexes("sector_ranking", [
            IndexModel(
                [("trade_date", DESCENDING), ("ranking_type", ASCENDING), ("rank", ASCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
            IndexModel([("ranking_type", ASCENDING)]),
        ])

        # 每日统计表
        await self._safe_create_indexes("daily_stats", [
            IndexModel([("trade_date", DESCENDING)], unique=True),
        ])

        # 股票关联关系表
        await self._safe_create_indexes("stock_relations", [
            IndexModel(
                [
                    ("ts_code", ASCENDING),
                    ("source", ASCENDING),
                    ("relation_type", ASCENDING),
                    ("relation_key", ASCENDING),
                    ("source_trade_date", DESCENDING),
                ],
                unique=True,
            ),
            IndexModel([("ts_code", ASCENDING), ("relation_type", ASCENDING)]),
            IndexModel([("relation_type", ASCENDING), ("relation_name", ASCENDING)]),
            IndexModel([("source", ASCENDING), ("source_trade_date", DESCENDING)]),
        ])

        # 每日指标表 (PE/PB/换手率/市值等)
        await self._safe_create_indexes("daily_basic", [
            IndexModel(
                [("ts_code", ASCENDING), ("trade_date", DESCENDING)],
                unique=True,
            ),
            IndexModel([("trade_date", DESCENDING)]),
            IndexModel([("pe_ttm", ASCENDING)]),
            IndexModel([("pb", ASCENDING)]),
            IndexModel([("total_mv", DESCENDING)]),
        ])

        # 市场分析表 (情绪周期分析结果)
        await self._safe_create_indexes("market_analysis", [
            IndexModel([("trade_date", DESCENDING)], unique=True),
            IndexModel([("cycle", ASCENDING)]),
        ])

        # 市场晴雨表日表
        await self._safe_create_indexes("market_weather_daily", [
            IndexModel([("trade_date", DESCENDING)], unique=True),
            IndexModel([("temperature_index", DESCENDING)]),
        ])

        # 一句话选股查询记录
        await self._safe_create_indexes("stock_picker_runs", [
            IndexModel([("run_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ])

        # 股池
        await self._safe_create_indexes("stock_pools", [
            IndexModel([("pool_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("pool_type", ASCENDING)]),
            IndexModel([("updated_at", DESCENDING)]),
        ])

        # 监听触发事件
        await self._safe_create_indexes("listener_trigger_events", [
            IndexModel([("event_id", ASCENDING)], unique=True),
            IndexModel([("strategy_id", ASCENDING)]),
            IndexModel([("ts_code", ASCENDING)]),
            IndexModel([("triggered_at", DESCENDING)]),
        ])

        # 股池流转日志
        await self._safe_create_indexes("pool_transition_logs", [
            IndexModel([("transition_id", ASCENDING)], unique=True),
            IndexModel([("event_id", ASCENDING)]),
            IndexModel([("rule_id", ASCENDING), ("ts_code", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("to_pool_id", ASCENDING)]),
            IndexModel([("transition_date", DESCENDING)]),
        ])

        # 新闻表
        await self._safe_create_indexes("news", [
            IndexModel([("_key", ASCENDING)], unique=True, sparse=True),
            IndexModel([("datetime", DESCENDING)]),
            IndexModel([("content_hash", ASCENDING)], unique=True, sparse=True),
            IndexModel([("collect_time", DESCENDING)]),
            IndexModel([("event_id", ASCENDING)], sparse=True),
            IndexModel([("title", "text"), ("content", "text")]),
        ])

        # 策略表
        await self._safe_create_indexes("strategies", [
            IndexModel([("strategy_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
        ])

        # 数据同步记录表 (每个 sync_type 只保留一条记录)
        await self._safe_create_indexes("sync_records", [
            IndexModel([("sync_type", ASCENDING)], unique=True),
        ])

        # 任务执行记录表
        await self._safe_create_indexes("job_execution_records", [
            IndexModel([("execution_id", ASCENDING)], unique=True),
            IndexModel([("job_name", ASCENDING), ("started_at", DESCENDING)]),
            IndexModel([("status", ASCENDING), ("started_at", DESCENDING)]),
            IndexModel([("target_trade_date", DESCENDING), ("job_name", ASCENDING)]),
            IndexModel([("pipeline_name", ASCENDING), ("started_at", DESCENDING)]),
        ])

        # 核心链路就绪标记
        await self._safe_create_indexes("readiness_markers", [
            IndexModel([("marker_type", ASCENDING), ("trade_date", DESCENDING)], unique=True),
            IndexModel([("status", ASCENDING), ("trade_date", DESCENDING)]),
            IndexModel([("updated_at", DESCENDING)]),
        ])

        # 运维事件表
        await self._safe_create_indexes("ops_events", [
            IndexModel([("event_id", ASCENDING)], unique=True),
            IndexModel([("event_type", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("severity", ASCENDING), ("created_at", DESCENDING)]),
        ])

        # DataSync 死信/脏数据记录表
        await self._safe_create_indexes("datasync_dead_letters", [
            IndexModel([("dead_letter_id", ASCENDING)], unique=True),
            IndexModel([("job_name", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("collection", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("target_trade_date", DESCENDING)]),
            IndexModel([("error_type", ASCENDING), ("created_at", DESCENDING)]),
        ])

        # DataSync 断点续拉游标
        await self._safe_create_indexes("datasync_checkpoints", [
            IndexModel([("checkpoint_id", ASCENDING)], unique=True),
            IndexModel([("job_name", ASCENDING), ("target_trade_date", ASCENDING), ("window", ASCENDING)], unique=True),
            IndexModel([("status", ASCENDING), ("updated_at", DESCENDING)]),
            IndexModel([("job_name", ASCENDING), ("updated_at", DESCENDING)]),
        ])

        # DataSync 历史补缺队列
        await self._safe_create_indexes("datasync_backfill_jobs", [
            IndexModel([("job_id", ASCENDING)], unique=True),
            IndexModel([("dedupe_key", ASCENDING)], unique=True),
            IndexModel([("status", ASCENDING), ("priority", ASCENDING), ("created_at", ASCENDING)]),
            IndexModel([("dataset", ASCENDING), ("status", ASCENDING), ("target_trade_date", DESCENDING)]),
            IndexModel([("locked_by", ASCENDING), ("updated_at", DESCENDING)]),
        ])

        # DataSync 历史补缺每日预算
        await self._safe_create_indexes("datasync_backfill_budgets", [
            IndexModel([("budget_date", ASCENDING)], unique=True),
            IndexModel([("updated_at", DESCENDING)]),
        ])

        # K线练习会话表
        await self._safe_create_indexes("kline_practice_sessions", [
            IndexModel([("session_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ])

        # 交割单复盘分组
        await self._safe_create_indexes("trade_review_groups", [
            IndexModel([("group_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("updated_at", DESCENDING)]),
        ])

        # 交割单导入批次
        await self._safe_create_indexes("trade_review_import_batches", [
            IndexModel([("batch_id", ASCENDING)], unique=True),
            IndexModel([("group_id", ASCENDING)]),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("imported_at", DESCENDING)]),
        ])

        # 交割单逐笔记录
        await self._safe_create_indexes("trade_review_records", [
            IndexModel([("record_id", ASCENDING)], unique=True),
            IndexModel([("group_id", ASCENDING), ("dedupe_key", ASCENDING)], unique=True),
            IndexModel([("group_id", ASCENDING), ("trade_date", DESCENDING)]),
            IndexModel([("group_id", ASCENDING), ("category", ASCENDING), ("trade_date", DESCENDING)]),
            IndexModel([("group_id", ASCENDING), ("ts_code", ASCENDING), ("trade_date", DESCENDING)]),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("reviewed", ASCENDING)]),
        ])

        # 交割单持仓快照
        await self._safe_create_indexes("trade_review_positions", [
            IndexModel([("position_id", ASCENDING)], unique=True),
            IndexModel([("group_id", ASCENDING), ("ts_code", ASCENDING)], unique=True),
            IndexModel([("group_id", ASCENDING), ("market_value", DESCENDING)]),
            IndexModel([("group_id", ASCENDING), ("unrealized_pnl_pct", DESCENDING)]),
            IndexModel([("user_id", ASCENDING)]),
        ])

        self.logger.info("MongoDB indexes ensured")
        result = {
            "success": True,
            "scope": normalized_scope,
            "collections": sorted(normalized_collections) if normalized_collections else (
                sorted(self.CORE_INDEX_COLLECTIONS) if normalized_scope == "core" else "all"
            ),
        }
        self._active_index_scope = previous_scope
        self._active_index_collections = previous_collections
        return result

    # ==================== 通用 CRUD ====================

    async def insert_one(self, collection: str, document: dict) -> str:
        """插入单条文档"""
        self._ensure_initialized()
        document["created_at"] = datetime.now(UTC)
        result = await self._db[collection].insert_one(document)
        await self._mirror_write(
            f"insert_one:{collection}",
            lambda: self._mirror_db[collection].insert_one(copy.deepcopy(document)),
        )
        return str(result.inserted_id)

    async def insert_many(self, collection: str, documents: List[dict]) -> List[str]:
        """批量插入"""
        self._ensure_initialized()
        now = datetime.now(UTC)
        for doc in documents:
            doc["created_at"] = now
        result = await self._db[collection].insert_many(documents)
        await self._mirror_write(
            f"insert_many:{collection}",
            lambda: self._mirror_db[collection].insert_many(copy.deepcopy(documents)),
        )
        return [str(id) for id in result.inserted_ids]

    async def find_one(
        self,
        collection: str,
        filter: dict,
        projection: Optional[dict] = None,
        sort: Optional[List[tuple]] = None,
    ) -> Optional[dict]:
        """查询单条文档"""
        self._ensure_initialized()
        return await self._db[collection].find_one(filter, projection, sort=sort)

    async def find_many(
        self,
        collection: str,
        filter: dict,
        projection: Optional[dict] = None,
        sort: Optional[List[tuple]] = None,
        limit: int = 0,
        skip: int = 0,
    ) -> List[dict]:
        """查询多条文档"""
        self._ensure_initialized()

        cursor = self._db[collection].find(filter, projection)

        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)

        return await cursor.to_list(length=limit or None)

    async def update_one(
        self,
        collection: str,
        filter: dict,
        update: dict,
        upsert: bool = False,
    ) -> int:
        """更新单条文档"""
        self._ensure_initialized()

        # 检查是否包含任何 MongoDB 更新操作符
        has_operator = any(key.startswith("$") for key in update.keys())

        if not has_operator:
            # 如果没有操作符，自动包装为 $set
            update = {"$set": update}

        # 添加 updated_at 时间戳
        if "$set" in update:
            update["$set"]["updated_at"] = datetime.now(UTC)
        else:
            update["$set"] = {"updated_at": datetime.now(UTC)}

        result = await self._db[collection].update_one(filter, update, upsert=upsert)
        await self._mirror_write(
            f"update_one:{collection}",
            lambda: self._mirror_db[collection].update_one(
                copy.deepcopy(filter),
                copy.deepcopy(update),
                upsert=upsert,
            ),
        )
        return result.modified_count

    async def update_many(
        self,
        collection: str,
        filter: dict,
        update: dict,
    ) -> int:
        """更新多条文档"""
        self._ensure_initialized()

        # 检查是否包含任何 MongoDB 更新操作符
        has_operator = any(key.startswith("$") for key in update.keys())

        if not has_operator:
            # 如果没有操作符，自动包装为 $set
            update = {"$set": update}

        # 添加 updated_at 时间戳
        if "$set" in update:
            update["$set"]["updated_at"] = datetime.now(UTC)
        else:
            update["$set"] = {"updated_at": datetime.now(UTC)}

        result = await self._db[collection].update_many(filter, update)
        await self._mirror_write(
            f"update_many:{collection}",
            lambda: self._mirror_db[collection].update_many(
                copy.deepcopy(filter),
                copy.deepcopy(update),
            ),
        )
        return result.modified_count

    async def delete_one(self, collection: str, filter: dict) -> int:
        """删除单条文档"""
        self._ensure_initialized()
        result = await self._db[collection].delete_one(filter)
        await self._mirror_write(
            f"delete_one:{collection}",
            lambda: self._mirror_db[collection].delete_one(copy.deepcopy(filter)),
        )
        return result.deleted_count

    async def delete_many(self, collection: str, filter: dict) -> int:
        """删除多条文档"""
        self._ensure_initialized()
        result = await self._db[collection].delete_many(filter)
        await self._mirror_write(
            f"delete_many:{collection}",
            lambda: self._mirror_db[collection].delete_many(copy.deepcopy(filter)),
        )
        return result.deleted_count

    async def count(self, collection: str, filter: dict) -> int:
        """统计数量"""
        self._ensure_initialized()
        return await self._db[collection].count_documents(filter)

    async def aggregate(
        self,
        collection: str,
        pipeline: List[dict],
    ) -> List[dict]:
        """聚合查询"""
        self._ensure_initialized()
        cursor = self._db[collection].aggregate(pipeline)
        return await cursor.to_list(length=None)

    # ==================== 高性能批量写入 ====================

    async def bulk_upsert(
        self,
        collection: str,
        documents: List[dict],
        key_fields: List[str],
        batch_size: int = 1000,
    ) -> dict:
        """
        高性能批量 upsert

        使用 MongoDB BulkWrite 实现高效批量写入。

        Args:
            collection: 集合名
            documents: 文档列表
            key_fields: 用于匹配的字段名列表 (支持复合键)
            batch_size: 每批次大小 (默认 1000)

        Returns:
            {
                "matched": int,     # 匹配数
                "modified": int,    # 修改数
                "upserted": int,    # 新插入数
                "total": int,       # 总处理数
            }
        """
        result = await self.bulk_upsert_batched(
            collection=collection,
            documents=documents,
            key_fields=key_fields,
            batch_size=batch_size,
        )
        return {
            "matched": result["matched"],
            "modified": result["modified"],
            "upserted": result["upserted"],
            "inserted": result["inserted"],
            "failed": result["failed"],
            "total": result["total"],
            "batch_count": result["batch_count"],
            "batch_errors": result["batch_errors"],
        }

    async def bulk_upsert_batched(
        self,
        collection: str,
        documents: List[dict],
        key_fields: List[str],
        batch_size: Optional[int] = None,
        ordered: bool = False,
    ) -> dict:
        """统一幂等批量 upsert，强制业务主键和批次上限。"""
        self._ensure_initialized()

        if not key_fields:
            raise ValueError("bulk_upsert_batched requires key_fields")

        if not documents:
            return {
                "matched": 0,
                "modified": 0,
                "upserted": 0,
                "inserted": 0,
                "failed": 0,
                "total": 0,
                "batch_count": 0,
                "batch_size": 0,
                "batch_errors": [],
            }

        requested_batch_size = batch_size or settings.data_sync.bulk_upsert_batch_size
        min_batch_size = max(1, int(settings.data_sync.bulk_upsert_min_batch_size))
        max_batch_size = max(min_batch_size, int(settings.data_sync.bulk_upsert_max_batch_size))
        configured_batch_size = max(1, min(int(requested_batch_size), max_batch_size, 5000))
        effective_min_batch_size = min(min_batch_size, configured_batch_size)
        current_batch_size = max(effective_min_batch_size, configured_batch_size)
        slow_batch_ms = max(1, int(settings.data_sync.bulk_upsert_slow_batch_ms))
        stable_batches_to_grow = max(1, int(settings.data_sync.bulk_upsert_stable_batches_to_grow))
        total_matched = 0
        total_modified = 0
        total_upserted = 0
        total_failed = 0
        batch_count = 0
        stable_batches = 0
        batch_size_history: List[int] = []
        batch_errors: List[dict] = []
        now = datetime.now(UTC)

        i = 0
        while i < len(documents):
            batch = documents[i:i + current_batch_size]
            batch_size_history.append(len(batch))
            batch_count += 1
            operations = []
            try:
                for offset, doc in enumerate(batch):
                    missing_keys = [key for key in key_fields if key not in doc or doc.get(key) in (None, "")]
                    if missing_keys:
                        raise ValueError(
                            f"Document missing key_fields {missing_keys} at index {i + offset}"
                        )
                    doc["updated_at"] = now
                    filter_query = {key: doc[key] for key in key_fields}
                    operations.append(
                        UpdateOne(
                            filter_query,
                            {"$set": doc},
                            upsert=True,
                        )
                    )

                batch_started_at = time.perf_counter()
                result = await self._db[collection].bulk_write(
                    operations,
                    ordered=ordered,
                )
                await self._mirror_write(
                    f"bulk_upsert:{collection}",
                    lambda batch_docs=copy.deepcopy(batch): self._mirror_bulk_upsert(
                        collection=collection,
                        documents=batch_docs,
                        key_fields=key_fields,
                        ordered=ordered,
                    ),
                )
                total_matched += result.matched_count
                total_modified += result.modified_count
                total_upserted += result.upserted_count
                elapsed_ms = (time.perf_counter() - batch_started_at) * 1000
                i += len(batch)
                if elapsed_ms >= slow_batch_ms and current_batch_size > effective_min_batch_size:
                    next_batch_size = max(effective_min_batch_size, current_batch_size // 2)
                    if next_batch_size < current_batch_size:
                        self.logger.warning(
                            "Mongo bulk upsert batch slowed, shrinking batch size: "
                            "collection=%s elapsed_ms=%.2f current=%s next=%s",
                            collection,
                            elapsed_ms,
                            current_batch_size,
                            next_batch_size,
                        )
                    current_batch_size = next_batch_size
                    stable_batches = 0
                else:
                    stable_batches += 1
                    if stable_batches >= stable_batches_to_grow and current_batch_size < configured_batch_size:
                        next_batch_size = min(configured_batch_size, current_batch_size * 2)
                        if next_batch_size > current_batch_size:
                            self.logger.info(
                                "Mongo bulk upsert batch stable, growing batch size: "
                                "collection=%s current=%s next=%s",
                                collection,
                                current_batch_size,
                                next_batch_size,
                            )
                        current_batch_size = next_batch_size
                        stable_batches = 0
            except Exception as exc:
                total_failed += len(batch)
                batch_errors.append(
                    {
                        "batch_start": i,
                        "batch_size": len(batch),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                break

        final_result = {
            "matched": total_matched,
            "modified": total_modified,
            "upserted": total_upserted,
            "inserted": total_upserted,
            "failed": total_failed,
            "total": len(documents),
            "batch_count": batch_count,
            "batch_size": configured_batch_size,
            "batch_size_history": batch_size_history,
            "adaptive_batching": {
                "enabled": True,
                "min_batch_size": effective_min_batch_size,
                "max_batch_size": max_batch_size,
                "slow_batch_ms": slow_batch_ms,
                "stable_batches_to_grow": stable_batches_to_grow,
            },
            "batch_errors": batch_errors,
        }
        if batch_errors:
            raise BulkUpsertBatchError(collection, final_result)
        return final_result

    async def bulk_insert(
        self,
        collection: str,
        documents: List[dict],
        batch_size: int = 1000,
        ordered: bool = False,
    ) -> int:
        """
        高性能批量插入

        Args:
            collection: 集合名
            documents: 文档列表
            batch_size: 每批次大小
            ordered: 是否有序插入

        Returns:
            插入的文档数
        """
        self._ensure_initialized()

        if not documents:
            return 0

        now = datetime.now(UTC)
        total_inserted = 0

        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]

            for doc in batch:
                doc["created_at"] = now

            try:
                result = await self._db[collection].insert_many(
                    batch,
                    ordered=ordered,
                )
                total_inserted += len(result.inserted_ids)
                await self._mirror_write(
                    f"bulk_insert:{collection}",
                    lambda batch_docs=copy.deepcopy(batch): self._mirror_db[collection].insert_many(
                        batch_docs,
                        ordered=ordered,
                    ),
                )
            except Exception as e:
                # 如果是 unordered 模式，可能部分成功
                self.logger.warning(f"Bulk insert partial failure: {e}")

        return total_inserted

    # ==================== 数据同步辅助 ====================

    async def record_sync(
        self,
        sync_type: str,
        sync_date: str,
        count: int = 0,
    ) -> None:
        """
        记录数据同步 (更新最后同步日期)

        每个 sync_type 只保留一条记录，更新 sync_date 字段。

        Args:
            sync_type: 同步类型 (stock_basic, stock_daily, news, etc.)
            sync_date: 最后同步日期 (YYYYMMDD)
            count: 本次同步数量 (可选，用于记录)
        """
        await self.update_one(
            "sync_records",
            {"sync_type": sync_type},
            {
                "sync_type": sync_type,
                "sync_date": sync_date,
                "last_count": count,
                "updated_at": datetime.now(UTC),
            },
            upsert=True,
        )

    async def record_job_execution(
        self,
        job_name: str,
        *,
        node_id: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        trigger: str = "scheduler",
        run_date: Optional[str] = None,
        target_trade_date: Optional[str] = None,
        data_cutoff_time: Optional[str] = None,
        count: Optional[int] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        resource_class: Optional[str] = None,
        source: Optional[str] = None,
        details: Optional[dict] = None,
        pipeline_name: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> str:
        """记录一次任务执行明细。"""
        self._ensure_initialized()

        execution_key = execution_id or uuid.uuid4().hex
        payload = {
            "execution_id": execution_key,
            "job_name": job_name,
            "node_id": node_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "trigger": trigger,
            "run_date": run_date or started_at.strftime("%Y%m%d"),
            "target_trade_date": target_trade_date,
            "data_cutoff_time": data_cutoff_time,
            "count": count,
            "duration_ms": duration_ms,
            "error": error,
            "resource_class": resource_class,
            "source": source,
            "details": details or {},
            "pipeline_name": pipeline_name,
        }
        await self.insert_one("job_execution_records", payload)
        return execution_key

    async def upsert_readiness_marker(
        self,
        marker_type: str,
        trade_date: str,
        status: str,
        *,
        details: Optional[dict] = None,
        source: str = "datasync",
        node_id: Optional[str] = None,
        ready_at: Optional[datetime] = None,
        ready_datasets: Optional[List[str]] = None,
        pending_datasets: Optional[List[str]] = None,
        warnings: Optional[List[dict]] = None,
        last_checked_at: Optional[datetime] = None,
    ) -> None:
        """更新核心链路就绪状态。"""
        details_payload = details or {}
        payload = {
            "marker_type": marker_type,
            "trade_date": trade_date,
            "status": status,
            "source": source,
            "node_id": node_id,
            "ready_at": ready_at,
            "ready_datasets": ready_datasets if ready_datasets is not None else details_payload.get("ready_datasets", []),
            "pending_datasets": pending_datasets if pending_datasets is not None else details_payload.get("pending_datasets", []),
            "warnings": warnings if warnings is not None else details_payload.get("warnings", []),
            "last_checked_at": last_checked_at or datetime.now(UTC),
            "details": details_payload,
        }

        await self.update_one(
            "readiness_markers",
            {"marker_type": marker_type, "trade_date": trade_date},
            payload,
            upsert=True,
        )

    async def record_ops_event(
        self,
        event_type: str,
        *,
        severity: str,
        message: str,
        source: str = "datasync",
        node_id: Optional[str] = None,
        details: Optional[dict] = None,
        event_id: Optional[str] = None,
    ) -> str:
        """记录一条运维事件。"""
        self._ensure_initialized()

        payload = {
            "event_id": event_id or uuid.uuid4().hex,
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "source": source,
            "node_id": node_id,
            "details": details or {},
        }
        await self.insert_one("ops_events", payload)
        return payload["event_id"]

    async def record_dead_letters(
        self,
        *,
        job_name: str,
        collection: str,
        records: List[Dict[str, Any]],
        source: Optional[str] = None,
        target_trade_date: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> int:
        """记录采集器坏数据样本，带单次上限保护。"""
        self._ensure_initialized()
        if not records:
            return 0

        limit = max_records
        if limit is None:
            limit = settings.data_sync.dead_letter_max_records_per_batch
        safe_limit = max(1, min(int(limit or 20), 100))
        now = datetime.now(UTC)
        documents: List[dict] = []

        for record in records[:safe_limit]:
            raw_item = copy.deepcopy(record.get("raw_item") or {})
            reason = record.get("reason") or record.get("reasons") or "validation_failed"
            if isinstance(reason, list):
                reason = ",".join(str(item) for item in reason)
            item_trade_date = target_trade_date or raw_item.get("trade_date")
            documents.append(
                {
                    "dead_letter_id": uuid.uuid4().hex,
                    "job_name": job_name,
                    "collection": collection,
                    "source": source,
                    "target_trade_date": item_trade_date,
                    "reason": str(reason),
                    "raw_item": raw_item,
                    "error_type": str(record.get("error_type") or "validation_failed"),
                    "created_at": now,
                }
            )

        if not documents:
            return 0

        await self.bulk_insert(
            "datasync_dead_letters",
            documents,
            batch_size=min(safe_limit, 100),
            ordered=False,
        )
        return len(documents)

    @staticmethod
    def build_checkpoint_id(job_name: str, target_trade_date: str, window: str) -> str:
        """构造稳定 checkpoint 主键，避免重复创建同一续跑游标。"""
        safe_job_name = str(job_name or "").strip()
        safe_trade_date = str(target_trade_date or "").strip()
        safe_window = str(window or "").strip()
        if not safe_job_name or not safe_trade_date or not safe_window:
            raise ValueError("checkpoint requires job_name, target_trade_date, and window")
        return f"{safe_job_name}:{safe_trade_date}:{safe_window}"

    async def upsert_checkpoint(
        self,
        job_name: str,
        target_trade_date: str,
        window: str,
        *,
        cursor: Optional[Any] = None,
        last_success_key: Optional[str] = None,
        status: str = "running",
        details: Optional[dict] = None,
    ) -> str:
        """更新任务续跑游标，只记录真实已完成位置，不推测或补造数据。"""
        self._ensure_initialized()
        checkpoint_id = self.build_checkpoint_id(job_name, target_trade_date, window)
        now = datetime.now(UTC)
        payload = {
            "checkpoint_id": checkpoint_id,
            "job_name": job_name,
            "target_trade_date": target_trade_date,
            "window": window,
            "status": status,
            "details": details or {},
            "updated_at": now,
        }
        if cursor is not None:
            payload["cursor"] = cursor
        if last_success_key is not None:
            payload["last_success_key"] = last_success_key
        await self.update_one(
            "datasync_checkpoints",
            {"checkpoint_id": checkpoint_id},
            {
                "$set": payload,
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )
        return checkpoint_id

    async def get_checkpoint(
        self,
        job_name: str,
        target_trade_date: str,
        window: str,
    ) -> Optional[dict]:
        """读取指定任务窗口的续跑游标。"""
        self._ensure_initialized()
        checkpoint_id = self.build_checkpoint_id(job_name, target_trade_date, window)
        return await self.find_one("datasync_checkpoints", {"checkpoint_id": checkpoint_id})

    async def mark_checkpoint_done(
        self,
        job_name: str,
        target_trade_date: str,
        window: str,
        *,
        details: Optional[dict] = None,
    ) -> str:
        """标记任务窗口已完整完成。"""
        return await self.upsert_checkpoint(
            job_name,
            target_trade_date,
            window,
            status="done",
            details=details or {},
        )

    async def list_checkpoints(
        self,
        *,
        job_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """列出最近 checkpoint，用于运维排查当前任务停在哪里。"""
        query: Dict[str, Any] = {}
        if job_name:
            query["job_name"] = job_name
        if status:
            query["status"] = status
        safe_limit = max(1, min(int(limit or 20), 200))
        return await self.find_many(
            "datasync_checkpoints",
            query,
            sort=[("updated_at", DESCENDING)],
            limit=safe_limit,
        )

    @staticmethod
    def build_backfill_dedupe_key(
        dataset: str,
        target_trade_date: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """构造历史补缺任务去重键。"""
        safe_dataset = str(dataset or "").strip()
        safe_trade_date = str(target_trade_date or "").strip()
        safe_start = str(start_date or "").strip()
        safe_end = str(end_date or "").strip()
        if not safe_dataset or not safe_trade_date:
            raise ValueError("backfill job requires dataset and target_trade_date")
        return f"{safe_dataset}:{safe_trade_date}:{safe_start}:{safe_end}"

    async def create_backfill_job(
        self,
        *,
        dataset: str,
        target_trade_date: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        priority: int = 100,
        created_by: str = "manual",
        payload: Optional[dict] = None,
    ) -> dict:
        """创建或返回一个历史补缺任务，按业务维度去重。"""
        self._ensure_initialized()
        dedupe_key = self.build_backfill_dedupe_key(dataset, target_trade_date, start_date, end_date)
        now = datetime.now(UTC)
        job_id = uuid.uuid4().hex
        await self.update_one(
            "datasync_backfill_jobs",
            {"dedupe_key": dedupe_key},
            {
                "$setOnInsert": {
                    "job_id": job_id,
                    "dedupe_key": dedupe_key,
                    "dataset": dataset,
                    "target_trade_date": target_trade_date,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "pending",
                    "priority": int(priority),
                    "attempts": 0,
                    "last_error": None,
                    "created_by": created_by,
                    "payload": payload or {},
                    "created_at": now,
                },
                "$set": {
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        row = await self.find_one("datasync_backfill_jobs", {"dedupe_key": dedupe_key})
        return row or {}

    async def list_backfill_jobs(
        self,
        *,
        status: Optional[str] = None,
        dataset: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """列出历史补缺任务。"""
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if dataset:
            query["dataset"] = dataset
        safe_limit = max(1, min(int(limit or 20), 200))
        return await self.find_many(
            "datasync_backfill_jobs",
            query,
            sort=[("priority", ASCENDING), ("created_at", ASCENDING)],
            limit=safe_limit,
        )

    async def claim_backfill_jobs(
        self,
        *,
        limit: int,
        node_id: str,
        max_attempts: int = 3,
    ) -> List[dict]:
        """领取一小批 pending 补缺任务，避免 worker 单轮跑太多。"""
        self._ensure_initialized()
        safe_limit = max(1, min(int(limit or 1), 20))
        safe_max_attempts = max(1, int(max_attempts or 3))
        candidates = await self.find_many(
            "datasync_backfill_jobs",
            {
                "status": "pending",
                "attempts": {"$lt": safe_max_attempts},
            },
            sort=[("priority", ASCENDING), ("created_at", ASCENDING)],
            limit=safe_limit * 3,
        )

        claimed: List[dict] = []
        for candidate in candidates:
            if len(claimed) >= safe_limit:
                break
            job_id = candidate.get("job_id")
            if not job_id:
                continue
            modified = await self.update_one(
                "datasync_backfill_jobs",
                {
                    "job_id": job_id,
                    "status": "pending",
                    "attempts": {"$lt": safe_max_attempts},
                },
                {
                    "$set": {
                        "status": "running",
                        "locked_by": node_id,
                        "started_at": datetime.now(UTC),
                    },
                    "$inc": {
                        "attempts": 1,
                    },
                },
            )
            if modified:
                row = await self.find_one("datasync_backfill_jobs", {"job_id": job_id})
                if row:
                    claimed.append(row)
        return claimed

    async def get_backfill_budget_state(self, budget_date: str) -> dict:
        """读取某日历史补缺预算状态，不存在时返回零用量。"""
        self._ensure_initialized()
        safe_date = str(budget_date or "").strip()
        if not safe_date:
            raise ValueError("budget_date is required")
        row = await self.find_one("datasync_backfill_budgets", {"budget_date": safe_date})
        return row or {
            "budget_date": safe_date,
            "jobs_consumed": 0,
            "external_requests": 0,
            "success_count": 0,
            "failure_count": 0,
            "consecutive_failures": 0,
        }

    async def record_backfill_budget_usage(
        self,
        budget_date: str,
        *,
        job_success: bool,
        external_requests: int = 0,
        result: Optional[dict] = None,
    ) -> dict:
        """记录一次补缺任务对当日预算的消耗。"""
        self._ensure_initialized()
        safe_date = str(budget_date or "").strip()
        if not safe_date:
            raise ValueError("budget_date is required")
        safe_requests = max(0, int(external_requests or 0))
        now = datetime.now(UTC)
        update: Dict[str, Any] = {
            "$setOnInsert": {
                "budget_date": safe_date,
                "jobs_consumed": 0,
                "external_requests": 0,
                "success_count": 0,
                "failure_count": 0,
                "consecutive_failures": 0,
                "created_at": now,
            },
            "$inc": {
                "jobs_consumed": 1,
                "external_requests": safe_requests,
                "success_count": 1 if job_success else 0,
                "failure_count": 0 if job_success else 1,
            },
            "$set": {
                "updated_at": now,
                "last_result": result or {},
            },
        }
        if job_success:
            update["$set"]["consecutive_failures"] = 0
        else:
            update["$inc"]["consecutive_failures"] = 1

        await self.update_one(
            "datasync_backfill_budgets",
            {"budget_date": safe_date},
            update,
            upsert=True,
        )
        return await self.get_backfill_budget_state(safe_date)

    async def mark_backfill_job_done(
        self,
        job_id: str,
        *,
        result: Optional[dict] = None,
    ) -> None:
        """标记补缺任务完成。"""
        await self.update_one(
            "datasync_backfill_jobs",
            {"job_id": job_id},
            {
                "status": "done",
                "finished_at": datetime.now(UTC),
                "last_result": result or {},
                "last_error": None,
                "locked_by": None,
            },
        )

    async def mark_backfill_job_failed(
        self,
        job_id: str,
        *,
        error: str,
        result: Optional[dict] = None,
        max_attempts: int = 3,
    ) -> None:
        """标记补缺任务失败；未耗尽次数则回到 pending，耗尽后进入 failed。"""
        row = await self.find_one("datasync_backfill_jobs", {"job_id": job_id})
        attempts = int((row or {}).get("attempts") or 0)
        status = "failed" if attempts >= max(1, int(max_attempts or 3)) else "pending"
        await self.update_one(
            "datasync_backfill_jobs",
            {"job_id": job_id},
            {
                "status": status,
                "finished_at": datetime.now(UTC) if status == "failed" else None,
                "last_error": str(error),
                "last_result": result or {},
                "locked_by": None,
            },
        )

    async def pause_backfill_job(self, job_id: str) -> None:
        """暂停补缺任务。"""
        await self.update_one(
            "datasync_backfill_jobs",
            {"job_id": job_id},
            {
                "status": "paused",
                "locked_by": None,
            },
        )

    async def resume_backfill_job(self, job_id: str) -> None:
        """恢复暂停的补缺任务。"""
        await self.update_one(
            "datasync_backfill_jobs",
            {"job_id": job_id, "status": "paused"},
            {
                "status": "pending",
                "locked_by": None,
            },
        )

    async def _mirror_bulk_upsert(
        self,
        *,
        collection: str,
        documents: List[dict],
        key_fields: List[str],
        ordered: bool,
    ) -> None:
        """在镜像库执行 best-effort bulk upsert。"""
        if not self._mirror_db or not documents:
            return
        operations = []
        for doc in documents:
            filter_query = {k: doc[k] for k in key_fields}
            operations.append(
                UpdateOne(
                    filter_query,
                    {"$set": doc},
                    upsert=True,
                )
            )
        await self._mirror_db[collection].bulk_write(operations, ordered=ordered)

    async def is_synced(self, sync_type: str, sync_date: str, granularity: str = "day") -> bool:
        """
        检查指定日期是否已同步

        Args:
            sync_type: 同步类型
            sync_date: 同步日期 (YYYYMMDD 格式)
            granularity: 粒度 - "day" 按天检查, "month" 按月检查

        Returns:
            如果 sync_date <= 记录的 sync_date（按指定粒度），则认为已同步
        """
        record = await self.find_one(
            "sync_records",
            {"sync_type": sync_type},
        )
        if not record:
            return False
        last_sync = record.get("sync_date", "")

        if granularity == "month":
            # 按月比较: 只比较 YYYYMM
            return sync_date[:6] <= last_sync[:6]
        else:
            # 按天比较
            return sync_date <= last_sync

    async def get_last_sync_date(self, sync_type: str) -> Optional[str]:
        """
        获取最后同步日期

        Args:
            sync_type: 同步类型

        Returns:
            最后同步日期 (YYYYMMDD 格式)，从未同步过返回 None
        """
        record = await self.find_one(
            "sync_records",
            {"sync_type": sync_type},
        )
        return record.get("sync_date") if record else None

    async def find_one(
        self,
        collection: str,
        filter: dict,
        projection: Optional[dict] = None,
        sort: Optional[list] = None,
    ) -> Optional[dict]:
        """
        查询单条文档 (支持排序)

        Args:
            collection: 集合名
            filter: 过滤条件
            projection: 投影
            sort: 排序规则
        """
        self._ensure_initialized()

        if sort:
            cursor = self._db[collection].find(filter, projection).sort(sort).limit(1)
            results = await cursor.to_list(length=1)
            return results[0] if results else None

        return await self._db[collection].find_one(filter, projection)


# ==================== 全局单例 ====================
mongo_manager = MongoManager()
