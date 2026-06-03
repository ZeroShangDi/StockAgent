"""
市场统计预聚合缓存服务

负责：
- 将重查询接口结果写入 Redis 热缓存
- 同步持久化到 MongoDB，便于服务重启后快速恢复
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from core.managers import mongo_manager, redis_manager


CACHE_COLLECTION = "market_statistics_cache"
REDIS_CACHE_PREFIX = "market_statistics"
DEFAULT_REDIS_TTL = 6 * 3600


def _redis_cache_key(cache_type: str, cache_key: str) -> str:
    return f"{REDIS_CACHE_PREFIX}:{cache_type}:{cache_key}"


async def get_cached_market_statistics(
    cache_type: str,
    cache_key: str,
) -> Optional[Dict[str, Any]]:
    """优先从 Redis 读取，回退到 MongoDB。"""
    redis_key = _redis_cache_key(cache_type, cache_key)

    if redis_manager.is_initialized:
        try:
            cached = await redis_manager.cache_get(redis_key)
            if cached:
                payload = json.loads(cached)
                payload["_cache"] = {"backend": "redis", "cache_type": cache_type, "cache_key": cache_key}
                return payload
        except Exception:
            pass

    record = await mongo_manager.find_one(
        CACHE_COLLECTION,
        {"cache_type": cache_type, "cache_key": cache_key},
        projection={"payload": 1, "_id": 0},
    )
    if not record:
        return None

    payload = dict(record.get("payload") or {})
    payload["_cache"] = {"backend": "mongodb", "cache_type": cache_type, "cache_key": cache_key}
    return payload


async def set_cached_market_statistics(
    cache_type: str,
    cache_key: str,
    payload: Dict[str, Any],
    *,
    trade_date: Optional[str] = None,
    ttl: int = DEFAULT_REDIS_TTL,
) -> None:
    """写入 Redis 和 MongoDB。"""
    normalized_payload = dict(payload)
    normalized_payload.pop("_cache", None)
    redis_key = _redis_cache_key(cache_type, cache_key)

    if redis_manager.is_initialized:
        await redis_manager.cache_set(
            redis_key,
            json.dumps(normalized_payload, ensure_ascii=False, default=str),
            ttl=ttl,
        )

    await mongo_manager.update_one(
        CACHE_COLLECTION,
        {"cache_type": cache_type, "cache_key": cache_key},
        {
            "cache_type": cache_type,
            "cache_key": cache_key,
            "trade_date": trade_date,
            "payload": normalized_payload,
            "updated_at": datetime.now(UTC),
        },
        upsert=True,
    )
