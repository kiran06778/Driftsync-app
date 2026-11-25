"""The app launchers: DriftSync.app (macOS), the Windows shortcut scripts, the icons, and the app name/icon
code in desktop_app / platform_bridge. Checked on any computer; nothing is opened or installed.
Run from the project folder:  python3 -m unittest discover tests -v"""
import os
import plistlib
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("webview", types.ModuleType("webview"))
import desktop_app as app  # noqa: E402
import platform_bridge as pb  # noqa: E402

APP = ROOT / "DriftSync.app" / "Contents"
ICONS = ROOT / "launcher" / "icons"


class MacApp(unittest.TestCase):
    def setUp(self):
        with open(APP / "Info.plist", "rb") as f:
            self.info = plistlib.load(f)

    def test_info_plist_names_the_app_and_its_icon(self):
        self.assertEqual(self.info["CFBundleName"], "DriftSync")
        self.assertEqual(self.info["CFBundlePackageType"], "APPL")
        self.assertTrue((APP / "Resources" / (self.info["CFBundleIconFile"] + ".icns")).is_file())

    def test_permission_texts_are_there(self):
        # macOS asks for the camera / Automation on behalf of the app; without these texts it refuses outright
        self.assertIn("NSCameraUsageDescription", self.info)
        self.assertIn("NSAppleEventsUsageDescription", self.info)

    def test_launcher_script_exists_is_executable_and_parses(self):
        exe = APP / "MacOS" / self.info["CFBundleExecutable"]
        self.assertTrue(exe.is_file())
        self.assertNotIn(b"\r\n", exe.read_bytes(), "the Mac launcher needs Unix line endings")
        if os.name != "nt":
            self.assertTrue(os.access(exe, os.X_OK), "DriftSync.app/Contents/MacOS/DriftSync must be executable")
        if shutil.which("bash") and os.name != "nt":   # Windows "bash" is often the WSL stub, not a real shell
            self.assertEqual(subprocess.run(["bash", "-n", str(exe)]).returncode, 0)

    def test_launcher_starts_desktop_app_with_the_launcher_flag(self):
        text = (APP / "MacOS" / "DriftSync").read_text()
        self.assertIn("export DRIFTSYNC_LAUNCHER=app", text)
        self.assertIn('exec "$PY" desktop_app.py', text)


class WindowsLauncher(unittest.TestCase):
    def test_vbs_files_use_windows_line_endings(self):
        for name in ("DriftSync.vbs", "Create shortcuts.vbs"):
            raw = (ROOT / "launcher" / name).read_bytes()
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)

    def test_shortcut_points_at_files_that_exist(self):
        text = (ROOT / "launcher" / "Create shortcuts.vbs").read_text()
        for part in (r"\launcher\DriftSync.vbs", r"\launcher\icons\DriftSync.ico"):
            self.assertIn(part, text)
            self.assertTrue((ROOT / part.replace("\\", "/").lstrip("/")).is_file(), part)
        self.assertIn("wscript.exe", text)   # no console window

    def test_launcher_uses_pythonw_and_falls_back_to_the_bat(self):
        text = (ROOT / "launcher" / "DriftSync.vbs").read_text()
        self.assertIn(r".venv\Scripts\pythonw.exe", text)
        self.assertIn(r"\DriftSync.bat", text)

    def test_bat_creates_the_shortcuts_once(self):
        raw = (ROOT / "DriftSync.bat").read_bytes()
        self.assertIn(b'launcher\\Create shortcuts.vbs" /quiet', raw)
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


class Icons(unittest.TestCase):
    def test_icon_files_exist(self):
        for name in ("DriftSync.ico", "DriftSync.icns", "DriftSync-512.png", "DriftSync.svg"):
            self.assertTrue((ICONS / name).is_file(), name)
        self.assertEqual((ICONS / "DriftSync.icns").read_bytes()[:4], b"icns")
        self.assertEqual((ICONS / "DriftSync.ico").read_bytes()[:4], b"\x00\x00\x01\x00")

    def test_ico_has_the_small_and_large_sizes(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        sizes = Image.open(ICONS / "DriftSync.ico").info["sizes"]
        for s in (16, 24, 32, 48, 256):
            self.assertIn((s, s), sizes)


class AppIdentity(unittest.TestCase):
    def test_permission_prompts_name_driftsync_when_opened_from_the_app(self):
        with mock.patch.dict(os.environ, {"DRIFTSYNC_LAUNCHER": "app"}):
            self.assertEqual(pb._host_app_name(), "DriftSync")
        with mock.patch.dict(os.environ, {"TERM_PROGRAM": "Apple_Terminal"}):
            os.environ.pop("DRIFTSYNC_LAUNCHER", None)
            self.assertEqual(pb._host_app_name(), "Terminal")

    def test_set_app_identity_never_raises(self):
        app.set_app_identity()   # no AppKit / Windows here: it just logs and carries on

    def test_window_icon_is_windows_only(self):
        with mock.patch.object(pb, "IS_WINDOWS", False):
            self.assertFalse(pb.set_window_icon(object(), ICONS / "DriftSync.ico"))

    def test_window_icon_without_a_native_window(self):
        with mock.patch.object(pb, "IS_WINDOWS", True):
            self.assertFalse(pb.set_window_icon(types.SimpleNamespace(native=None), ICONS / "DriftSync.ico"))

    def test_crash_hook_shows_a_dialog(self):
        with mock.patch.object(pb, "inform") as inform, mock.patch("sys.stderr"):
            app._launcher_crash_hook(RuntimeError, RuntimeError("boom"), None)
        self.assertIn("boom", inform.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
