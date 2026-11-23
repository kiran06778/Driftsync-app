"""Runs on a REAL Windows PC (GitHub Actions windows-latest, or your partner's laptop):
    python tests\\windows_smoke.py
Calls the real Windows code (registry, user32, Core Audio, PowerShell) and prints what it found.
Nothing is changed: volume is only read, no notification settings are written."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import platform_bridge as pb  # noqa: E402

assert pb.IS_WINDOWS, "run this on Windows"
results = []


def check(name, fn):
    t = time.time()
    try:
        value = fn()
        results.append((name, "OK", value))
    except Exception as e:
        results.append((name, "FAIL", repr(e)))
    print(f"{results[-1][1]:4}  {name}: {results[-1][2]}  ({time.time() - t:.2f}s)", flush=True)


check("WebView2 installed", pb.webview2_installed)
check("foreground window", pb.get_active_window_info)
check("idle seconds", pb.idle_seconds)
check("notification status", pb.notification_status)
check("camera privacy", pb.win_camera_privacy)
check("camera apps running", pb.camera_apps_running)
check("battery", pb.on_battery)
check("speaker volume (Core Audio)", pb._win_get_volume)
check("edge title cleanup", lambda: pb._win_clean_title(
    "microsoft edge", "Lofi - YouTube and 2 more pages - Personal - Microsoft​ Edge"))
check("alarm wav", pb._alarm_wav)
check("chime", pb.chime)


def toast():
    import subprocess
    import os
    env = dict(os.environ, DS_TITLE="DriftSync test", DS_MSG="Windows smoke test")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", pb._WIN_TOAST], env=env, capture_output=True, text=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return "toast sent"


check("PowerShell toast script", toast)


def volume_roundtrip():
    before = pb._win_get_volume()
    if before is None:
        return "no audio device (skipped)"
    pb._win_set_volume(*before)          # writes back the same value: nothing audible changes
    after = pb._win_get_volume()
    assert after == before, (before, after)
    return f"read/write OK at {before}"


check("speaker volume write-back", volume_roundtrip)

failed = [r for r in results if r[1] == "FAIL"]
print(f"\n{len(results) - len(failed)} of {len(results)} checks OK")
sys.exit(1 if failed else 0)
