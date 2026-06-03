"""机器可读 DataSync 数据能力目录生成器。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "1.0"


def build_data_capabilities(*, profile: str | None = None) -> dict[str, Any]:
    """构建静态能力目录，不初始化外部资源。"""
    from core.settings import settings
    from nodes.data_sync.node import DataSyncNode

    data_sync_settings = settings.data_sync
    original_profile = data_sync_settings.profile

    try:
        if profile:
            data_sync_settings.profile = profile

        node = DataSyncNode(node_id="data-sync-capability-builder", rpc_port=0)
        manifest = node.get_capability_manifest()
    finally:
        data_sync_settings.profile = original_profile

    manifest.update(
        {
            "schema_version": SCHEMA_VERSION,
            "catalog_type": "datasync_capabilities",
            "generated_at": datetime.now(UTC).isoformat(),
            "generated_by": "DataSync/src/datasync_capabilities.py",
        }
    )
    return manifest


def write_data_capabilities(
    output_path: Path,
    *,
    profile: str | None = None,
    output_format: str = "yaml",
) -> dict[str, Any]:
    """写入能力目录文件，并返回生成的目录内容。"""
    catalog = build_data_capabilities(profile=profile)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_format = output_format.lower()
    if normalized_format == "json":
        output_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    elif normalized_format in {"yaml", "yml"}:
        output_path.write_text(
            yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    else:
        raise ValueError(f"Unsupported capability catalog format: {output_format}")

    return catalog
