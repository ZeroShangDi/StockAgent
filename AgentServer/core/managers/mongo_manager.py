"""
MongoDB 管理器

负责:
- 业务数据 CRUD
- 索引管理 (ensure_indexes)
- 高性能批量写入 (BulkWrite)
- 聚合查询
"""

from typing import Optional, Any, List, Dict, Tuple
from datetime import datetime
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel, UpdateOne, InsertOne
from pymongo.errors import OperationFailure

from core.base import BaseManager
from ..settings import settings


class MongoManager(BaseManager):
    """
    MongoDB 资源管理器
    
    特性:
    - 连接池管理 (默认 max_pool_size=100)
    - 索引自动创建
    - 高性能批量写入
    """
    
    def __init__(self):
        super().__init__()
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._config = settings.mongo
        self._aggregate_default_limit = self._get_timeout_ms("MONGO_AGGREGATE_DEFAULT_LIMIT", 10000)
        self._aggregate_batch_size = self._get_timeout_ms("MONGO_AGGREGATE_BATCH_SIZE", 1000)
        self._aggregate_max_time_ms = self._get_timeout_ms("MONGO_AGGREGATE_MAX_TIME_MS", 30000)
        self._index_create_timeout_seconds = max(1, self._config.index_create_timeout_seconds)

    def _get_timeout_ms(self, env_key: str, default_ms: int) -> int:
        value = os.getenv(env_key)
        if value is None or value == "":
            return default_ms
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default_ms
        except ValueError:
            return default_ms
    
    async def initialize(self) -> None:
        """初始化 MongoDB 连接"""
        if self._initialized:
            return
        
        self.logger.info(
            f"Connecting to MongoDB: {self._config.host}:{self._config.port} "
            f"(pool_size={self._config.max_pool_size})"
        )
        
        # NOTE: 在受限 sandbox 环境里，localhost 可能被禁用；需要更短的超时避免长时间挂起。
        # 可通过环境变量覆盖：
        # - MONGO_CONNECT_TIMEOUT_MS
        # - MONGO_SERVER_SELECTION_TIMEOUT_MS
        # - MONGO_SOCKET_TIMEOUT_MS
        connect_timeout_ms = self._get_timeout_ms("MONGO_CONNECT_TIMEOUT_MS", 5000)
        server_selection_timeout_ms = self._get_timeout_ms("MONGO_SERVER_SELECTION_TIMEOUT_MS", 5000)
        socket_timeout_ms = self._get_timeout_ms("MONGO_SOCKET_TIMEOUT_MS", 5000)

        self._client = AsyncIOMotorClient(
            self._config.url,
            maxPoolSize=self._config.max_pool_size,
            connectTimeoutMS=connect_timeout_ms,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
            socketTimeoutMS=socket_timeout_ms,
        )
        self._db = self._client[self._config.database]
        
        # 测试连接
        ping_timeout = max(connect_timeout_ms, server_selection_timeout_ms, socket_timeout_ms) / 1000.0 + 0.5
        await asyncio.wait_for(self._client.admin.command("ping"), timeout=ping_timeout)
        
        if self._config.ensure_indexes:
            await self._ensure_indexes()
        else:
            self.logger.info("MongoDB index ensuring skipped by MONGO_ENSURE_INDEXES=false")
        
        self._initialized = True
        self.logger.info(f"MongoDB connected, database: {self._config.database} ✓")
    
    async def shutdown(self) -> None:
        """关闭连接"""
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
                return True
        except Exception:
            pass
        return False
    
    @property
    def db(self) -> AsyncIOMotorDatabase:
        """获取数据库实例"""
        self._ensure_initialized()
        return self._db
    
    async def _safe_create_indexes(self, collection_name: str, indexes: List[IndexModel]) -> None:
        """安全创建索引，处理索引冲突
        
        当已存在同名但属性不同的索引时，先删除旧索引再创建新索引。
        """
        collection = self._db[collection_name]
        try:
            await asyncio.wait_for(
                collection.create_indexes(indexes),
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
                for idx in indexes:
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
                        collection.create_indexes(indexes),
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

    async def _ensure_indexes(self) -> None:
        """
        确保索引存在
        
        在初始化时自动调用，为所有业务表创建必要的索引。
        """
        self.logger.info("Ensuring MongoDB indexes...")
        
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
    
    # ==================== 通用 CRUD ====================
    
    async def insert_one(self, collection: str, document: dict) -> str:
        """插入单条文档"""
        self._ensure_initialized()
        document["created_at"] = datetime.utcnow()
        result = await self._db[collection].insert_one(document)
        return str(result.inserted_id)
    
    async def insert_many(self, collection: str, documents: List[dict]) -> List[str]:
        """批量插入"""
        self._ensure_initialized()
        if not documents:
            return []
        now = datetime.utcnow()
        inserted_ids: List[str] = []
        batch_size = max(1, self._config.insert_many_batch_size)
        for start in range(0, len(documents), batch_size):
            batch = documents[start:start + batch_size]
            for doc in batch:
                doc["created_at"] = now
            result = await self._db[collection].insert_many(batch)
            inserted_ids.extend(str(inserted_id) for inserted_id in result.inserted_ids)
        return inserted_ids
    
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
            update["$set"]["updated_at"] = datetime.utcnow()
        else:
            update["$set"] = {"updated_at": datetime.utcnow()}
        
        result = await self._db[collection].update_one(filter, update, upsert=upsert)
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
            update["$set"]["updated_at"] = datetime.utcnow()
        else:
            update["$set"] = {"updated_at": datetime.utcnow()}
        
        result = await self._db[collection].update_many(filter, update)
        return result.modified_count
    
    async def delete_one(self, collection: str, filter: dict) -> int:
        """删除单条文档"""
        self._ensure_initialized()
        result = await self._db[collection].delete_one(filter)
        return result.deleted_count
    
    async def delete_many(self, collection: str, filter: dict) -> int:
        """删除多条文档"""
        self._ensure_initialized()
        result = await self._db[collection].delete_many(filter)
        return result.deleted_count
    
    async def count(self, collection: str, filter: dict) -> int:
        """统计数量"""
        self._ensure_initialized()
        return await self._db[collection].count_documents(filter)
    
    async def aggregate(
        self,
        collection: str,
        pipeline: List[dict],
        limit: int = 0,
        allow_disk_use: bool = True,
    ) -> List[dict]:
        """聚合查询"""
        self._ensure_initialized()
        effective_limit = limit if limit and limit > 0 else self._aggregate_default_limit
        cursor = self._db[collection].aggregate(
            pipeline,
            allowDiskUse=allow_disk_use,
            batchSize=self._aggregate_batch_size,
            maxTimeMS=self._aggregate_max_time_ms,
        )
        return await cursor.to_list(length=effective_limit)
    
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
        self._ensure_initialized()
        
        if not documents:
            return {"matched": 0, "modified": 0, "upserted": 0, "total": 0}
        
        total_matched = 0
        total_modified = 0
        total_upserted = 0
        
        now = datetime.utcnow()
        
        # 分批处理
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            operations = []
            for doc in batch:
                doc["updated_at"] = now
                # 构建复合键查询条件
                filter_query = {k: doc[k] for k in key_fields}
                operations.append(
                    UpdateOne(
                        filter_query,
                        {"$set": doc},
                        upsert=True,
                    )
                )
            
            result = await self._db[collection].bulk_write(
                operations,
                ordered=False,  # 无序执行，提高性能
            )
            
            total_matched += result.matched_count
            total_modified += result.modified_count
            total_upserted += result.upserted_count
        
        return {
            "matched": total_matched,
            "modified": total_modified,
            "upserted": total_upserted,
            "total": len(documents),
        }
    
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
        
        now = datetime.utcnow()
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
                "updated_at": datetime.utcnow(),
            },
            upsert=True,
        )
    
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
