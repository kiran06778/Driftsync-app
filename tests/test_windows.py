"""Windows code paths, checked on any computer with stand-ins for the Windows parts (registry, user32,
PowerShell, winsound). Nothing real is opened, played or changed.
Run from the project folder:  python3 -m unittest discover tests -v

What these tests can't prove: that Windows itself behaves as the stand-ins assume. The real-PC checklist
in WINDOWS_TESTING.md covers that part."""
import ctypes
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("webview", types.ModuleType("webview"))
import desktop_app as app  # noqa: E402
import platform_bridge as pb  # noqa: E402
import video_insight  # noqa: E402

ZWSP = "​"


# ---------------------------------------------------------------- stand-ins
class FakeWinreg(types.ModuleType):
    """A dict-backed registry: {(hive, path_lower): {name: value}}."""
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = "HKCU", "HKLM"
    KEY_SET_VALUE, REG_DWORD = 2, 4

    def __init__(self, data=None):
        super().__init__("winreg")
        self.data = {(h, p.lower()): dict(v) for (h, p), v in (data or {}).items()}

    class _Key:
        def __init__(self, reg, hive, path, create=False):
            self.k = (hive, path.lower())
            if self.k not in reg.data:
                if not create:
                    raise OSError("no such key")
                reg.data[self.k] = {}
            self.reg = reg

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, hive, path, *a):
        return self._Key(self, hive, path)

    def CreateKeyEx(self, hive, path, *a):
        return self._Key(self, hive, path, create=True)

    def QueryValueEx(self, key, name):
        vals = self.data[key.k]
        if name not in vals:
            raise OSError("no such value")
        return vals[name], 4

    def SetValueEx(self, key, name, _res, _type, value):
        self.data[key.k][name] = value


def windows(reg=None):
    """Pretend to be Windows, with this registry."""
    return mock.patch.multiple(pb, IS_WINDOWS=True, IS_MAC=False), \
        mock.patch.dict(sys.modules, {"winreg": reg or FakeWinreg()})


class Recorder:
    """user32 / kernel32 stand-in: records every call and returns a configurable value."""
    def __init__(self, returns=None):
        self.calls, self.returns = [], returns or {}

    def __getattr__(self, name):
        def fn(*args):
            self.calls.append((name, args))
            r = self.returns.get(name, 1)
            return r(*args) if callable(r) else r
        return fn

    def names(self):
        return [c[0] for c in self.calls]


NOTIF = pb._WIN_NOTIF_KEY
PUSH = pb._WIN_PUSH_KEY
PS_APP = NOTIF + "\\" + pb._WIN_TOAST_APP
CAM = pb._WIN_CAMERA_KEY


