"""
定时任务基类

所有定时调度任务的公共基类，提供：
- 调度时间管理
- 运行状态追踪
- 统一的 run() 入口

子类：
- BaseCollector: 数据采集，实现 collect()
- BaseTask: 处理任务，实现 execute()
- BaseGenerator: 生成任务，实现 generate()
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Iterable, Mapping
from datetime import UTC, datetime
import time
import logging


class ScheduledJob(ABC):
    """
    定时任务基类

    所有定时调度任务继承此类。

    Attributes:
        name: 任务名称
        description: 任务描述
        default_schedule: 默认 cron 表达式
        run_at_startup: 启动时是否立即运行
    """

    name: str
    description: str
    default_schedule: str
    run_at_startup: bool = True

    # 能力声明：用于生成数据能力目录和运维页面。子类可按需覆盖。
    dataset_name: Optional[str] = None
    resource_class: Optional[str] = None
    target_collections: Iterable[str] = ()
    dependencies: Iterable[str] = ()
    source_chain_keys: Iterable[str] = ()
    supports_backfill: bool = False
    quality_checks: Iterable[str] = ()
    recoverability: Mapping[str, Any] = {}

    # 子类需要设置的日志前缀
    _log_prefix: str = "job"

    @property
    def schedule(self) -> str:
        """获取调度时间，子类可重写从配置读取"""
        return self.default_schedule

    def __init__(self):
        self.logger = logging.getLogger(f"{self._log_prefix}.{self.name}")
        self._last_run: Optional[datetime] = None
        self._last_result: Optional[dict] = None

    @abstractmethod
    async def _do_work(self) -> Dict[str, Any]:
        """
        执行具体工作

        子类必须实现，返回至少包含 count 字段的 dict。
        """
        raise NotImplementedError

    async def run(self) -> dict:
        """运行任务"""
        start_time = time.time()

        try:
            result = await self._do_work()

            duration_ms = (time.time() - start_time) * 1000

            self._last_run = datetime.now(UTC)
            self._last_result = {
                "success": True,
                "count": result.get("count", 0),
                "duration_ms": duration_ms,
                **result,
            }

            return self._last_result

        except Exception as e:
            self.logger.exception(f"{self.__class__.__name__} failed: {e}")

            duration_ms = (time.time() - start_time) * 1000

            self._last_run = datetime.now(UTC)
            self._last_result = {
                "success": False,
                "error": str(e),
                "duration_ms": duration_ms,
            }

            return self._last_result

    @property
    def status(self) -> dict:
        """获取任务状态"""
        return {
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_result": self._last_result,
        }

    def capability_manifest(
        self,
        *,
        resource_class: Optional[str] = None,
        source_chains: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> Dict[str, Any]:
        """导出任务静态能力声明，不包含运行状态。"""
        source_chain_keys = list(self.source_chain_keys or ())
        can_recover_trade_date = callable(getattr(self, "recover_trade_date", None))
        can_backfill = bool(
            self.supports_backfill or callable(getattr(self, "backfill", None))
        )
        effective_resource_class = resource_class or self.resource_class or "background"
        return {
            "name": self.name,
            "description": self.description,
            "dataset_name": self.dataset_name or self.name,
            "resource_class": effective_resource_class,
            "default_schedule": self.default_schedule,
            "effective_schedule": self.schedule,
            "target_collections": list(self.target_collections or ()),
            "dependencies": list(self.dependencies or ()),
            "source_chain_keys": source_chain_keys,
            "source_chains": {
                key: list((source_chains or {}).get(key, []))
                for key in source_chain_keys
            },
            "supports_recover_trade_date": can_recover_trade_date,
            "supports_backfill": can_backfill,
            "recoverability": self._build_recoverability(
                can_recover_trade_date=can_recover_trade_date,
                can_backfill=can_backfill,
                resource_class=effective_resource_class,
            ),
            "quality_checks": list(self.quality_checks or ()),
            "run_at_startup": bool(self.run_at_startup),
        }

    def _build_recoverability(
        self,
        *,
        can_recover_trade_date: bool,
        can_backfill: bool,
        resource_class: str,
    ) -> Dict[str, Any]:
        """生成稳定的数据可恢复性声明，供能力目录和告警系统复用。"""
        declared = dict(self.recoverability or {})
        declared_mode = str(declared.get("mode") or "").strip().lower()
        if declared_mode in {"full", "best_effort", "none"}:
            mode = declared_mode
        elif can_recover_trade_date or can_backfill:
            mode = "full"
        else:
            mode = "best_effort"

        declared_severity = str(declared.get("severity_on_missing") or "").strip().lower()
        if declared_severity in {"info", "warning", "critical"}:
            severity = declared_severity
        elif mode == "none":
            severity = "warning"
        elif resource_class == "core":
            severity = "warning"
        else:
            severity = "info"

        if "can_rerun" in declared:
            can_rerun = bool(declared.get("can_rerun"))
        else:
            can_rerun = mode != "none"

        reason = declared.get("reason")
        if not reason:
            if mode == "full":
                reason = "支持按交易日或历史窗口进行可靠补缺。"
            elif mode == "none":
                reason = "错过采集窗口后无法可靠还原当时数据。"
            else:
                reason = "可重新运行获取最新结果，但历史定向补缺能力有限。"

        return {
            "mode": mode,
            "can_recover_trade_date": can_recover_trade_date,
            "can_backfill": can_backfill,
            "can_rerun": can_rerun,
            "severity_on_missing": severity,
            "reason": str(reason),
        }
