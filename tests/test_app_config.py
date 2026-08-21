import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from tools import app_config


class AppConfigPersistenceTests(unittest.TestCase):
    def _paths(self, directory: Path):
        return patch.multiple(
            app_config,
            _CONFIG_DIR=str(directory),
            _CONFIG_FILE=str(directory / "config.json"),
            _CONFIG_BACKUP_FILE=str(directory / "config.bak"),
            _CONFIG_LOG_FILE=str(directory / "config.log"),
        )

    def test_boolean_update_preferences_persist(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(Path(temp_dir)):
            app_config.set("update_auto_check", False)
            app_config.set("update_auto_download", True)

            self.assertIs(app_config.get("update_auto_check"), False)
            self.assertIs(app_config.get("update_auto_download"), True)

    def test_concurrent_writes_do_not_lose_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(Path(temp_dir)):
            original_load = app_config._load

            def slow_load():
                data = original_load()
                time.sleep(0.005)
                return data

            errors = []
            start = threading.Barrier(16)

            def write_value(index: int):
                try:
                    start.wait(timeout=2)
                    app_config.set(f"concurrent_{index}", index)
                except Exception as exc:
                    errors.append(exc)

            with patch.object(app_config, "_load", side_effect=slow_load):
                workers = [
                    threading.Thread(target=write_value, args=(index,))
                    for index in range(16)
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=5)

            self.assertEqual(errors, [])
            with open(Path(temp_dir) / "config.json", "r", encoding="utf-8") as source:
                saved = json.load(source)
            for index in range(16):
                self.assertEqual(saved[f"concurrent_{index}"], index)


if __name__ == "__main__":
    unittest.main()
