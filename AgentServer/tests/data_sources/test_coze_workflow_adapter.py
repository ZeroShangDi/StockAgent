import pytest

from src.data_sources.coze_workflow_adapter import CozeWorkflowAdapter


class DummyCozeWorkflowAdapter(CozeWorkflowAdapter):
    def __init__(self, payloads: dict[str, object]):
        super().__init__(api_token="token", workflow_id="workflow")
        self._initialized = True
        self._payloads = payloads

    async def is_available(self) -> bool:
        return True

    async def _run_plugin(self, plugin: str, params=None):  # type: ignore[override]
        return self._payloads[plugin]


@pytest.mark.asyncio
async def test_parse_stock_basic_from_realistic_payload() -> None:
    adapter = DummyCozeWorkflowAdapter(
        {
            "info_all_code": {
                "concept_code_list": [],
                "data": None,
                "fund_code_list": [],
                "stock_code_list": [
                    {
                        "exchange": "SZ",
                        "list_date": 703123200000,
                        "short_name": "全新好",
                        "stock_code": "000007",
                    }
                ],
            }
        }
    )

    records = await adapter.get_stock_basic()
    assert records == [
        {
            "ts_code": "000007.SZ",
            "symbol": "000007",
            "name": "全新好",
            "area": "",
            "industry": "",
            "market": "SZ",
            "list_date": "19920413",
            "list_status": "L",
        }
    ]


@pytest.mark.asyncio
async def test_get_daily_maps_real_workflow_fields() -> None:
    adapter = DummyCozeWorkflowAdapter(
        {
            "stock_k": {
                "data": [
                    {
                        "amount": 1908333958.72,
                        "change": 0.08,
                        "change_pct": 0.7,
                        "close": 11.46,
                        "high": 11.46,
                        "low": 11.32,
                        "open": 11.36,
                        "pre_close": 11.38,
                        "stock_code": "000001",
                        "trade_date": "2026-04-28",
                        "trade_time": "2026-04-28 00:00:00",
                        "turnover_ratio": 0.86,
                        "volume": 167425900,
                    }
                ]
            }
        }
    )

    records = await adapter.get_daily(
        ts_code="000001.SZ",
        start_date="20260428",
        end_date="20260428",
    )

    assert records == [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260428",
            "open": 11.36,
            "high": 11.46,
            "low": 11.32,
            "close": 11.46,
            "pre_close": 11.38,
            "change": 0.08,
            "pct_chg": 0.7,
            "vol": 167425900.0,
            "amount": 1908333958.72,
        }
    ]


@pytest.mark.asyncio
async def test_get_realtime_quotes_maps_real_workflow_fields() -> None:
    adapter = DummyCozeWorkflowAdapter(
        {
            "stock_current": {
                "data": [
                    {
                        "amount": 1312820000,
                        "change": "-0.03",
                        "change_pct": "-0.26",
                        "price": "11.49",
                        "short_name": "平安银行",
                        "stock_code": "000001",
                        "volume": 113924100,
                    }
                ]
            }
        }
    )

    quotes = await adapter.get_realtime_quotes(["000001.SZ"])

    assert quotes["000001.SZ"]["ts_code"] == "000001.SZ"
    assert quotes["000001.SZ"]["name"] == "平安银行"
    assert quotes["000001.SZ"]["price"] == 11.49
    assert quotes["000001.SZ"]["close"] == 11.49
    assert quotes["000001.SZ"]["pct_chg"] == -0.26


@pytest.mark.asyncio
async def test_get_daily_basic_combines_kline_shares_and_financials() -> None:
    adapter = DummyCozeWorkflowAdapter(
        {
            "stock_k": {
                "data": [
                    {
                        "close": 11.46,
                        "trade_date": "2026-04-28",
                        "trade_time": "2026-04-28 00:00:00",
                        "turnover_ratio": 0.86,
                    }
                ]
            },
            "stock_shares": {
                "data": [
                    {
                        "stock_code": "000001",
                        "total_shares": 19405918198,
                        "list_a_shares": 19405600653,
                    }
                ]
            },
            "stock_fin_data": {
                "data": [
                    {
                        "stock_code": "000001",
                        "basic_eps": 0.67,
                        "net_asset_ps": 23.91,
                        "notice_date": "2026-04-25",
                        "report_date": "2026-03-31",
                    }
                ]
            },
        }
    )

    records = await adapter.get_daily_basic(
        ts_code="000001.SZ",
        start_date="20260428",
        end_date="20260428",
    )

    assert records[0]["ts_code"] == "000001.SZ"
    assert records[0]["trade_date"] == "20260428"
    assert records[0]["turnover_rate"] == 0.86
    assert records[0]["total_share"] == 19405918198.0
    assert records[0]["float_share"] == 19405600653.0
    assert records[0]["pe"] == pytest.approx(11.46 / 0.67)
    assert records[0]["pb"] == pytest.approx(11.46 / 23.91)


@pytest.mark.asyncio
async def test_get_trade_calendar_derives_from_stock_k() -> None:
    adapter = DummyCozeWorkflowAdapter(
        {
            "stock_k": {
                "data": [
                    {"trade_date": "2026-04-28"},
                    {"trade_date": "2026-04-29"},
                    {"trade_date": "2026-04-30"},
                ]
            }
        }
    )

    dates = await adapter.get_trade_calendar("20260428", "20260430")
    assert dates == ["20260428", "20260429", "20260430"]
