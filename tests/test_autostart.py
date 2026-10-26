import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_DIR = ROOT / "toolskit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import autostart  # noqa: E402
from autostart import LegacyStartup, shortcut_installed, shortcut_paths, startup_preference  # noqa: E402


class FakeLegacy:
    def __init__(self, enabled):
        self.was_enabled = enabled

    def enabled(self):
        return self.was_enabled


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2

    def __init__(self, values):
        self.values = values
        self.accesses = []

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved, access):
        self.accesses.append(access)
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def DeleteValue(self, key, name):
        raise AssertionError("el Toolkit no debe borrar nada del arranque de Windows")

    def SetValueEx(self, *args):
        raise AssertionError("el Toolkit no debe escribir nada en el arranque de Windows")


class PreferenceTests(unittest.TestCase):
    def test_first_time_takes_legacy_and_leaves_it(self):
        config, logs = {}, []
        self.assertTrue(startup_preference(config.get, config.__setitem__, FakeLegacy(True), logs.append))
        self.assertEqual(config, {"auto_startup": True})
        self.assertEqual(logs, ["startup_migrated enabled=True; legacy_left=True"])

    def test_without_legacy_it_stays_off(self):
        config = {}
        self.assertFalse(startup_preference(config.get, config.__setitem__, FakeLegacy(False)))
        self.assertEqual(config, {"auto_startup": False})

    def test_saved_preference_never_looks_at_windows(self):
        class Untouchable:
            def enabled(self):
                raise AssertionError("con la preferencia guardada no se mira lo viejo")

        config = {"auto_startup": False}
        self.assertFalse(startup_preference(config.get, config.__setitem__, Untouchable()))


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
    def test_reads_the_old_run_value_and_leaves_it(self):
        registry = FakeRegistry({"ToolkitOGM_Sync": '"C:\\ToolkitOGM.exe" --autorun'})
        legacy = LegacyStartup(task_xml=lambda: None, registry=registry)
        self.assertTrue(legacy.enabled())
        self.assertEqual(registry.values, {"ToolkitOGM_Sync": '"C:\\ToolkitOGM.exe" --autorun'})
        self.assertEqual(set(registry.accesses), {FakeRegistry.KEY_READ})
        self.assertFalse(hasattr(legacy, "remove"))

    def test_nothing_left_means_off(self):
        self.assertFalse(LegacyStartup(task_xml=lambda: None, registry=FakeRegistry({})).enabled())

    def test_a_task_reader_that_fails_counts_as_no_task(self):
        def broken():
            raise OSError("sin acceso al Programador de tareas")

        self.assertFalse(LegacyStartup(task_xml=broken, registry=FakeRegistry({})).enabled())

    @staticmethod
    def _task(user, nulls=False):
        xml = f'<?xml version="1.0"?><Task><Principals><Principal id="Author"><UserId>{user}</UserId>' \
              '</Principal></Principals></Task>'
        return "\x00".join(xml) if nulls else xml

    def test_task_of_another_windows_user_does_not_count(self):
        legacy = LegacyStartup(task_xml=lambda: self._task("S-1-5-21-1-2-3-1002"), registry=FakeRegistry({}),
                               user_ids={"S-1-5-21-1-2-3-1001", "ana"})
        self.assertFalse(legacy.enabled())
        self.assertEqual(legacy.task_owner(), "S-1-5-21-1-2-3-1002")

    def test_own_task_by_sid_or_name_counts(self):
        for user in ("S-1-5-21-1-2-3-1001", "LAPTOP\\Ana", "ana"):
            legacy = LegacyStartup(task_xml=lambda: self._task(user), registry=FakeRegistry({}),
                                   user_ids={"s-1-5-21-1-2-3-1001", "laptop\\ana", "ana"})
            self.assertTrue(legacy.enabled(), user)

    def test_reads_the_owner_even_with_nulls(self):
        legacy = LegacyStartup(task_xml=lambda: self._task("S-1-5-21-9", nulls=True), registry=FakeRegistry({}),
                               user_ids=set())
        self.assertEqual(legacy.task_owner(), "S-1-5-21-9")

    def test_the_toolkit_never_touches_windows_startup(self):
        # Desde la 2.4.5 ni crea ni borra: Defender ponía en cuarentena el Toolkit por tocar el arranque.
        for name in ("autostart.py", "main.py"):
            source = (TOOLKIT_DIR / name).read_text(encoding="utf-8")
            for forbidden in ("/Create", "/Delete", "SetValueEx", "DeleteValue", "CreateKey", "import subprocess\n"
                              if name == "autostart.py" else "/Create"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")

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
