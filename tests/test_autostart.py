import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import autostart  # noqa: E402
from autostart import LegacyStartup, shortcut_installed, shortcut_paths, startup_preference  # noqa: E402


class FakeLegacy:
    def __init__(self, enabled):
        self.was_enabled = enabled
        self.removed = 0

    def enabled(self):
        return self.was_enabled

    def remove(self):
        self.removed += 1
        return ["borrado"]


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2

    def __init__(self, values):
        self.values = values

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved, access):
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def DeleteValue(self, key, name):
        del self.values[name]


class PreferenceTests(unittest.TestCase):
    def test_first_time_takes_legacy_and_removes_it(self):
        config, logs = {}, []
        legacy = FakeLegacy(True)
        self.assertTrue(startup_preference(config.get, config.__setitem__, legacy, logs.append))
        self.assertEqual(config, {"auto_startup": True})
        self.assertEqual(legacy.removed, 1)
        self.assertIn("borrado", logs)

    def test_without_legacy_it_stays_off(self):
        config = {}
        self.assertFalse(startup_preference(config.get, config.__setitem__, FakeLegacy(False)))
        self.assertEqual(config, {"auto_startup": False})

    def test_saved_preference_never_touches_windows(self):
        legacy = FakeLegacy(True)
        config = {"auto_startup": False}
        self.assertFalse(startup_preference(config.get, config.__setitem__, legacy))
        self.assertEqual(legacy.removed, 0)


class ShortcutTests(unittest.TestCase):
    def test_paths_for_all_users_and_for_the_user(self):
        env = {"ProgramData": r"C:\ProgramData", "APPDATA": r"C:\Users\ana\AppData\Roaming"}
        paths = shortcut_paths(env)
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(p.endswith(os.path.join("StartUp", "ToolKit SISMED.lnk")) for p in paths))
        self.assertTrue(paths[0].startswith(r"C:\ProgramData"))

    def test_installed_if_any_exists(self):
        env = {"ProgramData": "pd", "APPDATA": "ad"}
        self.assertTrue(shortcut_installed(lambda p: p.startswith("ad"), env))
        self.assertFalse(shortcut_installed(lambda p: False, env))


class LegacyStartupTests(unittest.TestCase):
    def test_never_creates_anything(self):
        calls = []

        def run(arguments):
            calls.append(arguments)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        registry = FakeRegistry({"ToolkitOGM_Sync": '"C:\\ToolkitOGM.exe" --autorun'})
        legacy = LegacyStartup(run=run, registry=registry)
        self.assertTrue(legacy.enabled())
        messages = legacy.remove()
        self.assertIn(["schtasks", "/Delete", "/TN", "ToolkitOGM_Autorun", "/F"], calls)
        self.assertFalse(any("/Create" in c for c in calls))
        self.assertEqual(registry.values, {})
        self.assertIn("startup_legacy_run_removed=True", messages)

    def test_nothing_left_means_nothing_to_remove(self):
        calls = []

        def run(arguments):
            calls.append(arguments)
            return SimpleNamespace(returncode=1, stdout="", stderr="no existe")

        legacy = LegacyStartup(run=run, registry=FakeRegistry({}))
        self.assertFalse(legacy.enabled())
        self.assertEqual(legacy.remove(), [])
        self.assertTrue(all(c[1] == "/Query" for c in calls))

    def _task(self, user, encoding=None):
        calls = []
        xml = f'<?xml version="1.0"?><Task><Principals><Principal id="Author"><UserId>{user}</UserId>' \
              '</Principal></Principals></Task>'
        if encoding:
            xml = xml.encode(encoding).decode("latin-1")

        def run(arguments):
            calls.append(arguments)
            return SimpleNamespace(returncode=0, stdout=xml, stderr="")

        return calls, run

    def test_task_of_another_windows_user_is_left_alone(self):
        calls, run = self._task("S-1-5-21-1-2-3-1002")
        legacy = LegacyStartup(run=run, registry=FakeRegistry({}), user_ids={"S-1-5-21-1-2-3-1001", "ana"})
        self.assertFalse(legacy.enabled())
        self.assertEqual(legacy.remove(), ["startup_legacy_task_kept owner=S-1-5-21-1-2-3-1002"])
        self.assertFalse(any("/Delete" in c for c in calls))

    def test_own_task_by_sid_or_name_counts_and_is_removed(self):
        for user in ("S-1-5-21-1-2-3-1001", "LAPTOP\\Ana", "ana"):
            calls, run = self._task(user)
            legacy = LegacyStartup(run=run, registry=FakeRegistry({}),
                                   user_ids={"s-1-5-21-1-2-3-1001", "laptop\\ana", "ana"})
            self.assertTrue(legacy.enabled(), user)
            legacy.remove()
            self.assertIn(["schtasks", "/Delete", "/TN", "ToolkitOGM_Autorun", "/F"], calls)

    def test_reads_the_owner_from_utf16_output(self):
        _, run = self._task("S-1-5-21-9", encoding="utf-16-le")
        self.assertEqual(LegacyStartup(run=run, registry=FakeRegistry({}), user_ids=set()).task_owner(), "S-1-5-21-9")

    def test_main_no_longer_registers_itself(self):
        source = (TOOLKIT_DIR / "main.py").read_text(encoding="utf-8")
        for forbidden in ("/Create", "SetValueEx", "CurrentVersion\\Run"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("/Create", (TOOLKIT_DIR / "autostart.py").read_text(encoding="utf-8"))
        self.assertEqual(autostart.SHORTCUT_NAME, "ToolKit SISMED.lnk")

    def test_installer_puts_the_startup_shortcut(self):
        iss = (ROOT / "packaging" / "windows" / "ToolkitOGM.iss").read_text(encoding="utf-8")
        self.assertIn('Name: "{autostartup}\\{#MyAppName}"', iss)
        self.assertIn('Parameters: "--autorun"', iss)
        self.assertIn('#define MyAppName "ToolKit SISMED"', iss)


if __name__ == "__main__":
    unittest.main()
