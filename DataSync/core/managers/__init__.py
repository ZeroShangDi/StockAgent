"""
资源管理器 (单例模式)

所有外部服务必须通过全局 Manager 单例访问。
禁止在业务代码中直接 import 外部库。

这里对与子模块重名的单例导出使用轻量代理对象，避免：
1. `from core.managers import redis_manager` 意外拿到子模块本身
2. 包导入时一次性把全部 manager 模块都拉起来
"""

from __future__ import annotations

from core.base import BaseManager


class _LazyAttrProxy:
    """延迟解析模块属性的简单代理。"""

    def __init__(self, module_name: str, attr_name: str):
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_attr_name", attr_name)

    def _resolve(self):
        module = __import__(f"{__name__}.{self._module_name}", fromlist=[self._attr_name])
        return getattr(module, self._attr_name)

    def __getattr__(self, item: str):
        return getattr(self._resolve(), item)

    def __setattr__(self, key: str, value):
        setattr(self._resolve(), key, value)

    def __repr__(self) -> str:
        return repr(self._resolve())


_EXPORTS = {
    "RedisManager": ("redis_manager", "RedisManager"),
    "MongoManager": ("mongo_manager", "MongoManager"),
    "LLMManager": ("llm_manager", "LLMManager"),
    "MilvusManager": ("milvus_manager", "MilvusManager"),
    "AnalysisManager": ("analysis_manager", "AnalysisManager"),
    "MarketCycle": ("analysis_manager", "MarketCycle"),
    "ThemeManager": ("theme_manager", "ThemeManager"),
    "ThemeStatus": ("theme_manager", "ThemeStatus"),
    "PromptManager": ("prompt_manager", "PromptManager"),
    "NotificationManager": ("notification_manager", "NotificationManager"),
    "DataSourceManager": ("data_source_manager", "DataSourceManager"),
    "StockRelationManager": ("stock_relation_manager", "StockRelationManager"),
    "TushareManager": ("tushare_manager", "TushareManager"),
    "AKShareManager": ("akshare_manager", "AKShareManager"),
}


def __getattr__(name: str):
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = export
    module = __import__(f"{__name__}.{module_name}", fromlist=[attr_name])
    return getattr(module, attr_name)


redis_manager = _LazyAttrProxy("redis_manager", "redis_manager")
mongo_manager = _LazyAttrProxy("mongo_manager", "mongo_manager")
llm_manager = _LazyAttrProxy("llm_manager", "llm_manager")
milvus_manager = _LazyAttrProxy("milvus_manager", "milvus_manager")
analysis_manager = _LazyAttrProxy("analysis_manager", "analysis_manager")
theme_manager = _LazyAttrProxy("theme_manager", "theme_manager")
prompt_manager = _LazyAttrProxy("prompt_manager", "prompt_manager")
notification_manager = _LazyAttrProxy("notification_manager", "notification_manager")
data_source_manager = _LazyAttrProxy("data_source_manager", "data_source_manager")
stock_relation_manager = _LazyAttrProxy("stock_relation_manager", "stock_relation_manager")
tushare_manager = _LazyAttrProxy("tushare_manager", "tushare_manager")
akshare_manager = _LazyAttrProxy("akshare_manager", "akshare_manager")


__all__ = [
    "BaseManager",
    "RedisManager",
    "redis_manager",
    "MongoManager",
    "mongo_manager",
    "LLMManager",
    "llm_manager",
    "MilvusManager",
    "milvus_manager",
    "AnalysisManager",
    "analysis_manager",
    "MarketCycle",
    "ThemeManager",
    "theme_manager",
    "ThemeStatus",
    "PromptManager",
    "prompt_manager",
    "NotificationManager",
    "notification_manager",
    "DataSourceManager",
    "data_source_manager",
    "StockRelationManager",
    "stock_relation_manager",
    "TushareManager",
    "tushare_manager",
    "AKShareManager",
    "akshare_manager",
    "initialize_all_managers",
    "shutdown_all_managers",
    "health_check_all",
]


async def initialize_all_managers() -> None:
    """
    按依赖顺序初始化所有管理器。

    初始化顺序:
    1. Redis (基础设施)
    2. MongoDB (基础设施)
    3. DataSource (统一数据源管理)
    4. LLM (AI 服务)
    5. Milvus (向量数据库)
    6. Prompt (提示词管理)
    7. Notification (通知服务)
    8. StockRelation (关系同步能力)
    """
    from .redis_manager import redis_manager
    from .mongo_manager import mongo_manager
    from .data_source_manager import data_source_manager
    from .llm_manager import llm_manager
    from .milvus_manager import milvus_manager
    from .prompt_manager import prompt_manager
    from .notification_manager import notification_manager
    from .stock_relation_manager import stock_relation_manager

    await redis_manager.initialize()
    await mongo_manager.initialize()
    await data_source_manager.initialize()
    await llm_manager.initialize()
    await milvus_manager.initialize()
    await prompt_manager.initialize()
    await notification_manager.initialize()
    await stock_relation_manager.initialize()


async def shutdown_all_managers() -> None:
    """关闭所有管理器。"""
    from .notification_manager import notification_manager
    from .prompt_manager import prompt_manager
    from .milvus_manager import milvus_manager
    from .llm_manager import llm_manager
    from .data_source_manager import data_source_manager
    from .stock_relation_manager import stock_relation_manager
    from .mongo_manager import mongo_manager
    from .redis_manager import redis_manager

    await notification_manager.shutdown()
    await prompt_manager.shutdown()
    await milvus_manager.shutdown()
    await llm_manager.shutdown()
    await data_source_manager.shutdown()
    await stock_relation_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()


async def health_check_all() -> dict[str, bool]:
    """检查所有管理器健康状态。"""
    from .redis_manager import redis_manager
    from .mongo_manager import mongo_manager
    from .data_source_manager import data_source_manager
    from .llm_manager import llm_manager
    from .milvus_manager import milvus_manager
    from .notification_manager import notification_manager
    from .stock_relation_manager import stock_relation_manager

    return {
        "redis": await redis_manager.health_check(),
        "mongo": await mongo_manager.health_check(),
        "data_source": await data_source_manager.health_check(),
        "llm": await llm_manager.health_check(),
        "milvus": await milvus_manager.health_check(),
        "notification": await notification_manager.health_check(),
        "stock_relations": await stock_relation_manager.health_check(),
    }
