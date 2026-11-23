"""Level 3 (School) strictness: exact intention for one 1-minute break per focus block, no pauses,
no early stop, no quitting, settings locked, and the block survives a page reload or a force quit.
Run from the project folder:  python3 -m unittest discover tests -v
PyWebView isn't needed: a stand-in module is used, and nothing real is shown or played."""
import json
import sys
import types
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("webview", types.ModuleType("webview"))
import desktop_app as app  # noqa: E402

GOAL = "Revise chapter 4: Photosynthesis"


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Level3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        app.DB_PATH = Path(self.tmp.name) / "test.db"
        app.init_db()
        self.clock = FakeClock()
        self.window = mock.MagicMock()
        patches = [
            mock.patch.object(app, "STRICT_PATH", Path(self.tmp.name) / "strict_block.json"),
            mock.patch.object(app, "PREFS_PATH", Path(self.tmp.name) / "prefs.json"),
            mock.patch.object(app.time, "time", self.clock),
            mock.patch.object(app, "friction_window", self.window),
            mock.patch.object(app, "grace_window", mock.MagicMock()),
            mock.patch.object(app, "check_macos_permissions", return_value=True),
            mock.patch.object(app.platform_bridge, "notify", return_value=True),
            mock.patch.object(app.platform_bridge, "chime", return_value=True),
            mock.patch.object(app.platform_bridge, "bring_app_to_front"),
            mock.patch.object(app.platform_bridge, "hide_app"),
            mock.patch.object(app.platform_bridge, "stop_alarm"),
            mock.patch.object(app.platform_bridge, "inform", return_value=True),
            mock.patch.object(app.platform_bridge, "confirm", return_value=True),
            mock.patch.object(app, "show_alarm_overlay"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.inform = app.platform_bridge.inform
        self.reset_globals()
        self.api = app.Api()
        self.api.save_session_config({"strictness": "3", "goal": GOAL, "duration": 30,
                                      "blocklist": ["Instagram", "Reddit"]})
        self.addCleanup(self.reset_globals)

    def reset_globals(self):
        app.current_user = {"id": 1, "username": "t"}
        app.timer_is_running = False
        app.is_friction_active = False
        app.grace_period_end = None
        app.app_quitting = False
        app.last_friction_closed_at = 0.0
        app.last_video_insight = None
        app.live_session = None
        app.strict_block.clear()
        app.strict_block["active"] = False
        app.last_progress_at = 0.0
        app.strict_logged_start_ms = None
        app.smart_state["overrides"].clear()
        app.desk.update(state="off", hold=False, warned=False, logged=False)
        app.desk.pop("end_requested", None)
        app.active_session_config.update({"sessionType": "FOCUS", "frictionStyle": "fullscreen"})
        app.reset_smart_state()

    # helpers
    def start(self):
        self.assertTrue(self.api.set_timer_state(True, "FOCUS"))

    def drift(self, item="Instagram"):
        app.is_friction_active = False
        app.last_friction_closed_at = 0.0
        app.trigger_friction_intercept(item, f"{item} | feed")

    def rows(self, sql):
        conn = app.db_connect()
        out = conn.execute(sql).fetchall()
        conn.close()
        return out

    def drifts(self):
        return self.rows("SELECT app_name, unlocked, response FROM drifts ORDER BY id")

    def relaunch(self):
        """What a force quit + reopen looks like: memory is gone, only the file and the database are left."""
        self.reset_globals()
        app.active_session_config.update({"strictness": "2", "mode": "College", "goal": "default"})
        return app.restore_strict_block()

    # --- the intention check ---
    def test_exact_intention_needed_typos_rejected(self):
        self.start()
        self.drift()
        self.assertTrue(app.is_friction_active)
        self.window.show.assert_called()
        res = self.api.verify_friction_goal("Revise chapter 4: Photosynthsis", 1)
        self.assertFalse(res["success"])
        self.assertIn("word for word", res["message"])
        self.assertFalse(self.api.verify_friction_goal("", 1)["success"])
        self.assertFalse(self.api.continue_anyway(1)["success"], "no 'Continue anyway' at Level 3")

    def test_case_spacing_and_punctuation_ignored(self):
        self.start()
        self.drift()
        self.assertTrue(self.api.verify_friction_goal("  revise CHAPTER 4 photosynthesis ", 1)["success"])

    def test_one_break_per_block_capped_at_one_minute(self):
        self.start()
        self.drift()
        res = self.api.verify_friction_goal(GOAL, 10)
        self.assertTrue(res["success"])
        self.assertEqual(res["approved_grace"], 1.0, "Level 3 breaks are at most 1 minute")
        self.assertEqual(self.api.get_friction_rules()["unlocksLeft"], 0)
        app.grace_period_end = None
        self.drift("Reddit")
        self.assertTrue(app.is_friction_active, "the popup still shows after the break is used")
        res = self.api.verify_friction_goal(GOAL, 1)
        self.assertFalse(res["success"])
        self.assertIn("one per focus block", res["message"])

    def test_next_block_gets_a_new_break(self):
        self.start()
        self.drift()
        self.assertTrue(self.api.verify_friction_goal(GOAL, 1)["success"])
        self.clock.now += 30 * 60          # the block runs out
        self.assertTrue(self.api.set_timer_state(False, "FOCUS"))
        self.assertFalse(app.strict_block["active"])
        self.start()
        self.assertEqual(self.api.get_friction_rules()["unlocksLeft"], 1)

    def test_drift_logging(self):
        self.start()
        self.drift()
        self.api.back_to_focus()
        self.clock.now += 120
        self.drift("Reddit")
        self.assertTrue(self.api.verify_friction_goal(GOAL, 1)["success"])
        self.assertEqual(self.drifts(), [("Instagram", 0, "back"), ("Reddit", 1, "typed")])

    # --- the block lock ---
    def test_no_early_stop_pause_or_break(self):
        self.start()
        self.assertTrue(app.strict_block["active"])
        self.clock.now += 60
        self.assertFalse(self.api.set_timer_state(False, "FOCUS"), "early stop refused")
        self.assertFalse(self.api.set_timer_state(False, "FOCUS", True), "pause refused")
        self.assertFalse(self.api.set_timer_state(True, "SHORT_BREAK"), "break refused")
        self.assertTrue(app.timer_is_running, "blocking stays on")
        self.assertEqual(app.active_session_config["sessionType"], "FOCUS")

    def test_block_ends_when_time_is_up(self):
        self.start()
        self.clock.now += 30 * 60 - 2      # the page finishes a moment after Python's end time
        self.assertTrue(self.api.set_timer_state(False, "FOCUS"))
        self.assertFalse(app.timer_is_running)
        self.assertFalse(app.STRICT_PATH.exists())
        self.assertTrue(self.api.set_timer_state(True, "SHORT_BREAK"))

    def test_settings_locked_during_block(self):
        self.start()
        self.assertFalse(self.api.save_session_config({"strictness": "1", "goal": "anything"}))
        self.assertEqual(app.current_level(), "3")
        self.assertEqual(app.active_session_config["goal"], GOAL)
        self.clock.now += 30 * 60
        self.assertTrue(self.api.save_session_config({"goal": "next"}))

    def test_page_reload_picks_the_block_up(self):
        self.start()
        self.clock.now += 10 * 60
        # the page reloads: on load it asks Python first, and the stop it used to send is refused anyway
        info = self.api.get_strict_block()
        self.assertTrue(info["active"])
        self.assertEqual(info["remaining"], 20 * 60)
        self.assertEqual(info["planned"], 30 * 60)
        self.assertFalse(self.api.set_timer_state(False, "FOCUS"))
        self.assertTrue(self.api.set_timer_state(True, "FOCUS", True))   # the page resumes the timer
        self.assertEqual(self.api.get_strict_block()["remaining"], 20 * 60)

    def test_restart_without_resume_flag_keeps_the_used_break(self):
        self.start()
        self.drift()
        self.assertTrue(self.api.verify_friction_goal(GOAL, 1)["success"])
        app.timer_is_running = False       # e.g. the page lost track and sends a fresh start
        self.assertTrue(self.api.set_timer_state(True, "FOCUS"))
        self.assertEqual(self.api.get_friction_rules()["unlocksLeft"], 0)

    def test_desk_pause_stops_the_block_clock(self):
        self.start()
        self.clock.now += 5 * 60
        app.desk["hold"] = True            # you left the desk: the desk check pauses the timer
        self.assertTrue(self.api.set_timer_state(False, "FOCUS", True))
        self.clock.now += 10 * 60
        self.assertEqual(self.api.get_strict_block()["remaining"], 25 * 60)
        app.desk["hold"] = False
        self.assertTrue(self.api.set_timer_state(True, "FOCUS", True))
        self.clock.now += 10 * 60
        self.assertEqual(self.api.get_strict_block()["remaining"], 15 * 60)

    def test_alarm_screen_end_is_allowed_and_logged(self):
        self.start()
        self.clock.now += 60
        self.api.desk_end_block()
        self.assertTrue(self.api.set_timer_state(False, "FOCUS"))
        self.assertFalse(app.strict_block["active"])
        self.assertIn((app.STRICT_ALARM_END_LOG_NAME, 0, None), self.drifts())

    # --- quitting ---
    def test_closing_the_window_is_refused(self):
        self.start()
        self.assertFalse(app._confirm_quit())
        self.inform.assert_called_once()
        self.assertIn("30 min", self.inform.call_args[0][1])
        app.platform_bridge.confirm.assert_not_called()

    def test_quitting_allowed_after_the_block(self):
        self.start()
        self.clock.now += 30 * 60
        app.timer_is_running = False
        self.assertTrue(app._confirm_quit())
        self.inform.assert_not_called()

    def test_window_closed_anyway_does_not_log_stopped_early(self):
        self.start()
        self.clock.now += 5 * 60
        app.live_session = {"mode": "FOCUS", "planned": 1800, "actual": 300, "started": 1}
        with mock.patch.object(app, "presence_watcher", None), mock.patch.object(app, "api_instance", self.api):
            app._on_main_closed()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM periods")[0][0], 0)
        self.assertTrue(app.STRICT_PATH.exists(), "the block is kept for the next launch")

    def test_force_quit_then_reopen_carries_on(self):
        self.start()
        self.drift()
        self.assertTrue(self.api.verify_friction_goal(GOAL, 1)["success"])
        self.clock.now += 8 * 60
        self.assertEqual(self.relaunch(), "resumed")
        self.assertTrue(app.timer_is_running, "blocking is back on straight away")
        self.assertEqual(app.current_level(), "3")
        self.assertEqual(app.active_session_config["goal"], GOAL)
        self.assertEqual(app.active_session_config["blocklist"], ["Instagram", "Reddit"])
        self.assertEqual(self.api.get_strict_block()["remaining"], 22 * 60, "time closed counts down")
        self.assertEqual(self.api.get_friction_rules()["unlocksLeft"], 0, "the break isn't given back")
        self.assertIn((app.STRICT_QUIT_LOG_NAME, 0, None), self.drifts())
        self.assertFalse(self.api.set_timer_state(False, "FOCUS"))

    def test_reopen_after_the_block_ran_out_logs_it(self):
        self.start()
        self.clock.now += 6 * 60
        self.api.note_progress("FOCUS", 1800, 360, 1)   # last sign of life 6 minutes in
        self.clock.now += 60 * 60          # reopened an hour later
        self.assertEqual(self.relaunch(), "logged")
        self.assertFalse(app.timer_is_running)
        self.assertFalse(app.STRICT_PATH.exists())
        rows = self.rows("SELECT planned_sec, actual_sec, outcome, level FROM periods")
        self.assertEqual(rows, [(1800, 360, "Stopped Early", "School")])
        self.assertIn((app.STRICT_QUIT_LOG_NAME, 0, None), self.drifts())

    def test_damaged_file_is_ignored(self):
        app.STRICT_PATH.write_text("{not json", encoding="utf-8")
        self.assertIsNone(app.restore_strict_block())
        self.assertFalse(app.timer_is_running)
        self.assertIsNone(app.restore_strict_block(), "no file: nothing to do")


    # --- added after end-to-end runs ---
    def test_watchdog_ends_a_block_nobody_is_watching(self):
        self.start()
        self.relaunch()
        self.clock.now += 40 * 60          # nobody signed in, the block's time ran out
        self.assertTrue(app.strict_watchdog())
        self.assertFalse(app.timer_is_running, "blocking stops")
        self.assertEqual(self.rows("SELECT outcome, level FROM periods"), [("Completed", "School")])
        started = self.api.get_strict_block()   # no block any more
        self.assertFalse(started["active"])
        self.api.log_session("FOCUS", 1800, 1800, app.strict_logged_start_ms)   # the page shows up late
        self.assertEqual(len(self.rows("SELECT * FROM periods")), 1, "not logged twice")

    def test_watchdog_leaves_it_to_an_open_timer_page(self):
        self.start()
        self.clock.now += 30 * 60 - 20
        self.api.note_progress("FOCUS", 1800, 1780, 1)
        self.clock.now += 30
        self.assertFalse(app.strict_watchdog())
        self.assertTrue(app.timer_is_running, "the page finishes the block itself")

    def test_study_override_off_at_level3(self):
        self.start()
        app.last_video_insight = {"drift_id": 1, "title": "Funny cats", "kind": "video"}
        self.assertFalse(self.api.mark_video_as_study()["success"])
        self.assertNotIn("Funny cats", app.smart_state["overrides"])

    def test_page_retry_after_python_refused_early_finish(self):
        self.start()
        self.clock.now += 30 * 60 - 20     # the page thinks it's done 20 s early
        self.assertFalse(self.api.set_timer_state(False, "FOCUS"))
        self.clock.now += 20
        self.assertTrue(self.api.set_timer_state(False, "FOCUS"))
        self.assertFalse(app.timer_is_running)

    # --- the popup ---
    def test_popup_red_x_means_back_to_focus(self):
        self.start()
        self.drift()
        with mock.patch.object(app, "api_instance", self.api):
            app._friction_closed_by_user()
        self.assertFalse(app.is_friction_active)
        app.platform_bridge.hide_app.assert_called_once_with("Instagram")
        self.assertEqual(self.drifts()[-1][2], "back")

    def test_rules_sent_to_the_popup(self):
        rules = self.api.get_friction_rules()
        self.assertEqual((rules["level"], rules["mode"], rules["maxGrace"]), ("3", "School", 1.0))
        self.assertTrue(rules["exactMatch"])
        self.assertTrue(rules["needsTyping"])

    # --- Level 2 is not affected ---
    def test_level2_has_no_lock(self):
        self.api.save_session_config({"strictness": "2"})
        self.start()
        self.assertFalse(app.strict_block["active"])
        self.assertFalse(app.STRICT_PATH.exists())
        self.assertTrue(self.api.set_timer_state(False, "FOCUS", True), "Level 2 can pause")
        self.assertTrue(self.api.set_timer_state(False, "FOCUS"), "Level 2 can stop early")
        self.drift()
        with mock.patch.object(app, "api_instance", self.api):
            app._friction_closed_by_user()
        app.platform_bridge.hide_app.assert_not_called()   # Level 2 red X only closes the popup, as before


if __name__ == "__main__":
    unittest.main()
