"""
Coze 工作流客户端。

用于调用与股票插件无关的独立 Coze 工作流，并统一处理 JSON 字符串嵌套返回。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from core.settings import settings


class CozeWorkflowClient:
    """轻量级 Coze Workflow HTTP 客户端。"""

    def __init__(
        self,
        api_token: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        config = settings.coze
        self._api_token = api_token or config.api_token.get_secret_value()
        self._api_base = (api_base or config.api_base).rstrip("/")
        self._timeout = timeout or config.timeout

    async def run(self, workflow_id: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._api_token:
            raise RuntimeError("COZE_API_TOKEN 未配置")
        if not workflow_id:
            raise RuntimeError("workflow_id 未配置")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            },
        ) as client:
            response = await client.post(
                f"{self._api_base}/v1/workflow/run",
                json={
                    "workflow_id": workflow_id,
                    "parameters": parameters or {},
                },
            )
            response.raise_for_status()
            payload = response.json()

        code = int(payload.get("code", 0) or 0)
        if code > 0:
            msg = payload.get("msg") or payload.get("error_message") or "未知错误"
            raise RuntimeError(f"Coze workflow 调用失败: code={code}, msg={msg}")
        return payload

    @classmethod
    def decode_json_like(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return cls.decode_json_like(json.loads(stripped))
                except json.JSONDecodeError:
                    return value
            return value
        if isinstance(value, list):
            return [cls.decode_json_like(item) for item in value]
        if isinstance(value, dict):
            return {key: cls.decode_json_like(item) for key, item in value.items()}
        return value
