from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_datasync_service(compose_path: str) -> dict:
    data = yaml.safe_load((REPO_ROOT / compose_path).read_text(encoding="utf-8"))
    return data["services"]["data-sync"]


def _default_value(value: object) -> str:
    text = str(value)
    if text.startswith("${") and ":-" in text and text.endswith("}"):
        return text.split(":-", 1)[1].removesuffix("}")
    return text


class DataSyncDockerComposeSafetyTest(unittest.TestCase):
    def test_root_compose_data_sync_keeps_4c8g_safe_defaults(self) -> None:
        for compose_path in ("docker-compose.yml", "docker-compose.full.yml"):
            with self.subTest(compose_path=compose_path):
                service = _load_datasync_service(compose_path)
                env = service["environment"]
                limits = service["deploy"]["resources"]["limits"]

                self.assertEqual(_default_value(env["SYNC_PROFILE"]), "conservative")
                self.assertEqual(_default_value(env["SYNC_RUN_INITIAL_SYNC"]), "false")
                self.assertEqual(_default_value(env["SYNC_MAX_RUNNING_JOBS"]), "1")
                self.assertEqual(_default_value(env["SYNC_MAX_PARALLEL_COLLECT_CONCURRENCY"]), "2")
                self.assertEqual(_default_value(env["SYNC_PREVENT_INITIAL_HISTORY_SYNC"]), "true")
                self.assertEqual(_default_value(env["SYNC_BACKFILL_JOBS_PER_ROUND"]), "2")
                self.assertEqual(_default_value(env["SYNC_BACKFILL_MAX_JOBS_PER_NIGHT"]), "24")
                self.assertEqual(_default_value(env["SYNC_BACKFILL_MAX_EXTERNAL_REQUESTS_PER_NIGHT"]), "300")
                self.assertEqual(_default_value(env["SYNC_HOT_NEWS_ENABLED"]), "false")
                self.assertEqual(_default_value(env["SYNC_MARKET_WEATHER_MAX_CONCURRENT"]), "2")
                self.assertEqual(_default_value(limits["cpus"]), "0.75")
                self.assertEqual(_default_value(limits["memory"]), "512M")

    def test_standalone_compose_disables_shared_env_fallback_and_has_probe(self) -> None:
        service = _load_datasync_service("DataSync/docker-compose.yml")
        env = service["environment"]
        healthcheck = service.get("healthcheck") or {}

        self.assertEqual(env["DATASYNC_ALLOW_SHARED_ENV_FALLBACK"], "0")
        self.assertEqual(_default_value(env["SYNC_PROFILE"]), "conservative")
        self.assertEqual(_default_value(env["SYNC_RUN_INITIAL_SYNC"]), "false")
        self.assertEqual(_default_value(env["SYNC_MAX_RUNNING_JOBS"]), "1")
        self.assertEqual(_default_value(env["SYNC_HOT_NEWS_ENABLED"]), "false")
        self.assertIn("--health", healthcheck.get("test", []))


if __name__ == "__main__":
    unittest.main()
