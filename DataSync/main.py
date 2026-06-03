"""Standalone DataSync service entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import ast
import importlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
SHARED_ENV_FALLBACK_FILES = (
    REPO_ROOT / ".env",
    REPO_ROOT / ".env.docker",
)


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone DataSync service")
    parser.add_argument(
        "--rpc-port",
        type=int,
        default=0,
        help="override DataSync RPC port",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only verify imports/config/jobs without starting the service",
    )
    parser.add_argument(
        "--check-startup",
        action="store_true",
        help="initialize managers, scheduler, and RPC server, then exit",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="lightweight liveness probe: validate config, Mongo, and Redis without heavy data queries",
    )
    parser.add_argument(
        "--ready",
        action="store_true",
        help="lightweight readiness probe: validate core ready marker and recent core failures",
    )
    parser.add_argument(
        "--audit-self-contained",
        action="store_true",
        help="verify DataSync can import all local modules without forbidden cross-service dependencies",
    )
    parser.add_argument(
        "--check-core-integrity",
        action="store_true",
        help="inspect recent core sync integrity without starting the long-running service",
    )
    parser.add_argument(
        "--recover-latest-core-gaps",
        action="store_true",
        help="attempt to rerun missing latest-trade-date core sync steps once, then exit",
    )
    parser.add_argument(
        "--recover-recent-core-gaps",
        action="store_true",
        help="attempt to recover missing core sync steps within the recent trade-date window",
    )
    parser.add_argument(
        "--safe-recover-core-window",
        action="store_true",
        help="safely repair the recent core sync window by combining inspection, recent recovery, targeted reruns, and final verification",
    )
    parser.add_argument(
        "--recover-job-trade-date",
        action="store_true",
        help="run a job's recover_trade_date(trade_date) hook directly for targeted repair",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="force a manual recovery/backfill outside the configured backfill window",
    )
    parser.add_argument(
        "--check-sync-targets",
        action="store_true",
        help="print current primary/mirror Mongo target status without starting the service",
    )
    parser.add_argument(
        "--ensure-indexes",
        action="store_true",
        help="manually ensure Mongo indexes; use --index-scope core/all or --index-collections",
    )
    parser.add_argument(
        "--ops-summary",
        action="store_true",
        help="print a compact operational summary including integrity, targets, and recent jobs",
    )
    parser.add_argument(
        "--recent-failed-jobs",
        action="store_true",
        help="print recent failed job execution records without starting the long-running service",
    )
    parser.add_argument(
        "--recent-ops-events",
        action="store_true",
        help="print recent DataSync operational events without starting the long-running service",
    )
    parser.add_argument(
        "--recent-checkpoints",
        action="store_true",
        help="print recent DataSync checkpoints without starting the long-running service",
    )
    parser.add_argument(
        "--enqueue-backfill-job",
        action="store_true",
        help="enqueue one DataSync backfill job; requires --job-name and --trade-date",
    )
    parser.add_argument(
        "--recent-backfill-jobs",
        action="store_true",
        help="print recent DataSync backfill jobs without starting the long-running service",
    )
    parser.add_argument(
        "--run-backfill-queue-once",
        action="store_true",
        help="consume one small batch from the backfill queue, respecting the backfill window unless --force is set",
    )
    parser.add_argument(
        "--core-job-runtime-summary",
        action="store_true",
        help="print recent runtime and success-rate summary for core sync jobs",
    )
    parser.add_argument(
        "--data-source-call-stats",
        action="store_true",
        help="print current DataSync process data-source call stats including timeouts, failures, and fallbacks",
    )
    parser.add_argument(
        "--data-capabilities",
        action="store_true",
        help="print the static machine-readable DataSync data capability catalog",
    )
    parser.add_argument(
        "--write-data-capabilities",
        nargs="?",
        const="config/datasync_capabilities.yaml",
        help="write the static DataSync capability catalog to a YAML/JSON file",
    )
    parser.add_argument(
        "--capabilities-format",
        choices=("yaml", "json"),
        default="yaml",
        help="output format for --data-capabilities or --write-data-capabilities (default: yaml)",
    )
    parser.add_argument(
        "--capabilities-profile",
        help="optional DataSync profile to use when generating the capability catalog",
    )
    parser.add_argument(
        "--reset-data-source-call-stats",
        action="store_true",
        help="reset current DataSync process data-source call stats window",
    )
    parser.add_argument(
        "--integrity-days",
        type=int,
        default=3,
        help="number of recent trade dates to inspect for --check-core-integrity (default: 3)",
    )
    parser.add_argument(
        "--job-log-limit",
        type=int,
        default=10,
        help="number of recent job execution records to include in --ops-summary (default: 10)",
    )
    parser.add_argument(
        "--require-recent-window-ready",
        action="store_true",
        help="make --check-core-integrity and --ops-summary exit non-zero unless the recent trade-date window is fully ready",
    )
    parser.add_argument(
        "--require-no-recent-failures",
        action="store_true",
        help="make --ops-summary exit non-zero if recent failed jobs are present in the summary window",
    )
    parser.add_argument(
        "--require-no-warning-events",
        action="store_true",
        help="make --ops-summary exit non-zero if warning/critical ops events exist in the recent event window",
    )
    parser.add_argument(
        "--require-no-data-source-degradation",
        action="store_true",
        help="make --ops-summary exit non-zero if current-process data-source timeouts, failures, or fallbacks are present",
    )
    parser.add_argument(
        "--require-no-core-data-source-degradation",
        action="store_true",
        help="make --ops-summary exit non-zero if current-process data-source degradation is present on core sync methods",
    )
    parser.add_argument(
        "--require-no-core-runtime-outliers",
        action="store_true",
        help="make --ops-summary exit non-zero if recent core jobs contain unusually long runtime outliers",
    )
    parser.add_argument(
        "--failure-lookback-hours",
        type=int,
        default=24,
        help="lookback window in hours for --recent-failed-jobs and --ops-summary failure checks (default: 24)",
    )
    parser.add_argument(
        "--event-lookback-hours",
        type=int,
        default=24,
        help="lookback window in hours for --recent-ops-events and --ops-summary event checks (default: 24)",
    )
    parser.add_argument(
        "--runtime-lookback-hours",
        type=int,
        default=24,
        help="lookback window in hours for --core-job-runtime-summary and --ops-summary runtime stats (default: 24)",
    )
    parser.add_argument(
        "--core-jobs-only",
        action="store_true",
        help="limit --recent-failed-jobs to core sync jobs only",
    )
    parser.add_argument(
        "--index-scope",
        choices=("core", "all", "none"),
        default="core",
        help="index scope for --ensure-indexes (default: core)",
    )
    parser.add_argument(
        "--index-collections",
        default="",
        help="comma-separated collection names for --ensure-indexes; overrides --index-scope filtering",
    )
    parser.add_argument(
        "--event-severities",
        default="",
        help="comma-separated severities for --recent-ops-events, for example info,warning",
    )
    parser.add_argument(
        "--env-file",
        help="explicit environment file to load before startup",
    )
    parser.add_argument(
        "--config-dir",
        help="optional YAML config directory override",
    )
    parser.add_argument(
        "--job-name",
        help="job name for targeted operations such as --recover-job-trade-date, --recent-checkpoints, or --enqueue-backfill-job",
    )
    parser.add_argument(
        "--start-date",
        help="optional start date (YYYYMMDD) for --enqueue-backfill-job",
    )
    parser.add_argument(
        "--end-date",
        help="optional end date (YYYYMMDD) for --enqueue-backfill-job",
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=100,
        help="priority for --enqueue-backfill-job, lower runs earlier (default: 100)",
    )
    parser.add_argument(
        "--created-by",
        default="cli",
        help="creator label for --enqueue-backfill-job (default: cli)",
    )
    parser.add_argument(
        "--backfill-status",
        help="optional status filter for --recent-backfill-jobs, for example pending or failed",
    )
    parser.add_argument(
        "--checkpoint-status",
        help="optional checkpoint status filter for --recent-checkpoints, for example running or done",
    )
    parser.add_argument(
        "--trade-date",
        help="target trade date (YYYYMMDD) for --recover-job-trade-date",
    )
    return parser


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _collect_env_files(cli_env_file: str | None) -> tuple[list[Path], str]:
    if cli_env_file:
        path = Path(cli_env_file).expanduser().resolve()
        return ([path] if path.exists() else [], "explicit")

    local_env = CURRENT_DIR / ".env"
    if local_env.exists():
        return ([local_env], "local")

    local_env_docker = CURRENT_DIR / ".env.docker"
    if local_env_docker.exists():
        return ([local_env_docker], "local")

    if _env_flag("DATASYNC_ALLOW_SHARED_ENV_FALLBACK", True):
        shared_existing = [path for path in SHARED_ENV_FALLBACK_FILES if path.exists()]
        if shared_existing:
            return (shared_existing, "shared_fallback")

    return ([], "none")


def _normalize_runtime_path(raw_value: str, runtime_dir: Path) -> Path:
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = runtime_dir / path
    return path.resolve()


def _normalize_milvus_uri(raw_value: str, runtime_dir: Path) -> str:
    # 仅将本地路径锚定到独立 DataSync 运行目录；远程 URI 保持原样。
    if "://" in raw_value:
        return raw_value
    return str(_normalize_runtime_path(raw_value, runtime_dir))


def _running_inside_container() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("DATASYNC_IN_DOCKER") == "1"


def _normalize_local_service_hosts() -> None:
    if _running_inside_container():
        return

    docker_host_map = {
        "REDIS_HOST": {"redis"},
        "MONGO_HOST": {"mongodb", "mongo"},
        "MILVUS_HOST": {"milvus"},
    }
    for env_name, docker_hosts in docker_host_map.items():
        raw_value = (os.environ.get(env_name) or "").strip().lower()
        if raw_value in docker_hosts:
            os.environ[env_name] = "localhost"


def _prepare_runtime(cli_env_file: str | None) -> dict[str, Any]:
    from dotenv import load_dotenv

    loaded_env_files, env_source = _collect_env_files(cli_env_file)
    for env_file in loaded_env_files:
        load_dotenv(env_file, override=False)

    _normalize_local_service_hosts()

    runtime_dir = _normalize_runtime_path(
        os.environ.get("DATASYNC_RUNTIME_DIR", "."),
        CURRENT_DIR,
    )
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime_dir)

    # DataSync 作为独立服务，节点类型应始终固定为 data_sync，
    # 避免继承到外层 shell 或其他服务残留的 NODE_TYPE。
    os.environ["NODE_TYPE"] = "data_sync"

    log_dir = _normalize_runtime_path(os.environ.get("OBS_LOG_DIR", "logs"), runtime_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    os.environ["OBS_LOG_DIR"] = str(log_dir)

    data_dir = _normalize_runtime_path(os.environ.get("DATASYNC_DATA_DIR", "data"), runtime_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    milvus_uri = _normalize_milvus_uri(
        os.environ.get("MILVUS_URI", str(data_dir / "milvus_lite.db")),
        runtime_dir,
    )
    os.environ["MILVUS_URI"] = milvus_uri

    if env_source == "shared_fallback":
        print(
            "WARNING: DataSync is using shared repository env files as a compatibility fallback. "
            "Create DataSync/.env or DataSync/.env.docker to make this service self-contained."
        )

    return {
        "runtime_dir": runtime_dir,
        "env_files": loaded_env_files,
        "env_source": env_source,
        "log_dir": log_dir,
        "data_dir": data_dir,
        "milvus_uri": milvus_uri,
    }


def _load_app_config(config_dir: str | None) -> int:
    from src.config import config_manager

    resolved_config_dir: str | None = None
    if config_dir:
        config_path = Path(config_dir).expanduser()
        if not config_path.is_absolute():
            config_path = (CURRENT_DIR / config_path).resolve()
        resolved_config_dir = str(config_path)

    config_count = config_manager.load(config_dir=resolved_config_dir)
    print(f"Loaded {config_count} YAML config files from {config_manager.config_dir}")
    return config_count


def _print_runtime_summary(runtime: dict[str, Any]) -> None:
    print(f"DataSync runtime dir: {runtime['runtime_dir']}")
    print(f"DataSync log dir: {runtime['log_dir']}")
    print(f"DataSync data dir: {runtime['data_dir']}")
    print(f"DataSync milvus uri: {runtime['milvus_uri']}")
    print(f"DataSync env source: {runtime['env_source']}")
    if runtime["env_files"]:
        print("Loaded env files:")
        for env_file in runtime["env_files"]:
            print(f" - {env_file}")
    else:
        print("Loaded env files: none")


def _resolve_datasync_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = CURRENT_DIR / path
    return path.resolve()


def _check_setup(rpc_port: int) -> int:
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()
    print(f"DataSync bootstrap OK: jobs={len(node._jobs)}")
    for job in node._jobs:
        print(f" - {job.name}")
    return 0


def _print_data_capabilities(profile: str | None, output_format: str) -> int:
    from src.datasync_capabilities import build_data_capabilities

    catalog = build_data_capabilities(profile=profile)
    print("DataSync data capability catalog")
    if output_format == "json":
        print(json.dumps(catalog, ensure_ascii=False, indent=2, default=str))
    else:
        import yaml

        print(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
    return 0


def _write_data_capabilities(raw_path: str, profile: str | None, output_format: str) -> int:
    from src.datasync_capabilities import write_data_capabilities

    output_path = _resolve_datasync_path(raw_path)
    catalog = write_data_capabilities(
        output_path,
        profile=profile,
        output_format=output_format,
    )
    print("DataSync data capability catalog written")
    print(f"Path: {output_path}")
    print(f"Format: {output_format}")
    print(f"Profile: {catalog.get('profile')}")
    print(f"Capabilities: {catalog.get('count')}")
    return 0


def _iter_module_names(root_dir: Path) -> list[str]:
    module_names: list[str] = []
    for path in sorted(root_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(root_dir).with_suffix("")
        module_names.append(".".join(rel.parts))
    return module_names


def _audit_forbidden_imports(root_dir: Path) -> list[tuple[str, int, str]]:
    forbidden_prefixes = (
        "AgentServer",
        "nodes.web",
        "nodes.listener",
        "nodes.inference",
    )
    violations: list[tuple[str, int, str]] = []

    for path in sorted(root_dir.rglob("*.py")):
        rel_path = str(path.relative_to(root_dir))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if any(node.module.startswith(prefix) for prefix in forbidden_prefixes):
                    violations.append((rel_path, node.lineno, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(prefix) for prefix in forbidden_prefixes):
                        violations.append((rel_path, node.lineno, alias.name))

    return violations


def _audit_module_imports(root_dir: Path) -> list[tuple[str, str, str]]:
    import_failures: list[tuple[str, str, str]] = []
    for module_name in _iter_module_names(root_dir):
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - diagnostic path
            import_failures.append((module_name, type(exc).__name__, str(exc)))
    return import_failures


def _audit_module_origins(root_dir: Path) -> list[tuple[str, str]]:
    local_packages = {"common", "core", "nodes", "src", "config"}
    normalized_root = root_dir.resolve()
    origin_violations: list[tuple[str, str]] = []

    for module_name, module in sorted(sys.modules.items()):
        if not module_name:
            continue
        top_level_name = module_name.split(".", 1)[0]
        if top_level_name not in local_packages:
            continue

        module_file = getattr(module, "__file__", None)
        if module_file:
            resolved_file = Path(module_file).resolve()
            if normalized_root not in resolved_file.parents and resolved_file != normalized_root:
                origin_violations.append((module_name, str(resolved_file)))
            continue

        module_paths = getattr(module, "__path__", None)
        if module_paths:
            for module_path in module_paths:
                resolved_path = Path(module_path).resolve()
                if normalized_root not in resolved_path.parents and resolved_path != normalized_root:
                    origin_violations.append((module_name, str(resolved_path)))

    return origin_violations


def _audit_self_contained(runtime: dict[str, Any], config_dir: str | None) -> int:
    if runtime["env_source"] == "shared_fallback":
        print("DataSync self-contained audit failed: shared repository env fallback is still in use.")
        return 1

    if runtime["env_source"] == "none":
        print("DataSync self-contained audit failed: no local or explicit env file was loaded.")
        return 1

    _load_app_config(config_dir)
    root_dir = CURRENT_DIR

    import_failures = _audit_module_imports(root_dir)
    if import_failures:
        print("DataSync self-contained audit failed: module import errors detected.")
        for module_name, error_type, message in import_failures:
            print(f" - {module_name}: {error_type}: {message}")
        return 1

    violations = _audit_forbidden_imports(root_dir)
    if violations:
        print("DataSync self-contained audit failed: forbidden cross-service imports detected.")
        for rel_path, lineno, module_name in violations:
            print(f" - {rel_path}:{lineno}: {module_name}")
        return 1

    origin_violations = _audit_module_origins(root_dir)
    if origin_violations:
        print("DataSync self-contained audit failed: local modules resolved outside DataSync root.")
        for module_name, origin in origin_violations:
            print(f" - {module_name}: {origin}")
        return 1

    print("DataSync self-contained audit OK")
    print(f"DataSync audited modules: {len(_iter_module_names(root_dir))}")
    print("DataSync forbidden import prefixes: AgentServer, nodes.web, nodes.listener, nodes.inference")
    print(f"DataSync module root: {root_dir.resolve()}")
    return 0


def _build_probe_result(
    *,
    probe: str,
    checks: dict[str, bool],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建统一探针结果，方便 CLI、Docker 和测试复用。"""
    success = all(bool(value) for value in checks.values())
    return {
        "success": success,
        "probe": probe,
        "checks": checks,
        "details": details or {},
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _derive_ready_probe_result(marker: dict[str, Any] | None, recent_failures: list[dict]) -> dict[str, Any]:
    """根据轻量 Mongo 结果判断 DataSync 是否业务就绪。"""
    status = str((marker or {}).get("status") or "missing")
    marker_usable = status in {"ready", "degraded"}
    no_recent_failures = len(recent_failures) == 0
    return _build_probe_result(
        probe="ready",
        checks={
            "core_ready_marker": marker_usable,
            "recent_core_failures": no_recent_failures,
        },
        details={
            "marker_status": status,
            "marker_trade_date": (marker or {}).get("trade_date"),
            "recent_failure_count": len(recent_failures),
            "recent_failures": recent_failures[:5],
            "usable_statuses": ["ready", "degraded"],
        },
    )


async def _health_async() -> int:
    """轻量健康检查：只确认配置、Redis、Mongo 可用。"""
    from core.managers import mongo_manager, redis_manager, shutdown_all_managers

    checks = {"config": True, "redis": False, "mongo": False}
    details: dict[str, Any] = {}
    try:
        try:
            await redis_manager.initialize()
            checks["redis"] = bool(redis_manager.is_initialized and await redis_manager.health_check())
        except Exception as exc:
            details["redis_error"] = str(exc)

        try:
            original_ensure_indexes = mongo_manager._config.ensure_indexes
            mongo_manager._config.ensure_indexes = False
            try:
                await mongo_manager.initialize()
            finally:
                mongo_manager._config.ensure_indexes = original_ensure_indexes
            checks["mongo"] = bool(mongo_manager.is_initialized and await mongo_manager.health_check())
            if checks["mongo"]:
                details["mongo_targets"] = await mongo_manager.get_target_status()
        except Exception as exc:
            details["mongo_error"] = str(exc)

        result = _build_probe_result(probe="health", checks=checks, details=details)
        print("DataSync health probe")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _ready_async(failure_lookback_hours: int) -> int:
    """轻量就绪检查：只读取 ready marker 和近期核心失败记录。"""
    from core.managers import mongo_manager, shutdown_all_managers
    from nodes.data_sync.services.ops_summary import CORE_JOB_NAMES, _normalize

    try:
        original_ensure_indexes = mongo_manager._config.ensure_indexes
        mongo_manager._config.ensure_indexes = False
        try:
            await mongo_manager.initialize()
        finally:
            mongo_manager._config.ensure_indexes = original_ensure_indexes
        marker = await mongo_manager.find_one(
            "readiness_markers",
            {"marker_type": "market_core_ready"},
            sort=[("trade_date", -1)],
        )
        cutoff = datetime.now(UTC) - timedelta(
            hours=max(1, min(int(failure_lookback_hours or 24), 24 * 30))
        )
        recent_failures = await mongo_manager.find_many(
            "job_execution_records",
            {
                "job_name": {"$in": sorted(CORE_JOB_NAMES)},
                "status": "failed",
                "started_at": {"$gte": cutoff},
            },
            sort=[("started_at", -1)],
            limit=10,
        )
        result = _derive_ready_probe_result(_normalize(marker), _normalize(recent_failures))
        result["details"]["failure_lookback_hours"] = failure_lookback_hours
        print("DataSync readiness probe")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    except Exception as exc:
        result = _build_probe_result(
            probe="ready",
            checks={"mongo": False, "core_ready_marker": False, "recent_core_failures": False},
            details={"error": str(exc)},
        )
        print("DataSync readiness probe")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1
    finally:
        await shutdown_all_managers()


async def _check_startup_async(rpc_port: int) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._running = True

    try:
        await node.start()
        mongo_targets = await mongo_manager.get_target_status()
        checks = {
            "redis": redis_manager.is_initialized and await redis_manager.health_check(),
            "mongo": mongo_manager.is_initialized and await mongo_manager.health_check(),
            "data_source": data_source_manager.is_initialized and bool(data_source_manager.get_available_adapters()),
            "llm": llm_manager.is_initialized,
        }
        print("DataSync startup OK")
        print(f"DataSync RPC address: {node._rpc_address}")
        print(f"DataSync registered jobs: {len(node._jobs)}")
        print(f"DataSync adapters: {data_source_manager.get_available_adapters()}")
        print(f"DataSync mongo primary: {mongo_targets['primary']}")
        print(f"DataSync mongo mirror: {mongo_targets['mirror']}")
        for name, healthy in checks.items():
            status = "ok" if healthy else "failed"
            print(f" - {name}: {status}")
        return 0 if all(checks.values()) else 1
    finally:
        node._running = False
        await node._stop_rpc_server()
        await node.stop()
        await shutdown_all_managers()


async def _check_core_integrity_async(days: int, require_recent_window_ready: bool) -> int:
    from core.managers import data_source_manager, mongo_manager, redis_manager, shutdown_all_managers
    from nodes.data_sync.services.core_integrity import build_core_integrity_overview

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        overview = await build_core_integrity_overview(days=days)
        print("DataSync core integrity overview")
        print(json.dumps(overview, ensure_ascii=False, indent=2, default=str))
        recent_window_ready = bool(overview.get("recent_window_ready"))
        if require_recent_window_ready:
            return 0 if (overview.get("success") and recent_window_ready) else 1
        return 0 if overview.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _recover_latest_core_gaps_async(rpc_port: int) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await llm_manager.initialize()
        result = await node._recover_latest_core_gaps(trigger="cli_recovery")
        print("DataSync latest core gap recovery")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _recover_recent_core_gaps_async(rpc_port: int, days: int) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await llm_manager.initialize()
        result = await node._recover_recent_core_gaps(trigger="cli_recent_recovery", days=days)
        print("DataSync recent core gap recovery")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _safe_recover_core_window_async(rpc_port: int, days: int) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode
    from nodes.data_sync.services.core_integrity import build_core_integrity_overview

    window_days = max(1, min(int(days or 3), 10))
    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await llm_manager.initialize()

        before = await build_core_integrity_overview(days=window_days)
        recent_recovery = await node._recover_recent_core_gaps(
            trigger="cli_safe_window_recovery",
            days=window_days,
        )
        after_recent = await build_core_integrity_overview(days=window_days)

        targeted_repairs: list[dict[str, Any]] = []
        unsupported: list[dict[str, str]] = []
        for entry in after_recent.get("overview", []):
            if entry.get("ready"):
                continue
            trade_date = str(entry.get("trade_date") or "")
            if not trade_date:
                continue
            for dataset_state in entry.get("datasets", []):
                if dataset_state.get("ok"):
                    continue
                dataset = str(dataset_state.get("dataset") or "")
                if dataset not in node.RECENT_RECOVERABLE_DATASETS:
                    unsupported.append({"trade_date": trade_date, "dataset": dataset})
                    continue
                repair = await node._recover_job_trade_date(
                    dataset,
                    trade_date,
                    trigger="cli_safe_window_targeted_recovery",
                    pipeline_name="safe_core_window_recovery",
                )
                targeted_repairs.append(
                    {
                        "trade_date": trade_date,
                        "dataset": dataset,
                        "repair": repair,
                    }
                )

        final_overview = await build_core_integrity_overview(days=window_days)
        success = bool(
            before.get("success")
            and recent_recovery.get("success")
            and final_overview.get("success")
        )
        recent_window_ready = bool(final_overview.get("recent_window_ready"))

        result = {
            "success": success,
            "days": window_days,
            "before": before,
            "recent_recovery": recent_recovery,
            "after_recent_recovery": after_recent,
            "targeted_repairs": targeted_repairs,
            "unsupported": unsupported,
            "final": final_overview,
            "recent_window_ready": recent_window_ready,
        }

        print("DataSync safe core window recovery")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if (success and recent_window_ready) else 1
    finally:
        await shutdown_all_managers()


async def _recover_job_trade_date_async(rpc_port: int, job_name: str, trade_date: str, force: bool = False) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await llm_manager.initialize()

        result = await node._recover_job_trade_date(
            job_name,
            trade_date,
            trigger="cli_targeted_recovery",
            force_backfill_window=force,
        )
        print("DataSync targeted job trade-date recovery")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _check_sync_targets_async() -> int:
    from core.managers import mongo_manager, shutdown_all_managers

    try:
        await mongo_manager.initialize()
        status = await mongo_manager.get_target_status()
        print("DataSync sync target status")
        print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
        primary_ok = bool(status.get("primary", {}).get("healthy"))
        mirror = status.get("mirror", {})
        mirror_required = bool(mirror.get("enabled"))
        mirror_ok = bool(mirror.get("healthy")) if mirror_required else True
        return 0 if (primary_ok and mirror_ok) else 1
    finally:
        await shutdown_all_managers()


async def _ensure_indexes_async(scope: str, collections: list[str]) -> int:
    from core.managers import mongo_manager, shutdown_all_managers

    try:
        original_ensure_indexes = mongo_manager._config.ensure_indexes
        mongo_manager._config.ensure_indexes = False
        try:
            await mongo_manager.initialize()
        finally:
            mongo_manager._config.ensure_indexes = original_ensure_indexes
        result = await mongo_manager.ensure_indexes(
            scope=scope,
            collections=collections or None,
        )
        print("DataSync Mongo index ensuring")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _ops_summary_async(
    integrity_days: int,
    job_log_limit: int,
    require_recent_window_ready: bool,
    require_no_recent_failures: bool,
    require_no_warning_events: bool,
    require_no_data_source_degradation: bool,
    require_no_core_data_source_degradation: bool,
    require_no_core_runtime_outliers: bool,
    failure_lookback_hours: int,
    event_lookback_hours: int,
    runtime_lookback_hours: int,
) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from nodes.data_sync.services.ops_summary import build_ops_summary

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await llm_manager.initialize()
        summary = await build_ops_summary(
            integrity_days=integrity_days,
            recent_job_limit=job_log_limit,
            recent_failure_lookback_hours=failure_lookback_hours,
            recent_event_lookback_hours=event_lookback_hours,
            core_runtime_lookback_hours=runtime_lookback_hours,
        )
        print("DataSync operational summary")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        probe_checks = summary.get("probe_checks") or {}
        checks = [
            bool(summary.get("success")),
            bool(probe_checks.get("primary_target_healthy")),
            bool(probe_checks.get("latest_core_effectively_ready")),
        ]
        if require_recent_window_ready:
            checks.append(bool(probe_checks.get("recent_window_ready")))
        if require_no_recent_failures:
            checks.append(bool(probe_checks.get("no_unresolved_recent_failures")))
        if require_no_warning_events:
            checks.append(bool(probe_checks.get("no_unresolved_warning_events")))
        if require_no_data_source_degradation:
            data_source_degraded_count = int(
                summary.get("data_source_runtime_stats", {}).get("degraded_entry_count") or 0
            )
            checks.append(data_source_degraded_count == 0)
        if require_no_core_data_source_degradation:
            checks.append(bool(probe_checks.get("no_core_data_source_degradation")))
        if require_no_core_runtime_outliers:
            checks.append(bool(probe_checks.get("no_core_runtime_outliers")))

        return 0 if all(checks) else 1
    finally:
        await shutdown_all_managers()


async def _recent_failed_jobs_async(limit: int, lookback_hours: int, core_jobs_only: bool) -> int:
    from core.managers import mongo_manager, shutdown_all_managers
    from nodes.data_sync.services.ops_summary import get_recent_failed_job_executions

    try:
        await mongo_manager.initialize()
        summary = await get_recent_failed_job_executions(
            limit=limit,
            lookback_hours=lookback_hours,
            core_jobs_only=core_jobs_only,
        )
        print("DataSync recent failed jobs")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if summary.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _recent_ops_events_async(limit: int, lookback_hours: int, severities: list[str]) -> int:
    from core.managers import mongo_manager, shutdown_all_managers
    from nodes.data_sync.services.ops_summary import get_recent_ops_events

    try:
        await mongo_manager.initialize()
        summary = await get_recent_ops_events(
            limit=limit,
            severities=severities,
            lookback_hours=lookback_hours,
        )
        print("DataSync recent ops events")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if summary.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _core_job_runtime_summary_async(lookback_hours: int) -> int:
    from core.managers import mongo_manager, shutdown_all_managers
    from nodes.data_sync.services.ops_summary import get_core_job_runtime_summary

    try:
        await mongo_manager.initialize()
        summary = await get_core_job_runtime_summary(
            lookback_hours=lookback_hours,
        )
        print("DataSync core job runtime summary")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if summary.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _data_source_call_stats_async() -> int:
    from core.managers import data_source_manager, shutdown_all_managers

    try:
        await data_source_manager.initialize()
        summary = data_source_manager.get_call_stats_summary()
        print("DataSync data source call stats")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if summary.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _reset_data_source_call_stats_async() -> int:
    from core.managers import data_source_manager, shutdown_all_managers

    try:
        await data_source_manager.initialize()
        summary = data_source_manager.reset_call_stats()
        print("DataSync data source call stats reset")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if summary.get("success") else 1
    finally:
        await shutdown_all_managers()


async def _recent_checkpoints_async(limit: int, job_name: str | None, status: str | None) -> int:
    from core.managers import mongo_manager, shutdown_all_managers

    try:
        await mongo_manager.initialize()
        rows = await mongo_manager.list_checkpoints(
            job_name=job_name or None,
            status=status or None,
            limit=limit,
        )
        print("DataSync recent checkpoints")
        print(json.dumps({"success": True, "count": len(rows), "items": rows}, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        await shutdown_all_managers()


async def _enqueue_backfill_job_async(
    job_name: str,
    trade_date: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    priority: int = 100,
    created_by: str = "cli",
) -> int:
    from core.managers import mongo_manager, shutdown_all_managers
    from nodes.data_sync.services.backfill_queue import BackfillQueueService

    try:
        await mongo_manager.initialize()
        service = BackfillQueueService(mongo_manager)
        job = await service.enqueue(
            dataset=job_name,
            target_trade_date=trade_date,
            start_date=start_date or None,
            end_date=end_date or None,
            priority=priority,
            created_by=created_by,
        )
        print("DataSync backfill job enqueued")
        print(json.dumps({"success": True, "job": job}, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        await shutdown_all_managers()


async def _recent_backfill_jobs_async(limit: int, job_name: str | None, status: str | None) -> int:
    from core.managers import mongo_manager, shutdown_all_managers
    from nodes.data_sync.services.backfill_queue import BackfillQueueService

    try:
        await mongo_manager.initialize()
        service = BackfillQueueService(mongo_manager)
        rows = await service.list_jobs(
            dataset=job_name or None,
            status=status or None,
            limit=limit,
        )
        print("DataSync recent backfill jobs")
        print(json.dumps({"success": True, "count": len(rows), "items": rows}, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        await shutdown_all_managers()


async def _run_backfill_queue_once_async(rpc_port: int, force: bool) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()

    try:
        await redis_manager.initialize()
        await mongo_manager.initialize()
        await data_source_manager.initialize()
        await llm_manager.initialize()
        result = await node._run_backfill_queue_worker(
            trigger="cli_backfill_queue",
            force_window=force,
        )
        print("DataSync backfill queue run once")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    finally:
        await shutdown_all_managers()


def main() -> int:
    args = _create_parser().parse_args()
    runtime = _prepare_runtime(args.env_file)
    _print_runtime_summary(runtime)

    if args.audit_self_contained:
        return _audit_self_contained(runtime, args.config_dir)

    _load_app_config(args.config_dir)

    if args.health:
        return asyncio.run(_health_async())

    if args.ready:
        return asyncio.run(_ready_async(args.failure_lookback_hours))

    if args.check_core_integrity:
        return asyncio.run(_check_core_integrity_async(args.integrity_days, args.require_recent_window_ready))

    if args.recover_latest_core_gaps:
        return asyncio.run(_recover_latest_core_gaps_async(args.rpc_port))

    if args.recover_recent_core_gaps:
        return asyncio.run(_recover_recent_core_gaps_async(args.rpc_port, args.integrity_days))

    if args.safe_recover_core_window:
        return asyncio.run(_safe_recover_core_window_async(args.rpc_port, args.integrity_days))

    if args.recover_job_trade_date:
        job_name = str(args.job_name or "").strip()
        trade_date = str(args.trade_date or "").strip()
        if not job_name or not trade_date:
            print("--recover-job-trade-date requires --job-name and --trade-date")
            return 1
        return asyncio.run(_recover_job_trade_date_async(args.rpc_port, job_name, trade_date, args.force))

    if args.enqueue_backfill_job:
        job_name = str(args.job_name or "").strip()
        trade_date = str(args.trade_date or "").strip()
        if not job_name or not trade_date:
            print("--enqueue-backfill-job requires --job-name and --trade-date")
            return 1
        return asyncio.run(
            _enqueue_backfill_job_async(
                job_name,
                trade_date,
                start_date=args.start_date,
                end_date=args.end_date,
                priority=args.priority,
                created_by=args.created_by,
            )
        )

    if args.run_backfill_queue_once:
        return asyncio.run(_run_backfill_queue_once_async(args.rpc_port, args.force))

    if args.check_sync_targets:
        return asyncio.run(_check_sync_targets_async())

    if args.ensure_indexes:
        collections = [
            item.strip()
            for item in str(args.index_collections or "").split(",")
            if item.strip()
        ]
        return asyncio.run(_ensure_indexes_async(args.index_scope, collections))

    if args.ops_summary:
        return asyncio.run(
            _ops_summary_async(
                args.integrity_days,
                args.job_log_limit,
                args.require_recent_window_ready,
                args.require_no_recent_failures,
                args.require_no_warning_events,
                args.require_no_data_source_degradation,
                args.require_no_core_data_source_degradation,
                args.require_no_core_runtime_outliers,
                args.failure_lookback_hours,
                args.event_lookback_hours,
                args.runtime_lookback_hours,
            )
        )

    if args.recent_failed_jobs:
        return asyncio.run(
            _recent_failed_jobs_async(
                args.job_log_limit,
                args.failure_lookback_hours,
                args.core_jobs_only,
            )
        )

    if args.recent_ops_events:
        severities = [part.strip() for part in str(args.event_severities or "").split(",") if part.strip()]
        return asyncio.run(_recent_ops_events_async(args.job_log_limit, args.event_lookback_hours, severities))

    if args.recent_checkpoints:
        return asyncio.run(_recent_checkpoints_async(args.job_log_limit, args.job_name, args.checkpoint_status))

    if args.recent_backfill_jobs:
        return asyncio.run(_recent_backfill_jobs_async(args.job_log_limit, args.job_name, args.backfill_status))

    if args.core_job_runtime_summary:
        return asyncio.run(_core_job_runtime_summary_async(args.runtime_lookback_hours))

    if args.data_source_call_stats:
        return asyncio.run(_data_source_call_stats_async())

    if args.data_capabilities:
        return _print_data_capabilities(args.capabilities_profile, args.capabilities_format)

    if args.write_data_capabilities:
        return _write_data_capabilities(
            args.write_data_capabilities,
            args.capabilities_profile,
            args.capabilities_format,
        )

    if args.reset_data_source_call_stats:
        return asyncio.run(_reset_data_source_call_stats_async())

    if args.check:
        return _check_setup(args.rpc_port)

    if args.check_startup:
        return asyncio.run(_check_startup_async(args.rpc_port))

    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=args.rpc_port or settings.rpc.data_sync_port)
    try:
        asyncio.run(node.main())
    except KeyboardInterrupt:
        print("\nShutdown by user")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
