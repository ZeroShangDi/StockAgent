from pathlib import Path
import logging
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from common.logger import build_log_extra, log_event, sanitize_log_value


class StructuredLoggingTest(unittest.TestCase):
    def test_sanitize_log_value_truncates_long_strings_and_lists(self) -> None:
        value = {
            "payload": "x" * 20,
            "items": [{"idx": idx, "raw": "y" * 20} for idx in range(4)],
        }

        compact = sanitize_log_value(value, max_value_chars=8, max_items=2, max_depth=2)

        self.assertIn("<truncated:20>", compact["payload"])
        self.assertEqual(len(compact["items"]), 3)
        self.assertEqual(compact["items"][-1]["_truncated_items"], 2)

    def test_log_event_attaches_bounded_extra_data(self) -> None:
        records = []

        class CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.getLogger("test.structured_logging")
        original_handlers = list(logger.handlers)
        original_propagate = logger.propagate
        original_level = logger.level
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.addHandler(CaptureHandler())

        try:
            log_event(
                logger,
                logging.INFO,
                "datasync_test_event",
                job="stock_daily",
                source="tushare",
                raw_response="x" * 2000,
            )
        finally:
            logger.handlers = original_handlers
            logger.propagate = original_propagate
            logger.setLevel(original_level)

        self.assertEqual(len(records), 1)
        extra = records[0].extra_data
        self.assertEqual(extra["event"], "datasync_test_event")
        self.assertEqual(extra["job"], "stock_daily")
        self.assertEqual(extra["source"], "tushare")
        self.assertIn("<truncated:2000>", extra["raw_response"])

    def test_build_log_extra_omits_none_values(self) -> None:
        extra = build_log_extra(job="stock_daily", source=None)

        self.assertEqual(extra["extra_data"], {"job": "stock_daily"})


if __name__ == "__main__":
    unittest.main()
