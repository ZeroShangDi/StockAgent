from nodes.web.api.stock import (
    _DEFAULT_STOCK_REPAIR_START_DATE,
    _build_stock_repair_plan,
    _merge_stock_basic_records,
    _normalize_compact_date,
)


def test_normalize_compact_date_accepts_multiple_date_formats() -> None:
    assert _normalize_compact_date("1991-04-03") == "19910403"
    assert _normalize_compact_date("19910403") == "19910403"
    assert _normalize_compact_date(" 1991/04/03 ") == "19910403"


def test_merge_stock_basic_records_keeps_existing_values_when_new_record_is_sparse() -> None:
    merged = _merge_stock_basic_records(
        {"ts_code": "603399.SH", "name": "吉翔股份", "industry": "有色金属", "list_date": ""},
        {"ts_code": "603399.SH", "name": "", "market": "主板"},
    )

    assert merged == {
        "ts_code": "603399.SH",
        "name": "吉翔股份",
        "industry": "有色金属",
        "market": "主板",
    }


def test_build_stock_repair_plan_prefers_resolved_list_date() -> None:
    plan = _build_stock_repair_plan(
        list_date="2016-08-09",
        list_date_source="tushare",
        existing_daily_start="20260331",
    )

    assert plan["mode"] == "full_history_repair"
    assert plan["mode_label"] == "完整补数"
    assert plan["start_date"] == "20160809"
    assert plan["start_date_reason"] == "resolved_list_date"
    assert plan["list_date_source"] == "tushare"
    assert plan["planned_to_extend_earlier"] is True


def test_build_stock_repair_plan_uses_default_history_start_when_list_date_missing() -> None:
    plan = _build_stock_repair_plan(
        list_date="",
        list_date_source="default_history_start",
        existing_daily_start="20260331",
    )

    assert plan["mode"] == "full_history_repair"
    assert plan["start_date"] == _DEFAULT_STOCK_REPAIR_START_DATE
    assert plan["start_date_reason"] == "fallback_default_history_start"
    assert plan["planned_to_extend_earlier"] is True
    assert "默认历史起点" in plan["start_date_reason_label"]
