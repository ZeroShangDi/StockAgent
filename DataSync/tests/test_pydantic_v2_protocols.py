import time
import unittest

from common.enums import NodeType
from core.protocols import NodeInfo, StockAnalysisState
from src.collector.types import NewsItem, NewsSource


class PydanticV2ProtocolTest(unittest.TestCase):
    def test_protocol_models_allow_extra_fields_with_config_dict(self) -> None:
        state = StockAnalysisState(
            ts_code="000001.SZ",
            task_id="task-1",
            custom_payload={"source": "unit-test"},
        )
        item = NewsItem(
            title="测试新闻",
            source=NewsSource.CLS,
            custom_field="extra",
        )

        self.assertEqual(state.custom_payload, {"source": "unit-test"})
        self.assertEqual(item.custom_field, "extra")

    def test_datetime_default_factory_is_evaluated_per_instance(self) -> None:
        first = NodeInfo(node_id="node-1", node_type=NodeType.DATA_SYNC, host="127.0.0.1", port=9001)
        time.sleep(0.001)
        second = NodeInfo(node_id="node-2", node_type=NodeType.DATA_SYNC, host="127.0.0.1", port=9002)

        self.assertGreater(second.last_heartbeat, first.last_heartbeat)
        self.assertIsNotNone(first.last_heartbeat.tzinfo)
        self.assertIsNotNone(second.last_heartbeat.tzinfo)


if __name__ == "__main__":
    unittest.main()
