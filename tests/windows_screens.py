"""Screenshots of the REAL DriftSync window on Windows (used by the GitHub Windows check).
    python tests\\windows_screens.py  -> windows-run\\*.png
Uses the real Api and the real WebView2 window; a throwaway account in a temporary database."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import webview  # noqa: E402
import desktop_app as app  # noqa: E402
from PIL import ImageGrab  # noqa: E402

OUT = ROOT / "windows-run"
OUT.mkdir(exist_ok=True)
app.DB_PATH = Path(tempfile.mkdtemp()) / "screens.db"
app.PREFS_PATH = Path(tempfile.mkdtemp()) / "prefs.json"
app.init_db()
api = app.Api()
app.api_instance = api
api.register_user("demo", None, "demo1234", "demo1234")


def shot(win, name, wait=4.0):
    time.sleep(wait)
    try:
        x, y = win.x, win.y
        w, h = win.width, win.height
        img = ImageGrab.grab(all_screens=True)
        # crop to the window when the numbers look sane, else keep the whole screen
        if w > 200 and h > 200:
            img = img.crop((max(0, x), max(0, y), max(0, x) + w, max(0, y) + h)) if x >= 0 and y >= 0 else img
        img.save(OUT / f"{name}.png")
        print(f"saved {name}.png ({w}x{h} at {x},{y})", flush=True)
    except Exception as e:
        print(f"screenshot {name} failed: {e}", flush=True)


def run(win):
    try:
        shot(win, "1-sign-in", 6)
        api.login_user("demo", "demo1234")
        for name, page in (("2-focus-timer", "index.html"), ("3-setup", "setup.html"),
                           ("4-insights", "insights.html"), ("5-timetable", "timetable.html"),
                           ("6-leaderboard", "leaderboard.html")):
            win.load_url((ROOT / page).as_uri())
            shot(win, name)
        # A real Windows permission flow: turn on Desk check on a PC with no camera -> the in-app message
        win.load_url((ROOT / "setup.html").as_uri())
        time.sleep(4)
        win.evaluate_js("""(async () => {
            await window.pywebview.api.set_pref('deskIntroSeen', true);
            const box = document.getElementById('deskCheckToggle');
            box.scrollIntoView({block: 'center'});
            box.checked = true; box.dispatchEvent(new Event('change'));
        })()""")
        shot(win, "7-camera-prompt", 14)   # the camera probe takes a few seconds to give up
        win.evaluate_js("(async () => { if (window.dsPermissions) await dsPermissions.info(true); })()")
        print("platform info:", api.get_platform_info(), flush=True)
    finally:
        time.sleep(1)
        win.destroy()


if __name__ == "__main__":
    w = webview.create_window("DriftSync", (ROOT / "login.html").as_uri(), width=1100, height=760, x=0, y=0,
                              js_api=api)
    webview.start(run, w)
