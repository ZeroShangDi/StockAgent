"""
独立 DataSync 入口。

当前阶段先复用 AgentServer 内已有的 DataSyncNode 实现，
通过 sibling bootstrap 的方式把 DataSync 作为单独服务目录运行。
确认独立运行稳定后，再继续下沉/迁移具体模块。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
AGENTSERVER_DIR = REPO_ROOT / "AgentServer"
DEFAULT_ENV_FILES = (
    REPO_ROOT / ".env",
    AGENTSERVER_DIR / ".env",
    REPO_ROOT / ".env.docker",
)

if str(AGENTSERVER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTSERVER_DIR))


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
        "--env-file",
        help="explicit environment file to load before startup",
    )
    parser.add_argument(
        "--config-dir",
        help="optional YAML config directory override",
    )
    return parser


def _collect_env_files(cli_env_file: str | None) -> list[Path]:
    candidates: list[Path] = []
    if cli_env_file:
        candidates.append(Path(cli_env_file).expanduser().resolve())
    candidates.extend(DEFAULT_ENV_FILES)

    existing: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        existing.append(path)
    return existing


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


def _prepare_runtime(cli_env_file: str | None) -> dict[str, Any]:
    from dotenv import load_dotenv

    loaded_env_files = _collect_env_files(cli_env_file)
    for env_file in loaded_env_files:
        load_dotenv(env_file, override=False)

    runtime_dir = Path(os.environ.get("DATASYNC_RUNTIME_DIR", CURRENT_DIR)).expanduser().resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime_dir)

    os.environ.setdefault("NODE_TYPE", "data_sync")

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

    return {
        "runtime_dir": runtime_dir,
        "env_files": loaded_env_files,
        "log_dir": log_dir,
        "data_dir": data_dir,
        "milvus_uri": milvus_uri,
    }


def _load_app_config(config_dir: str | None) -> int:
    from src.config import config_manager

    config_count = config_manager.load(config_dir=config_dir)
    print(f"Loaded {config_count} YAML config files from {config_manager.config_dir}")
    return config_count


def _print_runtime_summary(runtime: dict[str, Any]) -> None:
    print(f"DataSync runtime dir: {runtime['runtime_dir']}")
    print(f"DataSync log dir: {runtime['log_dir']}")
    print(f"DataSync data dir: {runtime['data_dir']}")
    print(f"DataSync milvus uri: {runtime['milvus_uri']}")
    if runtime["env_files"]:
        print("Loaded env files:")
        for env_file in runtime["env_files"]:
            print(f" - {env_file}")
    else:
        print("Loaded env files: none")


def _check_setup(rpc_port: int) -> int:
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._register_jobs()
    print(f"DataSync bootstrap OK: jobs={len(node._jobs)}")
    for job in node._jobs:
        print(f" - {job.name}")
    return 0


async def _check_startup_async(rpc_port: int) -> int:
    from core.managers import data_source_manager, llm_manager, mongo_manager, redis_manager, shutdown_all_managers
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    node = DataSyncNode(rpc_port=rpc_port or settings.rpc.data_sync_port)
    node._running = True

    try:
        await node.start()
        checks = {
            "redis": await redis_manager.health_check(),
            "mongo": await mongo_manager.health_check(),
            "data_source": await data_source_manager.health_check(),
            "llm": await llm_manager.health_check(),
        }
        print("DataSync startup OK")
        print(f"DataSync RPC address: {node._rpc_address}")
        print(f"DataSync registered jobs: {len(node._jobs)}")
        for name, healthy in checks.items():
            status = "ok" if healthy else "failed"
            print(f" - {name}: {status}")
        return 0 if all(checks.values()) else 1
    finally:
        node._running = False
        await node._stop_rpc_server()
        await node.stop()
        await shutdown_all_managers()


def main() -> int:
    args = _create_parser().parse_args()
    runtime = _prepare_runtime(args.env_file)
    _load_app_config(args.config_dir)
    _print_runtime_summary(runtime)

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
