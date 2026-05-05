"""Coze 工作流数据源联调脚本。"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import data_source_manager


def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def _check(name: str, ok: bool, detail: str, *, data: Any = None) -> Dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
        "data": data,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="测试 Coze 工作流数据源适配器")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    await data_source_manager.initialize()
    adapter = data_source_manager.get_adapter("coze")

    checks: List[Dict[str, Any]] = []
    if adapter is None:
        checks.append(_check("adapter", False, "未检测到 Coze 适配器，请检查 COZE_* 配置"))
    else:
        start_date = "20260428"
        end_date = "20260430"

        try:
            stock_basic = await adapter.get_stock_basic(ts_code="000001.SZ")
            checks.append(_check(
                "stock_basic_single",
                bool(stock_basic),
                f"单股基础信息返回 {len(stock_basic or [])} 条",
                data=stock_basic[0] if stock_basic else None,
            ))
        except Exception as exc:
            checks.append(_check("stock_basic_single", False, f"单股基础信息失败：{exc}"))

        try:
            stock_list = await adapter.get_stock_basic()
            checks.append(_check(
                "stock_basic_full",
                bool(stock_list),
                f"全量股票列表返回 {len(stock_list or [])} 条",
                data={"count": len(stock_list or [])},
            ))
        except Exception as exc:
            checks.append(_check("stock_basic_full", False, f"全量股票列表失败：{exc}"))

        try:
            daily = await adapter.get_daily(ts_code="000001.SZ", start_date=start_date, end_date=end_date)
            checks.append(_check(
                "daily",
                bool(daily),
                f"日线返回 {len(daily or [])} 条",
                data=daily[:1] if daily else None,
            ))
        except Exception as exc:
            checks.append(_check("daily", False, f"日线失败：{exc}"))

        try:
            realtime = await adapter.get_realtime_quotes(ts_codes=["000001.SZ", "600000.SH"])
            checks.append(_check(
                "realtime_quotes",
                bool(realtime),
                f"实时行情返回 {len(realtime or {})} 条",
                data=realtime,
            ))
        except Exception as exc:
            checks.append(_check("realtime_quotes", False, f"实时行情失败：{exc}"))

        try:
            daily_basic = await adapter.get_daily_basic(ts_code="000001.SZ", start_date=start_date, end_date=end_date)
            checks.append(_check(
                "daily_basic",
                bool(daily_basic),
                f"daily_basic 返回 {len(daily_basic or [])} 条",
                data=daily_basic[:1] if daily_basic else None,
            ))
        except Exception as exc:
            checks.append(_check("daily_basic", False, f"daily_basic 失败：{exc}"))

        try:
            financial = await adapter.get_financial_indicator(ts_code="000001.SZ", limit=2)
            checks.append(_check(
                "financial_indicator",
                bool(financial),
                f"财务指标返回 {len(financial or [])} 条",
                data=financial[:1] if financial else None,
            ))
        except Exception as exc:
            checks.append(_check("financial_indicator", False, f"财务指标失败：{exc}"))

        try:
            calendar = await adapter.get_trade_calendar(start_date=start_date, end_date=end_date)
            checks.append(_check(
                "trade_calendar",
                bool(calendar),
                f"交易日历返回 {len(calendar or [])} 天",
                data=calendar,
            ))
        except Exception as exc:
            checks.append(_check("trade_calendar", False, f"交易日历失败：{exc}"))

        try:
            index_quotes = await adapter.get_realtime_index_quotes()
            checks.append(_check(
                "realtime_index_quotes",
                bool(index_quotes),
                f"指数实时行情返回 {len(index_quotes or {})} 条",
                data=index_quotes,
            ))
        except Exception as exc:
            checks.append(_check("realtime_index_quotes", False, f"指数实时行情失败：{exc}"))

        try:
            index_daily = await adapter.get_index_daily(ts_code="000001.SH", start_date=end_date, end_date=end_date)
            checks.append(_check(
                "index_daily",
                bool(index_daily),
                "指数历史日线返回空，说明当前 Coze `index_k` 仍不可用" if not index_daily else f"指数历史日线返回 {len(index_daily)} 条",
                data=index_daily[:1] if index_daily else None,
            ))
        except Exception as exc:
            checks.append(_check("index_daily", False, f"指数历史日线失败：{exc}"))

    await data_source_manager.shutdown()

    if args.json:
        print(json.dumps({"checks": checks}, ensure_ascii=False, indent=2, default=str))
        return

    _print_section("Coze 数据源联调结果")
    for item in checks:
        prefix = "PASS" if item["ok"] else "FAIL"
        print(f"[{prefix}] {item['name']}: {item['detail']}")
        if item.get("data") is not None:
            preview = json.dumps(item["data"], ensure_ascii=False, default=str)
            print(f"       preview={preview[:240]}")

    passed = sum(1 for item in checks if item["ok"])
    print(f"\nSummary: {passed}/{len(checks)} checks passed")


if __name__ == "__main__":
    asyncio.run(main())
