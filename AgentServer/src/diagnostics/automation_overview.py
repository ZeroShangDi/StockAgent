"""项目自动任务与自动流程总览。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence

from core.settings import settings


ACTIVE_SCHEDULED_ITEMS: Sequence[Dict[str, Any]] = (
    {
        "key": "stock_basic",
        "name": "stock_basic",
        "description": "采集股票基础信息和估值指标",
        "trigger_value": "0 9 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/basic.py",
    },
    {
        "key": "stock_daily",
        "name": "stock_daily",
        "description": "采集股票日线数据",
        "trigger_value": "30 15 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/daily.py",
    },
    {
        "key": "daily_basic",
        "name": "daily_basic",
        "description": "采集股票每日指标数据（PE/PB/换手率/市值等）",
        "trigger_value": "0 16 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/daily_basic.py",
    },
    {
        "key": "index_basic",
        "name": "index_basic",
        "description": "采集指数基础信息",
        "trigger_value": "0 9 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/index_basic.py",
    },
    {
        "key": "index_daily",
        "name": "index_daily",
        "description": "采集指数日线数据",
        "trigger_value": "35 15 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/index_daily.py",
    },
    {
        "key": "moneyflow_industry",
        "name": "moneyflow_industry",
        "description": "采集行业资金流向数据",
        "trigger_value": "0 16 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/moneyflow_industry.py",
    },
    {
        "key": "moneyflow_concept",
        "name": "moneyflow_concept",
        "description": "采集概念板块资金流向数据",
        "trigger_value": "5 16 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/moneyflow_concept.py",
    },
    {
        "key": "limit_list",
        "name": "limit_list",
        "description": "采集涨跌停统计数据",
        "trigger_value": "10 16 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/limit_list.py",
    },
    {
        "key": "stock_news",
        "name": "stock_news",
        "description": "采集涨跌停股票新闻",
        "trigger_value": "30 18 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/news/stock_news.py",
    },
    {
        "key": "fina_indicator",
        "name": "fina_indicator",
        "description": "采集财务数据（三大报表 + 财务指标）",
        "trigger_value": "0 9 1 * *",
        "file": "AgentServer/nodes/data_sync/collectors/stock/fina_indicator.py",
    },
    {
        "key": "hot_news",
        "name": "hot_news",
        "description": "采集多来源热点新闻",
        "trigger_value": "*/5 * * * *",
        "file": "AgentServer/nodes/data_sync/collectors/news/hot_news.py",
    },
    {
        "key": "ths_sector",
        "name": "ths_sector",
        "description": "采集同花顺板块和成分股映射",
        "trigger_value": "0 2 * * 6",
        "file": "AgentServer/nodes/data_sync/collectors/stock/ths_sector.py",
    },
    {
        "key": "review_data",
        "name": "review_data",
        "description": "采集每日复盘数据（连板/龙虎榜/热股等）",
        "trigger_value": "30 19 * * 1-5",
        "file": "AgentServer/nodes/data_sync/collectors/stock/review_data.py",
    },
    {
        "key": "daily_stats",
        "name": "daily_stats",
        "description": "计算每日统计数据",
        "trigger_value": "10 18 * * 1-5",
        "file": "AgentServer/nodes/data_sync/tasks/daily_stats.py",
    },
)

STANDBY_ITEMS: Sequence[Dict[str, Any]] = (
    {
        "key": "event_clustering",
        "name": "event_clustering",
        "description": "新闻事件聚类（深度去重）",
        "trigger_value": "*/30 * * * *",
        "file": "AgentServer/nodes/data_sync/tasks/event_clustering.py",
    },
    {
        "key": "news_lifecycle",
        "name": "news_lifecycle",
        "description": "新闻数据生命周期管理",
        "trigger_value": "0 3 * * *",
        "file": "AgentServer/nodes/data_sync/tasks/news_lifecycle.py",
    },
    {
        "key": "morning_report",
        "name": "morning_report",
        "description": "生成早报",
        "trigger_value": "50 8 * * 1-5",
        "file": "AgentServer/nodes/data_sync/generators/morning_report.py",
    },
    {
        "key": "noon_report",
        "name": "noon_report",
        "description": "生成午报",
        "trigger_value": "50 13 * * 1-5",
        "file": "AgentServer/nodes/data_sync/generators/noon_report.py",
    },
    {
        "key": "multi_source_news",
        "name": "multi_source_news",
        "description": "多源新闻聚合采集",
        "trigger_value": "* * * * *",
        "file": "AgentServer/nodes/data_sync/collectors/news/multi_source.py",
    },
)


def _build_scheduled_items(
    rows: Sequence[Dict[str, Any]],
    *,
    runtime_mode: str,
) -> List[Dict[str, Any]]:
    return [
        {
            "key": row["key"],
            "name": row["name"],
            "description": row["description"],
            "automation_type": "scheduled",
            "trigger_type": "cron",
            "trigger_value": row["trigger_value"],
            "runtime_mode": runtime_mode,
            "source": "DataSyncNode",
            "file": row["file"],
            "run_at_startup": runtime_mode == "active",
        }
        for row in rows
    ]


def _build_daemon_items() -> List[Dict[str, Any]]:
    return [
        {
            "key": "listener_polling",
            "name": "市场监听轮询",
            "description": "交易时段持续拉取实时行情并执行全部监听策略。",
            "automation_type": "daemon",
            "trigger_type": "interval",
            "trigger_value": f"{settings.listener.poll_interval} 秒轮询一次",
            "runtime_mode": "active",
            "source": "ListenerNode",
            "file": "AgentServer/nodes/listener/node.py",
            "run_at_startup": True,
        },
        {
            "key": "node_heartbeat",
            "name": "节点心跳保活",
            "description": "所有节点定期向 Redis 写入心跳，用于在线状态和服务发现。",
            "automation_type": "daemon",
            "trigger_type": "interval",
            "trigger_value": f"{settings.node.heartbeat_interval} 秒一次",
            "runtime_mode": "active",
            "source": "BaseNode",
            "file": "AgentServer/core/base/node.py",
            "run_at_startup": True,
        },
    ]


def _build_event_items() -> List[Dict[str, Any]]:
    return [
        {
            "key": "listener_notification_push",
            "name": "监听命中自动推送",
            "description": "监听策略命中后按通知配置自动发送预警消息。",
            "automation_type": "event",
            "trigger_type": "event",
            "trigger_value": "监听策略命中时",
            "runtime_mode": "active",
            "source": "ListenerNode / NotificationManager",
            "file": "AgentServer/nodes/listener/node.py",
            "run_at_startup": True,
        },
        {
            "key": "pool_transition",
            "name": "股池自动流转",
            "description": "监听命中且满足流转规则时，自动把股票移入或复制到目标股池。",
            "automation_type": "event",
            "trigger_type": "event",
            "trigger_value": "监听策略命中且规则通过时",
            "runtime_mode": "active",
            "source": "ListenerNode",
            "file": "AgentServer/nodes/listener/node.py",
            "run_at_startup": True,
        },
        {
            "key": "candidate_pool_expiry",
            "name": "候选池 5 日自动移出",
            "description": "候选池里来自一句话选股的股票，超过 5 个交易日后自动移出。",
            "automation_type": "event",
            "trigger_type": "event",
            "trigger_value": "访问或操作股池时自动清理",
            "runtime_mode": "active",
            "source": "Stock Picker API",
            "file": "AgentServer/nodes/web/api/stock_picker.py",
            "run_at_startup": False,
        },
    ]


async def build_automation_overview() -> Dict[str, Any]:
    scheduled_items = _build_scheduled_items(ACTIVE_SCHEDULED_ITEMS, runtime_mode="active")
    daemon_items = _build_daemon_items()
    event_items = _build_event_items()
    standby_items = _build_scheduled_items(STANDBY_ITEMS, runtime_mode="standby")

    total_active = len(scheduled_items) + len(daemon_items) + len(event_items)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "total_active": total_active,
            "scheduled": len(scheduled_items),
            "daemon": len(daemon_items),
            "event": len(event_items),
            "standby": len(standby_items),
        },
        "sections": {
            "scheduled": scheduled_items,
            "daemon": daemon_items,
            "event": event_items,
            "standby": standby_items,
        },
    }
