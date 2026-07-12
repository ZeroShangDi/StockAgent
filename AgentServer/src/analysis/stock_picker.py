"""
一句话选股服务。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from core.managers import mongo_manager
from core.settings import settings

from .coze_workflow_client import CozeWorkflowClient


class OneLineStockPickerService:
    RUN_COLLECTION = "stock_picker_runs"

    def __init__(
        self,
        workflow_id: Optional[str] = None,
        client: Optional[CozeWorkflowClient] = None,
    ) -> None:
        self._workflow_id = workflow_id or settings.coze.stock_picker_workflow_id
        self._client = client or CozeWorkflowClient()

    @staticmethod
    def _normalize_market(code: str, market: Any, market_code: Any) -> str:
        market_text = str(market or "").strip().upper()
        if market_text in {"SH", "SZ", "BJ"}:
            return market_text

        market_code_text = str(market_code or "").strip()
        if market_code_text == "1":
            return "SH"
        if market_code_text == "0":
            return "SZ"
        if market_code_text == "2":
            return "BJ"

        if code.startswith(("600", "601", "603", "605", "688", "900")):
            return "SH"
        if code.startswith(("000", "001", "002", "003", "200", "300")):
            return "SZ"
        if code.startswith(("430", "440", "830", "831", "832", "833", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "920")):
            return "BJ"
        return ""

    @classmethod
    def _build_candidate_meta(cls, row: Dict[str, Any]) -> Dict[str, str]:
        raw_code = str(
            row.get("代码")
            or row.get("code")
            or row.get("股票代码")
            or row.get("ts_code")
            or ""
        ).strip().upper()
        name = str(row.get("名称") or row.get("name") or row.get("股票名称") or "").strip()

        if "." in raw_code:
            code, market = raw_code.split(".", 1)
            market = market.upper()
            ts_code = f"{code}.{market}"
        else:
            market = cls._normalize_market(raw_code, row.get("市场简称") or row.get("market"), row.get("市场码"))
            ts_code = f"{raw_code}.{market}" if raw_code and market else ""
            code = raw_code

        return {
            "code": code,
            "ts_code": ts_code,
            "name": name,
            "market": market,
        }

    @staticmethod
    def _infer_ts_code(code: str) -> str:
        """从纯数字 code 推断 ts_code（A 股规则）。"""
        code = str(code or "").strip()
        if not code:
            return ""
        if code.startswith(("60", "68")):
            return f"{code}.SH"
        if code.startswith(("00", "30")):
            return f"{code}.SZ"
        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        return code

    def _parse_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        decoded = self._client.decode_json_like(payload.get("data"))
        if not isinstance(decoded, dict):
            raise RuntimeError("一句话选股返回格式异常")
        # 新格式：data.message 直接包含股票列表
        message = decoded.get("message")
        if isinstance(message, list):
            return {"data_list": message, "query_condition": str(decoded.get("input") or ""), "headers": list(message[0].keys()) if message else []}
        # 旧格式兼容：data.result.data_list
        result = self._client.decode_json_like(decoded.get("result"))
        if not isinstance(result, dict):
            raise RuntimeError("一句话选股 result 为空")
        return result

    def _build_response(self, *, run_id: str, input_text: str, result: Dict[str, Any]) -> Dict[str, Any]:
        raw_rows = result.get("data_list") or []
        headers = result.get("headers") or []
        rows: List[Dict[str, Any]] = []
        code_list: List[str] = []
        ts_code_list: List[str] = []

        for idx, row in enumerate(raw_rows, 1):
            if not isinstance(row, dict):
                continue
            meta = self._build_candidate_meta(row)
            # 如果 meta 中缺少 ts_code，从 code 推断
            if not meta.get("ts_code") and meta.get("code"):
                meta["ts_code"] = self._infer_ts_code(meta["code"])
            elif not meta.get("ts_code"):
                raw_code = str(row.get("code") or row.get("股票代码") or "")
                if raw_code:
                    meta["ts_code"] = self._infer_ts_code(raw_code)
            enriched = dict(row)
            enriched["__meta"] = meta
            enriched["__row_id"] = idx
            rows.append(enriched)

            if meta["code"]:
                code_list.append(meta["code"])
            if meta["ts_code"]:
                ts_code_list.append(meta["ts_code"])

        return {
            "run_id": run_id,
            "input": input_text,
            "query_condition": result.get("query_condition") or input_text,
            "headers": headers,
            "data_list": rows,
            "statistics": result.get("statistics") or {},
            "code_list": code_list,
            "ts_code_list": ts_code_list,
            "total": len(rows),
        }

    async def query(self, input_text: str, user_id: str) -> Dict[str, Any]:
        if not self._workflow_id:
            raise RuntimeError("COZE_STOCK_PICKER_WORKFLOW_ID 未配置")

        payload = await self._client.run(self._workflow_id, {"input": input_text})
        result = self._parse_result(payload)
        run_id = uuid.uuid4().hex
        response = self._build_response(run_id=run_id, input_text=input_text, result=result)

        await mongo_manager.update_one(
            self.RUN_COLLECTION,
            {"run_id": run_id},
            {
                "$set": {
                    "run_id": run_id,
                    "user_id": user_id,
                    "input": input_text,
                    "query_condition": response["query_condition"],
                    "headers": response["headers"],
                    "statistics": response["statistics"],
                    "code_list": response["code_list"],
                    "ts_code_list": response["ts_code_list"],
                    "data_list": response["data_list"],
                    "total": response["total"],
                    "raw_payload": payload,
                    "created_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return response


stock_picker_service = OneLineStockPickerService()

