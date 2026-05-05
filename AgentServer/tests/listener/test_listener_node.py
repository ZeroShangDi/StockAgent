from unittest.mock import AsyncMock

import pytest

from core.protocols import StrategySubscription, StrategyType
from nodes.listener import node as listener_node_module
from nodes.listener.node import ListenerNode


def test_build_snapshot_accepts_quote_dict() -> None:
    node = ListenerNode(node_id="listener-test-build")

    snapshot = node._build_snapshot(
        {
            "000001.sz": {
                "ts_code": "000001.sz",
                "name": "平安银行",
                "price": 10.5,
                "pct_chg": 1.2,
            }
        }
    )

    assert snapshot.total_stocks == 1
    assert snapshot.up_count == 1
    assert "000001.SZ" in snapshot.quotes
    assert snapshot.quotes["000001.SZ"]["name"] == "平安银行"


@pytest.mark.asyncio
async def test_poll_cycle_unpacks_manager_results(monkeypatch: pytest.MonkeyPatch) -> None:
    node = ListenerNode(node_id="listener-test-poll")
    node._subscriptions = [
        StrategySubscription(
            strategy_name="涨幅预警",
            strategy_type=StrategyType.PRICE_CHANGE,
            watch_list=["000001.SZ"],
        )
    ]

    stored: dict = {}

    monkeypatch.setattr(node, "_fetch_limit_prices_if_needed", AsyncMock())
    monkeypatch.setattr(
        node,
        "_store_realtime_market_data",
        AsyncMock(side_effect=lambda index_quotes: stored.setdefault("index_quotes", index_quotes)),
    )
    monkeypatch.setattr(node, "_evaluate_strategies", AsyncMock(return_value=[]))

    monkeypatch.setattr(
        listener_node_module.data_source_manager,
        "get_realtime_index_quotes",
        AsyncMock(return_value=({"000001.SH": {"price": 3200.0}}, "fake-index")),
    )
    monkeypatch.setattr(
        listener_node_module.data_source_manager,
        "get_realtime_quotes",
        AsyncMock(
            return_value=(
                {
                    "000001.SZ": {
                        "ts_code": "000001.SZ",
                        "name": "平安银行",
                        "price": 10.5,
                        "pct_chg": 1.2,
                    }
                },
                "fake-quote",
            )
        ),
    )

    await node._poll_cycle("trace-test")

    assert node._current_snapshot is not None
    assert node._current_snapshot.total_stocks == 1
    assert stored["index_quotes"] == {"000001.SH": {"price": 3200.0}}
