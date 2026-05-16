from core.managers.notification_manager import NotificationManager
from core.protocols import StrategyAlert


def build_alert() -> StrategyAlert:
    return StrategyAlert(
        subscription_id="sub-1",
        strategy_id="strategy-1",
        strategy_name="涨停打开",
        ts_code="600000.SH",
        stock_name="浦发银行",
        trigger_price=8.2,
        trigger_reason="涨停打开，前价格 8.30，当前 8.20",
        extra_data={"limit_type": "up", "up_limit": 8.3},
    )


def test_preview_alert_contains_core_fields() -> None:
    manager = NotificationManager()

    preview = manager.preview_alert(build_alert())

    assert "涨停打开提醒" in preview
    assert "浦发银行 (600000.SH)" in preview
    assert "当前价格: 8.20" in preview


def test_prepare_text_content_prefixes_dingtalk_keyword() -> None:
    manager = NotificationManager()

    content = manager._prepare_text_content(
        provider="dingtalk",
        content="测试消息",
        keyword="小财",
    )

    assert content.startswith("小财\n")
    assert content.endswith("测试消息")


async def test_send_alert_dry_run_succeeds() -> None:
    manager = NotificationManager()

    success = await manager.send_alert(build_alert(), dry_run=True)

    assert success is True
