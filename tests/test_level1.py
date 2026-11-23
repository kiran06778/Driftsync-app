"""Level 1 (Corporate) strictness: notifications only, never a popup. Levels 2 and 3 must keep the popup.
Run from the project folder:  python3 -m unittest discover tests -v
PyWebView isn't needed: a stand-in module is used, and nothing real is shown or played."""
import sys
import types
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("webview", types.ModuleType("webview"))
import desktop_app as app  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Level1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = Path(self.tmp.name) / "test.db"
        app.init_db()
        app.current_user = {"id": 1, "username": "t"}
        app.active_session_config.update({"strictness": "1", "mode": "Corporate", "goal": "Finish the report",
                                          "frictionStyle": "banner", "sessionType": "FOCUS"})
        app.is_friction_active = False
        app.last_friction_closed_at = 0.0
        app.last_video_insight = None
        app.reset_smart_state()
        self.clock = FakeClock()
        self.window = mock.MagicMock()
        patches = [
            mock.patch.object(app.time, "time", self.clock),
            mock.patch.object(app, "friction_window", self.window),
            mock.patch.object(app.platform_bridge, "notify", return_value=True),
            mock.patch.object(app.platform_bridge, "chime", return_value=True),
            mock.patch.object(app.platform_bridge, "bring_app_to_front"),
            mock.patch.object(app.platform_bridge, "hide_app"),
        ]
        self.mocks = [p.start() for p in patches]
        self.notify, self.chime = self.mocks[2], self.mocks[3]
        for p in patches:
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def drift(self, item="Instagram"):
        app.trigger_friction_intercept(item, f"{item} | feed")

    def rows(self):
        conn = app.db_connect()
        rows = conn.execute("SELECT app_name, response, unlocked FROM drifts ORDER BY id").fetchall()
        conn.close()
        return rows

    def stay(self, seconds, item="Instagram"):
        """The radar sees the same app every 1.5 seconds for this long."""
        end = self.clock.now + seconds
        while self.clock.now < end:
            self.clock.now += app.SCAN_INTERVAL_SEC
            self.drift(item)

    # --- Level 1 ---
    def test_drift_sends_notification_not_popup(self):
        self.drift()
        self.notify.assert_called_once()
        title, message = self.notify.call_args[0][:2]
        self.assertIn("Instagram", message)
        self.assertIn("Finish the report", message)
        self.window.show.assert_not_called()
        self.assertFalse(app.is_friction_active)
        self.assertEqual(self.rows(), [("Instagram", "reminded", 0)])

    def test_fullscreen_choice_still_means_notification(self):
        app.active_session_config["frictionStyle"] = "fullscreen"
        self.drift()
        self.notify.assert_called_once()
        self.window.show.assert_not_called()

    def test_staying_logs_one_drift_and_repeats_reminder(self):
        self.drift()
        self.stay(5 * 60)
        self.assertEqual(len(self.rows()), 1, "a 5-minute stay is one drift, not one per reminder")
        self.assertGreaterEqual(self.notify.call_count, 4)
        self.assertLessEqual(self.notify.call_count, 6)
        self.window.show.assert_not_called()

    def test_ignored_reminders_get_firmer(self):
        self.drift()
        self.stay(5 * 60)
        calls = self.notify.call_args_list
        for c in calls[:app.SOFT_ESCALATE_AFTER]:
            self.assertFalse(c.kwargs.get("sound"))
        firm = calls[app.SOFT_ESCALATE_AFTER]
        self.assertTrue(firm.kwargs.get("sound"))
        self.assertIn("Still on Instagram", firm.args[1])

    def test_leaving_resets_the_count_and_logs_a_new_drift(self):
        self.drift()
        self.stay(4 * 60)
        self.clock.now += 120          # away from Instagram for 2 minutes
        self.notify.reset_mock()
        self.drift()
        self.assertFalse(self.notify.call_args.kwargs.get("sound"))
        self.assertEqual(len(self.rows()), 2)

    def test_notification_failure_falls_back_to_sound(self):
        self.notify.return_value = False
        self.drift()
        self.chime.assert_called_once()
        self.window.show.assert_not_called()

    def test_nothing_available_still_no_popup(self):
        self.notify.return_value = False
        self.chime.return_value = False
        self.drift()
        self.window.show.assert_not_called()
        self.assertFalse(app.is_friction_active)
        self.assertEqual(len(self.rows()), 1)

    def test_sound_only_style(self):
        app.active_session_config["frictionStyle"] = "chime"
        self.drift()
        self.chime.assert_called_once()
        self.notify.assert_not_called()

    def test_save_config_level1_keeps_notification(self):
        api = app.Api() if hasattr(app, "Api") else app.API()
        api.save_session_config({"strictness": "1", "frictionStyle": "fullscreen"})
        self.assertEqual(app.active_session_config["frictionStyle"], "banner")
        api.save_session_config({"strictness": "1", "frictionStyle": "chime"})
        self.assertEqual(app.active_session_config["frictionStyle"], "chime")

    def test_test_button(self):
        api = app.Api() if hasattr(app, "Api") else app.API()
        self.assertTrue(api.test_soft_reminder("banner")["success"])
        self.assertTrue(api.test_soft_reminder("chime")["success"])
        self.assertFalse(api.test_soft_reminder("fullscreen")["success"])

    # --- Levels 2 and 3 are unchanged ---
    def test_level2_and_3_still_popup(self):
        api = app.Api() if hasattr(app, "Api") else app.API()
        for lvl in ("2", "3"):
            api.save_session_config({"strictness": lvl, "frictionStyle": "banner"})
            self.assertEqual(app.active_session_config["frictionStyle"], "fullscreen")
            app.is_friction_active = False
            app.last_drift.update({"app": None, "time": 0.0, "id": None})
            self.window.reset_mock()
            self.notify.reset_mock()
            self.drift("Reddit")
            self.window.show.assert_called_once()
            self.notify.assert_not_called()
            self.assertTrue(app.is_friction_active)

    def test_level3_still_needs_exact_goal(self):
        api = app.Api() if hasattr(app, "Api") else app.API()
        api.save_session_config({"strictness": "3"})
        app.is_friction_active = True
        self.assertFalse(api.verify_friction_goal("finish teh report", 1)["success"])
        self.assertFalse(api.continue_anyway(1)["success"])


if __name__ == "__main__":
    unittest.main()
