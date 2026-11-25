"""The Windows "Not Responding" freeze (school PC, 2026-11-25): always-on-top changes must go through the
window's own UI thread, and a freeze must leave a report behind. Runs on any computer with stand-ins.
Run from the project folder:  python3 -m unittest discover tests -v"""
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


class FakeForm:
    """A WinForms form: records whether TopMost was set on the UI thread (through Invoke) or directly."""
    def __init__(self, invoke_required=True):
        self.InvokeRequired = invoke_required
        self.calls = []
        self._top = False

    @property
    def TopMost(self):
        return self._top

    @TopMost.setter
    def TopMost(self, value):
        self.calls.append(("TopMost", value, self._in_invoke))
        self._top = value

    _in_invoke = False

    def Invoke(self, delegate):
        self._in_invoke = True
        try:
            delegate()
        finally:
            self._in_invoke = False


def fake_system():
    """`from System import Func, Type`: Func[Type](fn) just hands fn back."""
    system = types.ModuleType("System")

    class _Func:
        def __getitem__(self, _):
            return lambda fn: fn
    system.Func, system.Type = _Func(), object
    return system


class FakeWindow:
    def __init__(self, form=None):
        self.native = form
        self.on_top_set = []

    @property
    def on_top(self):
        return self.on_top_set[-1] if self.on_top_set else False

    @on_top.setter
    def on_top(self, value):
        self.on_top_set.append(value)


class SetOnTopTests(unittest.TestCase):
    def test_windows_sets_topmost_on_the_ui_thread(self):
        form = FakeForm(invoke_required=True)
        win = FakeWindow(form)
        with mock.patch.object(pb, "IS_WINDOWS", True), mock.patch.dict(sys.modules, {"System": fake_system()}):
            self.assertTrue(pb.set_on_top(win, True))
            self.assertTrue(pb.set_on_top(win, False))
        self.assertEqual(form.calls, [("TopMost", True, True), ("TopMost", False, True)])
        self.assertEqual(win.on_top_set, [], "pywebview's direct (cross-thread) setter must not be used")

    def test_windows_on_ui_thread_sets_directly(self):
        form = FakeForm(invoke_required=False)
        with mock.patch.object(pb, "IS_WINDOWS", True), mock.patch.dict(sys.modules, {"System": fake_system()}):
            pb.set_on_top(FakeWindow(form), True)
        self.assertEqual(form.calls, [("TopMost", True, False)])

    def test_mac_uses_pywebview(self):
        win = FakeWindow(form=object())
        with mock.patch.object(pb, "IS_WINDOWS", False):
            pb.set_on_top(win, True)
        self.assertEqual(win.on_top_set, [True])

    def test_no_window(self):
        self.assertFalse(pb.set_on_top(None, True))

    def test_desktop_app_never_sets_on_top_directly(self):
        src = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
        import re
        self.assertEqual(re.findall(r"\w+\.on_top\s*=", src), [],
                         "use platform_bridge.set_on_top(...) so Windows doesn't freeze")


class TimerStateDoesNotTouchWindowsDirectly(unittest.TestCase):
    def test_stop_on_page_load_hides_popups_through_the_bridge(self):
        friction, grace = FakeWindow(), FakeWindow()
        friction.hide = mock.Mock()
        grace.hide = mock.Mock()
        with mock.patch.object(app, "friction_window", friction, create=True), \
                mock.patch.object(app, "grace_window", grace, create=True), \
                mock.patch.object(app, "strict_locked", return_value=False), \
                mock.patch.object(pb, "set_on_top") as set_top:
            self.assertTrue(app.Api().set_timer_state(False, "FOCUS"))
        set_top.assert_any_call(friction, False)
        set_top.assert_any_call(grace, False)
        self.assertEqual(friction.on_top_set, [])


class DiagnosticsTests(unittest.TestCase):
    def test_quick_edit_and_responding_are_noops_off_windows(self):
        with mock.patch.object(pb, "IS_WINDOWS", False):
            self.assertFalse(pb.disable_console_quick_edit())
            self.assertIsNone(pb.window_responding(FakeWindow(FakeForm())))

    def test_hang_watch_writes_a_report_when_the_window_stops_responding(self):
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as d:
            started = []

            def capture(target, **kw):
                started.append(target)
                return mock.Mock()
            answers = iter([False, False, False, False, True])

            def responding(_w):
                try:
                    return next(answers)
                except StopIteration:
                    app.app_quitting = True
                    return True
            clock = [1000.0]

            def fake_time():
                clock[0] += 2
                return clock[0]
            with mock.patch.object(app, "_LOG_DIR", d), \
                    mock.patch.object(app.threading, "Thread", side_effect=capture), \
                    mock.patch.object(pb, "window_responding", side_effect=responding), \
                    mock.patch.object(app.time, "sleep"), \
                    mock.patch.object(app.time, "time", side_effect=fake_time), \
                    mock.patch.object(app, "app_quitting", False):
                app.start_hang_watch(FakeWindow())
                self.assertEqual(len(started), 1)
                started[0]()
            text = (Path(d) / "hang-report.txt").read_text(encoding="utf-8")
            self.assertIn("stopped responding", text)
            self.assertIn("File", text)   # thread stacks were written


if __name__ == "__main__":
    unittest.main()