# ---------------------------------------------------------------- browser titles
class BrowserTitleTests(unittest.TestCase):
    def setUp(self):
        pb._profile_cache.clear()

    def tearDown(self):
        pb._profile_cache.clear()

    def test_edge_title_loses_profile_tab_count_and_hidden_space(self):
        raw = f"Lofi beats to study - YouTube and 3 more pages - Personal - Microsoft{ZWSP} Edge"
        self.assertEqual(pb._win_clean_title("microsoft edge", raw), "Lofi beats to study - YouTube - Microsoft Edge")

    def test_edge_inprivate_and_work_profiles(self):
        self.assertEqual(pb._win_clean_title("microsoft edge", f"r/python - Reddit - [InPrivate] - Microsoft{ZWSP} Edge"),
                         "r/python - Reddit - Microsoft Edge")
        self.assertEqual(pb._win_clean_title("microsoft edge", "Instagram - Work - Microsoft Edge"),
                         "Instagram - Microsoft Edge")

    def test_edge_without_profile_keeps_site_name(self):
        # if Edge ever leaves the profile out, the site name must not be eaten
        self.assertEqual(pb._win_clean_title("microsoft edge", "r/python - Reddit - Microsoft Edge"),
                         "r/python - Reddit - Microsoft Edge")

    def test_custom_profile_name_read_from_local_state(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d, "Microsoft", "Edge", "User Data")
            folder.mkdir(parents=True)
            (folder / "Local State").write_text(json.dumps(
                {"profile": {"info_cache": {"Default": {"name": "Kiran College"}}}}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": d}), \
                    mock.patch.object(pb, "_PROFILE_BROWSERS", {"microsoft edge": ("Microsoft Edge", str(Path("Microsoft", "Edge", "User Data")))}):
                self.assertEqual(pb._win_clean_title("microsoft edge", "Netflix - Kiran College - Microsoft Edge"),
                                 "Netflix - Microsoft Edge")

    def test_chrome_profile_after_browser_name(self):
        self.assertEqual(pb._win_clean_title("google chrome", "YouTube - Google Chrome - Personal"),
                         "YouTube - Google Chrome")
        self.assertEqual(pb._win_clean_title("google chrome", "YouTube - Google Chrome"), "YouTube - Google Chrome")

    def test_other_apps_untouched(self):
        self.assertEqual(pb._win_clean_title("code", "reddit_notes.py - Visual Studio Code"),
                         "reddit_notes.py - Visual Studio Code")

    def test_blocklist_matches_cleaned_edge_titles(self):
        for raw in (f"r/python - Reddit - Personal - Microsoft{ZWSP} Edge",
                    f"Home - YouTube and 2 more pages - Profile 1 - Microsoft{ZWSP} Edge"):
            info = "microsoft edge | " + pb._win_clean_title("microsoft edge", raw)
            site = "reddit" if "Reddit" in raw else "youtube"
            self.assertTrue(app.smart_match(site, info), info)
        # even an uncleaned title with the hidden space still matches the site part
        self.assertTrue(app.smart_match("reddit", f"microsoft edge | r/python - Reddit - Microsoft{ZWSP} Edge"))
        # an article that only mentions YouTube is still not flagged
        self.assertFalse(app.smart_match("youtube", "microsoft edge | Embedding YouTube in React - Stack Overflow - Microsoft Edge"))

    def test_firefox_private_window(self):
        self.assertTrue(app.smart_match("reddit", "firefox | r/python - Reddit — Mozilla Firefox Private Browsing"))

    def test_smart_youtube_reads_windows_titles(self):
        for app_name, raw in (("microsoft edge", f"Dijkstra's Algorithm - YouTube and 4 more pages - Personal - Microsoft{ZWSP} Edge"),
                              ("google chrome", "(3) Dijkstra's Algorithm - YouTube - Google Chrome"),
                              ("firefox", "Dijkstra's Algorithm - YouTube — Mozilla Firefox")):
            title = pb._win_clean_title(app_name, raw)
            self.assertTrue(video_insight.is_youtube_page("", title), title)
            self.assertEqual(video_insight.clean_youtube_title(title, app_name), "Dijkstra's Algorithm")

    def test_active_window_info_maps_exe_names(self):
        proc = mock.MagicMock()
        proc.name.return_value = "msedge.exe"
        psutil_stub = types.SimpleNamespace(Process=lambda pid: proc)
        with mock.patch.object(pb, "_win_foreground", return_value=(42, 7, f"Instagram - Personal - Microsoft{ZWSP} Edge")), \
                mock.patch.dict(sys.modules, {"psutil": psutil_stub}):
            self.assertEqual(pb._win_active_window_info(), "microsoft edge | Instagram - Microsoft Edge")
        self.assertEqual(pb._last_foreground["microsoft edge"], 42)

    def test_store_apps_named_by_title(self):
        proc = mock.MagicMock()
        proc.name.return_value = "ApplicationFrameHost.exe"
        with mock.patch.object(pb, "_win_foreground", return_value=(9, 3, "WhatsApp")), \
                mock.patch.dict(sys.modules, {"psutil": types.SimpleNamespace(Process=lambda pid: proc)}):
            self.assertEqual(pb._win_active_window_info(), "whatsapp | WhatsApp")
        self.assertTrue(app.smart_match("WhatsApp", "whatsapp | WhatsApp"))


# ---------------------------------------------------------------- windows: raise / hide / boxes
class FakeWindll:
    def __init__(self, user32, kernel32=None, ole32=None):
        self.user32, self.kernel32, self.ole32 = user32, kernel32 or Recorder(), ole32 or Recorder()


class WindowControlTests(unittest.TestCase):
    def test_bring_to_front_joins_foreground_input(self):
        user32 = Recorder({"GetForegroundWindow": 500, "GetWindowThreadProcessId": 77, "IsIconic": 0,
                           "SetForegroundWindow": 1})
        kernel32 = Recorder({"GetCurrentThreadId": 11})
        with mock.patch.object(ctypes, "windll", FakeWindll(user32, kernel32), create=True), \
                mock.patch.object(pb, "_win_windows_of", return_value=[1001, 1002]):
            self.assertTrue(pb._win_bring_to_front(123))
        calls = user32.calls
        self.assertIn(("AttachThreadInput", (11, 77, True)), calls)
        self.assertIn(("SetForegroundWindow", (1001,)), calls)       # the top window (the on-top popup)
        self.assertIn(("AttachThreadInput", (11, 77, False)), calls)  # always detached again
        self.assertNotIn("keybd_event", user32.names())               # no Alt press when it worked

    def test_bring_to_front_falls_back_to_alt(self):
        user32 = Recorder({"GetForegroundWindow": 0, "IsIconic": 1, "SetForegroundWindow": 0})
        with mock.patch.object(ctypes, "windll", FakeWindll(user32), create=True), \
                mock.patch.object(pb, "_win_windows_of", return_value=[1001]):
            self.assertFalse(pb._win_bring_to_front(123))
        self.assertIn(("ShowWindow", (1001, 9)), user32.calls)        # restored from minimised
        self.assertEqual(user32.names().count("keybd_event"), 2)

    def test_hide_store_app_uses_last_seen_window(self):
        user32 = Recorder()
        pb._last_foreground["whatsapp"] = 55
        with mock.patch.object(ctypes, "windll", FakeWindll(user32), create=True), \
                mock.patch.object(pb, "_win_windows_of", return_value=[]):
            pb._win_hide_app("WhatsApp")
        self.assertEqual(user32.calls, [("ShowWindow", (55, 6))])

    def test_quit_boxes_open_on_top(self):
        user32 = Recorder({"MessageBoxW": 1})
        a, b = windows()
        with a, b, mock.patch.object(ctypes, "windll", FakeWindll(user32), create=True):
            self.assertTrue(pb.confirm("Quit DriftSync?", "Sure?"))
            self.assertTrue(pb.inform("Level 3", "Stays open"))
        for name, args in user32.calls:
            self.assertEqual(args[3] & 0x50000, 0x50000)   # MB_TOPMOST | MB_SETFOREGROUND


# ---------------------------------------------------------------- notifications
class NotificationTests(unittest.TestCase):
    def test_status_on_by_default(self):
        a, b = windows()
        with a, b:
            self.assertEqual(pb.notification_status()["enabled"], True)

    def test_all_off_is_detected_and_switched_on(self):
        reg = FakeWinreg({("HKCU", PUSH): {"ToastEnabled": 0}})
        a, b = windows(reg)
        with a, b:
            st = pb.notification_status()
            self.assertEqual((st["enabled"], st["reason"], st["canFix"]), (False, "all-off", True))
            self.assertTrue(pb.enable_notifications()["enabled"])
        self.assertEqual(reg.data[("HKCU", PUSH.lower())]["ToastEnabled"], 1)

    def test_win11_master_switch_off(self):
        reg = FakeWinreg({("HKCU", NOTIF): {"NOC_GLOBAL_SETTING_TOASTS_ENABLED": 0}})
        a, b = windows(reg)
        with a, b:
            self.assertEqual(pb.notification_status()["reason"], "all-off")
            self.assertTrue(pb.enable_notifications()["enabled"])

    def test_sender_off_is_detected_and_switched_on(self):
        reg = FakeWinreg({("HKCU", PS_APP): {"Enabled": 0}})
        a, b = windows(reg)
        with a, b:
            self.assertEqual(pb.notification_status()["reason"], "app-off")
            self.assertTrue(pb.enable_notifications()["enabled"])
        self.assertEqual(reg.data[("HKCU", PS_APP.lower())]["Enabled"], 1)

    def test_enable_never_touches_anything_when_already_on(self):
        reg = FakeWinreg()
        a, b = windows(reg)
        with a, b:
            pb.enable_notifications()
        self.assertEqual(reg.data, {})

    def test_notify_returns_false_when_off_so_level1_chimes(self):
        reg = FakeWinreg({("HKCU", PUSH): {"ToastEnabled": 0}})
        a, b = windows(reg)
        with a, b, mock.patch.object(pb.subprocess, "Popen") as popen:
            self.assertFalse(pb.notify("t", "m"))
        popen.assert_not_called()

    def test_notify_runs_hidden_powershell_with_text_in_env(self):
        a, b = windows()
        proc = mock.MagicMock()
        proc.wait.return_value = 0
        with a, b, mock.patch.object(pb.subprocess, "Popen", return_value=proc) as popen, \
                mock.patch.object(pb.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                mock.patch.object(pb, "chime") as chime:
            self.assertTrue(pb.notify('Back to "work"', "Instagram is on your drift list"))
            for t in list(pb._threading.enumerate()):
                if t.name != "MainThread" and t.daemon and t.is_alive():
                    t.join(1)
        args, kw = popen.call_args
        self.assertEqual(args[0][0], "powershell")
        self.assertEqual(kw["creationflags"], 0x08000000)
        self.assertEqual(kw["env"]["DS_TITLE"], 'Back to "work"')   # quotes can't break the script
        self.assertNotIn("Back to", " ".join(args[0]))
        chime.assert_not_called()

    def test_failed_toast_plays_a_sound(self):
        a, b = windows()
        proc = mock.MagicMock()
        proc.wait.return_value = 1
        with a, b, mock.patch.object(pb.subprocess, "Popen", return_value=proc), mock.patch.object(pb, "chime") as chime:
            pb.notify("t", "m")
            for t in list(pb._threading.enumerate()):
                if t.name != "MainThread" and t.daemon and t.is_alive():
                    t.join(1)
        chime.assert_called_once()

    def test_level1_reminder_falls_back_to_sound(self):
        app.active_session_config.update({"strictness": "1", "frictionStyle": "banner", "goal": "x"})
        with mock.patch.object(pb, "notify", return_value=False), mock.patch.object(pb, "chime", return_value=True):
            self.assertEqual(app.show_soft_reminder("banner", "Instagram"), "sound")


# ---------------------------------------------------------------- camera
class CameraTests(unittest.TestCase):
    def setUp(self):
        pb._camera_granted = False

    def tearDown(self):
        pb._camera_granted = False

    def test_privacy_switches(self):
        cases = [({}, "ok"),
                 ({("HKCU", CAM): {"Value": "Deny"}}, "off-for-all"),
                 ({("HKCU", CAM + r"\NonPackaged"): {"Value": "Deny"}}, "off-for-desktop-apps"),
                 ({("HKLM", CAM): {"Value": "Deny"}}, "off-by-admin"),
                 ({("HKCU", CAM): {"Value": "Allow"}, ("HKCU", CAM + r"\NonPackaged"): {"Value": "Allow"}}, "ok")]
        for data, expected in cases:
            a, b = windows(FakeWinreg(data))
            with a, b:
                self.assertEqual(pb.win_camera_privacy(), expected, data)

    def test_blocked_camera_is_not_probed_and_no_native_box(self):
        a, b = windows(FakeWinreg({("HKCU", CAM + r"\NonPackaged"): {"Value": "Deny"}}))
        with a, b, mock.patch.object(pb, "_camera_probe") as probe, \
                mock.patch.object(pb, "_mac_camera_denied_dialog") as mac_box:
            self.assertFalse(pb.request_camera_access())
            self.assertEqual(pb.camera_problem()["reason"], "privacy")
        probe.assert_not_called()
        mac_box.assert_not_called()

    def test_busy_and_missing(self):
        a, b = windows()
        with a, b, mock.patch.object(pb, "camera_apps_running", return_value=["Zoom"]):
            self.assertEqual(pb.camera_problem(), {"reason": "busy", "apps": ["Zoom"]})
        a, b = windows()
        with a, b, mock.patch.object(pb, "camera_apps_running", return_value=[]):
            self.assertEqual(pb.camera_problem()["reason"], "missing")

    def test_allowed_camera_is_remembered(self):
        a, b = windows()
        with a, b, mock.patch.object(pb, "_camera_probe", return_value=True) as probe:
            self.assertTrue(pb.request_camera_access())
            self.assertTrue(pb.request_camera_access())
        probe.assert_called_once()

    def test_api_tells_the_page_why(self):
        fake_pc = types.SimpleNamespace(available=lambda: True)
        a, b = windows(FakeWinreg({("HKCU", CAM): {"Value": "Deny"}}))
        with a, b, mock.patch.object(app, "presence_check", fake_pc):
            r = app.Api().request_camera_access()
        self.assertEqual((r["ok"], r["reason"], r["os"]), (False, "privacy", "windows"))

    def test_probe_runs_without_a_console_window(self):
        with mock.patch.object(pb.subprocess, "run") as run, \
                mock.patch.object(pb.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            run.return_value.returncode = 0
            self.assertTrue(pb._camera_probe())
        self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
        self.assertIn("CAP_MSMF", run.call_args.args[0][2])   # second camera backend is tried too


# ---------------------------------------------------------------- alarm volume
class AlarmTests(unittest.TestCase):
    def test_windows_alarm_turns_up_and_restores_volume(self):
        sets = []
        winsound = types.SimpleNamespace(SND_FILENAME=1, SND_ASYNC=2, SND_LOOP=4, PlaySound=mock.MagicMock())
        a, b = windows()
        with a, b, mock.patch.dict(sys.modules, {"winsound": winsound}), \
                mock.patch.object(pb, "_win_get_volume", return_value=(20, True)), \
                mock.patch.object(pb, "_win_set_volume", side_effect=lambda v, m=False: sets.append((v, m))), \
                mock.patch.object(ctypes, "windll", FakeWindll(Recorder()), create=True), \
                mock.patch.object(pb, "_alarm_wav", return_value="alarm.wav"):
            self.assertTrue(pb.start_alarm())
            pb._alarm_stop.wait(0.3)
            pb.stop_alarm()
        self.assertEqual(sets[0], (40, False))           # unmuted, at least 40%
        self.assertEqual(sets[-1], (20, True))           # put back exactly: 20%, muted
        winsound.PlaySound.assert_any_call("alarm.wav", 1 | 2 | 4)
        winsound.PlaySound.assert_any_call(None, 0)      # the sound stops

    def test_alarm_without_volume_control_still_rings(self):
        winsound = types.SimpleNamespace(SND_FILENAME=1, SND_ASYNC=2, SND_LOOP=4, PlaySound=mock.MagicMock())
        a, b = windows()
        with a, b, mock.patch.dict(sys.modules, {"winsound": winsound}), \
                mock.patch.object(pb, "_win_get_volume", return_value=None), \
                mock.patch.object(pb, "_win_set_volume") as setv, \
                mock.patch.object(ctypes, "windll", FakeWindll(Recorder()), create=True), \
                mock.patch.object(pb, "_alarm_wav", return_value="alarm.wav"):
            self.assertTrue(pb.start_alarm())
            pb.stop_alarm()
        setv.assert_not_called()


# ---------------------------------------------------------------- startup
class StartupTests(unittest.TestCase):
    def test_webview2_detection(self):
        key = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        a, b = windows(FakeWinreg({("HKLM", key): {"pv": "131.0.2903.70"}}))
        with a, b:
            self.assertTrue(pb.webview2_installed())
        a, b = windows(FakeWinreg({("HKLM", key): {"pv": "0.0.0.0"}}))
        with a, b:
            self.assertFalse(pb.webview2_installed())
        user_key = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        a, b = windows(FakeWinreg({("HKCU", user_key): {"pv": "120.0.1"}}))
        with a, b:
            self.assertTrue(pb.webview2_installed())

    def test_env_file_saved_by_notepad(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, ".env.txt")
            p.write_bytes("﻿DS_TEST_KEY_A=abc\r\nDS_TEST_KEY_B = \"x y\"\r\n".encode("utf-8"))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DS_TEST_KEY_A", None)
                os.environ.pop("DS_TEST_KEY_B", None)
                app.load_env_file(p)
                self.assertEqual(os.environ.get("DS_TEST_KEY_A"), "abc")
                self.assertEqual(os.environ.get("DS_TEST_KEY_B"), "x y")

    def test_platform_info_for_pages(self):
        a, b = windows()
        with a, b, mock.patch.object(pb, "can_raise_volume", return_value=True):
            info = app.Api().get_platform_info()
        self.assertEqual(info["os"], "windows")
        self.assertEqual(info["cameraPrivacy"], "ok")
        self.assertTrue(info["notifications"]["enabled"])

    def test_launcher_has_windows_line_endings(self):
        raw = (ROOT / "DriftSync.bat").read_bytes()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))   # cmd.exe breaks labels on bare \n
        self.assertIn(b'-c "import sys"', raw)                # catches the Microsoft Store "python" placeholder

    def test_requirements_pick_the_right_packages_on_windows(self):
        try:
            from packaging.requirements import Requirement
        except ImportError:
            self.skipTest("packaging not installed")
        reqs = [Requirement(line.split("#")[0].strip()) for line in (ROOT / "requirements.txt").read_text().splitlines()
                if line.split("#")[0].strip()]
        win = {"sys_platform": "win32", "platform_machine": "AMD64"}
        arm = {"sys_platform": "win32", "platform_machine": "ARM64"}
        mac = {"sys_platform": "darwin", "platform_machine": "arm64"}
        chosen = lambda env: {str(r.name) + str(r.specifier) for r in reqs if not r.marker or r.marker.evaluate(env)}
        self.assertIn("pywebview<7,>=6.0", chosen(win))
        self.assertIn("pywebview<7,>=5.0", chosen(mac))
        self.assertTrue(any(x.startswith("opencv-python") for x in chosen(win)))
        self.assertFalse(any(x.startswith("opencv-python") for x in chosen(arm)))   # no ARM build: don't fail the install

    def test_no_mac_only_calls_outside_mac_branches(self):
        """osascript / afplay / pmset / ioreg may only run inside an IS_MAC branch."""
        import ast
        src = (ROOT / "platform_bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        mac_only = ("osascript", "afplay", "pmset", "ioreg", "x-apple.systempreferences")
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            body = ast.get_source_segment(src, fn)
            if any(m in body for m in mac_only):
                self.assertTrue(fn.name.startswith("_mac") or "IS_MAC" in body or fn.name == "_osa", fn.name)


if __name__ == "__main__":
    unittest.main()
