"""Leaderboard: every account on this computer ranked by focus score, minutes, streak or accuracy.
Run from the project folder:  python3 -m unittest discover tests -v"""
import sys
import types
import unittest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("webview", types.ModuleType("webview"))
import desktop_app as app  # noqa: E402

NOW = datetime(2026, 11, 22, 18, 0, 0)


class LeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_db = app.DB_PATH
        self.addCleanup(setattr, app, "DB_PATH", self.old_db)
        app.DB_PATH = Path(self.tmp.name) / "test.db"
        app.init_db()
        self.ids = {}
        for name in ("asha", "ben", "chen"):
            self.ids[name] = self.user(name)

    def user(self, name):
        conn = app.db_connect()
        cur = conn.execute("INSERT INTO users (username, password_hash, salt) VALUES (?, 'x', 'y')", (name,))
        conn.commit()
        conn.close()
        return cur.lastrowid

    def block(self, name, days_ago, minutes, outcome="Completed", mode="focus", hour=10):
        start = (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0)
        end = start + timedelta(minutes=minutes)
        conn = app.db_connect()
        conn.execute('''INSERT INTO periods (user_id, mode, planned_sec, actual_sec, started_at, ended_at, outcome, level)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'College')''',
                     (self.ids[name], mode, minutes * 60, minutes * 60, start.strftime('%Y-%m-%d %H:%M:%S'),
                      end.strftime('%Y-%m-%d %H:%M:%S'), outcome))
        conn.commit()
        conn.close()
        return start

    def drift(self, name, at, on_topic=0, allowed=0):
        conn = app.db_connect()
        conn.execute("INSERT INTO drifts (user_id, timestamp, app_name, unlocked, on_topic, allowed) VALUES (?, ?, 'YouTube', 0, ?, ?)",
                     (self.ids[name], at.strftime('%Y-%m-%d %H:%M:%S'), on_topic, allowed))
        conn.commit()
        conn.close()

    def board(self, period="week", metric="score", me="asha"):
        return app.leaderboard_data(period, metric, self.ids.get(me, 0), now=NOW)

    def row(self, data, name):
        return next(r for r in data["rows"] if r["name"] == name)

    def test_empty_board_lists_everyone_with_zeroes(self):
        data = self.board()
        self.assertEqual(data["totalUsers"], 3)
        self.assertTrue(all(r["score"] == 0 and r["accuracy"] is None for r in data["rows"]))
        self.assertEqual({r["rank"] for r in data["rows"]}, {1})   # all tied
        self.assertTrue(data["me"]["isMe"])

    def test_score_is_minutes_times_accuracy(self):
        start = self.block("asha", 0, 60)
        self.drift("asha", start + timedelta(minutes=5))
        self.drift("asha", start + timedelta(minutes=9))
        r = self.row(self.board(), "asha")
        self.assertEqual((r["minutes"], r["drifts"], r["accuracy"], r["score"]), (60, 2, 90, 54))

    def test_ranked_by_score_then_metric_switch(self):
        start = self.block("asha", 0, 60)
        for m in range(10):                                   # 50% accuracy -> score 30
            self.drift("asha", start + timedelta(minutes=m + 1))
        self.block("ben", 0, 40)                              # 100% -> score 40
        data = self.board()
        self.assertEqual([r["name"] for r in data["rows"]][:2], ["ben", "asha"])
        self.assertEqual(data["me"]["rank"], 2)
        self.assertEqual(data["gap"], {"name": "ben", "amount": 11})
        by_minutes = self.board(metric="minutes")
        self.assertEqual(by_minutes["rows"][0]["name"], "asha")
        self.assertIsNone(by_minutes["gap"])

    def test_invalid_blocks_breaks_and_allowed_drifts_dont_count(self):
        self.block("asha", 0, 1, outcome="Invalid", hour=8)
        self.block("asha", 0, 15, mode="short_break", hour=9)
        start = self.block("asha", 0, 30, hour=11)
        self.drift("asha", start + timedelta(minutes=1), allowed=1)
        self.drift("asha", start + timedelta(minutes=2), on_topic=1)
        r = self.row(self.board(), "asha")
        self.assertEqual((r["minutes"], r["blocks"], r["drifts"], r["score"]), (30, 1, 0, 30))

    def test_period_filters_minutes_but_streaks_are_all_time(self):
        for d in range(0, 10):            # ten days in a row, ending today
            self.block("chen", d, 30)
        week = self.row(self.board("week"), "chen")
        month = self.row(self.board("month"), "chen")
        self.assertEqual(week["minutes"], 7 * 30)
        self.assertEqual(month["minutes"], 10 * 30)
        self.assertEqual((week["streak"], week["bestStreak"]), (10, 10))

    def test_streak_survives_until_today_ends_and_breaks_after_a_gap(self):
        self.block("asha", 1, 30)
        self.block("asha", 2, 30)       # yesterday + day before: streak still alive today
        self.block("ben", 2, 30)
        self.block("ben", 3, 30)        # last block two days ago: streak broken
        self.block("ben", 5, 30)
        data = self.board()
        self.assertEqual((self.row(data, "asha")["streak"], self.row(data, "asha")["bestStreak"]), (2, 2))
        self.assertEqual((self.row(data, "ben")["streak"], self.row(data, "ben")["bestStreak"]), (0, 2))

    def test_accuracy_ranking_puts_people_without_blocks_last(self):
        start = self.block("ben", 0, 30)
        self.drift("ben", start + timedelta(minutes=3))
        data = self.board(metric="accuracy")
        self.assertEqual(data["rows"][0]["name"], "ben")
        self.assertEqual(data["rows"][0]["rank"], 1)
        self.assertTrue(all(r["rank"] == 2 for r in data["rows"][1:]))

    def test_personal_bests(self):
        self.block("asha", 3, 50, hour=9)
        self.block("asha", 3, 40, hour=14)
        self.block("asha", 40, 70)        # outside 30 days, still a personal best
        r = self.row(self.board("week"), "asha")
        self.assertEqual((r["bestDayMin"], r["longestBlockMin"]), (90, 70))

    def test_drift_in_overlapping_blocks_counts_once(self):
        a = self.block("asha", 0, 60, hour=10)
        self.block("asha", 0, 30, hour=10, outcome="Stopped Early")   # same start: newest-start rule picks one
        conn = app.db_connect()
        conn.execute("UPDATE periods SET started_at = ? WHERE id = 2", ((a + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
        conn.close()
        self.drift("asha", a + timedelta(minutes=15))
        self.assertEqual(self.row(self.board(), "asha")["drifts"], 1)

    def test_bad_arguments_fall_back_and_api_never_raises(self):
        data = self.board(period="year", metric="vibes")
        self.assertEqual((data["period"], data["metric"]), ("week", "score"))
        app.current_user = {"id": self.ids["ben"], "username": "ben"}
        self.addCleanup(setattr, app, "current_user", None)
        out = app.Api().get_leaderboard("all", "streak")
        self.assertEqual(out["me"]["name"], "ben")
        app.DB_PATH = Path(self.tmp.name) / "missing" / "nope.db"
        self.assertTrue(app.Api().get_leaderboard()["error"])

    def test_every_app_page_links_to_the_leaderboard(self):
        root = Path(app.__file__).resolve().parent
        for page in ("index.html", "setup.html", "timetable.html", "insights.html", "leaderboard.html"):
            html = (root / page).read_text(encoding="utf-8")
            self.assertIn('href="leaderboard.html"', html, page)
            self.assertNotIn("Leaderboard coming soon", html, page)


if __name__ == "__main__":
    unittest.main()
