from pathlib import Path
import json
import sys
import tempfile
import unittest

import yaml


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from src.datasync_capabilities import build_data_capabilities, write_data_capabilities


class DataSyncCapabilitiesCatalogTest(unittest.TestCase):
    def test_build_catalog_contains_source_priority(self) -> None:
        catalog = build_data_capabilities(profile="conservative")
        capability_by_name = {
            item["name"]: item
            for item in catalog["capabilities"]
        }

        self.assertEqual(catalog["catalog_type"], "datasync_capabilities")
        self.assertEqual(catalog["schema_version"], "1.0")
        self.assertEqual(catalog["profile"], "conservative")
        self.assertEqual(catalog["count"], 12)
        self.assertEqual(
            capability_by_name["stock_daily"]["source_chains"]["get_daily.full_market"],
            ["tushare", "baostock", "akshare", "coze"],
        )
        self.assertEqual(
            capability_by_name["market_weather"]["source_chains"]["coze_market_indicator_workflow"],
            ["coze"],
        )
        self.assertEqual(capability_by_name["stock_daily"]["recoverability"]["mode"], "full")
        self.assertEqual(
            capability_by_name["market_weather"]["recoverability"]["can_recover_trade_date"],
            True,
        )
        self.assertNotIn("last_result", capability_by_name["stock_daily"])

    def test_write_catalog_yaml_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_path = Path(temp_dir) / "datasync_capabilities.yaml"
            json_path = Path(temp_dir) / "datasync_capabilities.json"

            yaml_catalog = write_data_capabilities(
                yaml_path,
                profile="conservative",
                output_format="yaml",
            )
            json_catalog = write_data_capabilities(
                json_path,
                profile="conservative",
                output_format="json",
            )

            loaded_yaml = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            loaded_json = json.loads(json_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded_yaml["count"], yaml_catalog["count"])
            self.assertEqual(loaded_json["count"], json_catalog["count"])
            self.assertIn("capabilities", loaded_yaml)
            self.assertIn("source_chain_catalog", loaded_json)

    def test_checked_in_catalog_matches_current_conservative_capabilities(self) -> None:
        catalog_path = DATASYNC_ROOT / "config" / "datasync_capabilities.yaml"
        checked_in_catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        generated_catalog = build_data_capabilities(profile="conservative")

        checked_names = [item["name"] for item in checked_in_catalog["capabilities"]]
        generated_names = [item["name"] for item in generated_catalog["capabilities"]]

        self.assertEqual(checked_in_catalog["catalog_type"], "datasync_capabilities")
        self.assertEqual(checked_in_catalog["schema_version"], generated_catalog["schema_version"])
        self.assertEqual(checked_names, generated_names)
        self.assertEqual(
            checked_in_catalog["source_chain_catalog"],
            generated_catalog["source_chain_catalog"],
        )


if __name__ == "__main__":
    unittest.main()
