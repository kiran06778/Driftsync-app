"""DriftSync setup check: can this computer run DriftSync?

    python3 check_setup.py           full report
    python3 check_setup.py --quiet   print only problems (the launchers use this); exit code 1 if DriftSync can't start

It only looks things up (nothing is installed or changed) and takes well under a second.
"""
import importlib.util
import os
import platform
import shutil
import sys

MIN_PY = (3, 9)
QUIET = "--quiet" in sys.argv
problems, warnings, oks = [], [], []


def has(module):
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


# --- Python ---
py = sys.version_info
if py < MIN_PY:
    problems.append(f"Python {py.major}.{py.minor} is too old. Install Python 3.9 or newer from python.org.")
else:
    oks.append(f"Python {py.major}.{py.minor}.{py.micro}")

# --- Operating system ---
system = platform.system()
if system == "Darwin":
    ver = platform.mac_ver()[0] or "?"
    try:
        major = int(ver.split(".")[0])
    except ValueError:
        major = 0
    if major and major < 11:
        warnings.append(f"macOS {ver}: DriftSync is tested on macOS 11 (Big Sur) and newer.")
    else:
        oks.append(f"macOS {ver}")
elif system == "Windows":
    release = platform.release()
    if release not in ("10", "11"):
        warnings.append(f"Windows {release}: DriftSync needs Windows 10 or 11.")
    else:
        oks.append(f"Windows {release}")
    # The window is drawn by Microsoft Edge WebView2 (built into up-to-date Windows 10/11)
    webview2 = False
    try:
        import winreg
        key = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        for hive, path in ((winreg.HKEY_LOCAL_MACHINE, key), (winreg.HKEY_CURRENT_USER, key.replace("WOW6432Node\\", ""))):
            try:
                with winreg.OpenKey(hive, path) as k:
                    if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                        webview2 = True
                        break
            except OSError:
                pass
    except Exception:
        webview2 = True   # can't tell: don't block the start
    if webview2:
        oks.append("Edge WebView2 runtime")
    else:
        problems.append("Microsoft Edge WebView2 runtime is missing. Install it from "
                        "https://developer.microsoft.com/microsoft-edge/webview2/ (Evergreen Bootstrapper).")
else:
    warnings.append(f"{system}: DriftSync supports macOS and Windows. The window may open, but distraction "
                    "blocking won't work here.")

# --- Packages ---
for module, pip_name, needed in (("webview", "pywebview", True), ("psutil", "psutil", True),
                                 ("certifi", "certifi", False), ("cv2", "opencv-python", False)):
    if has(module):
        oks.append(pip_name)
    elif needed:
        problems.append(f"{pip_name} is not installed. Run: pip install -r requirements.txt")
    elif module == "cv2":
        warnings.append("opencv-python is not installed, so the webcam Desk check is off. Everything else works.")
    else:
        warnings.append(f"{pip_name} is not installed (AI features may fail to connect). Run: pip install -r requirements.txt")

if system == "Windows" and has("webview") and not has("clr"):
    problems.append("pythonnet is missing (pywebview needs it on Windows). Run: pip install -r requirements.txt")
if system == "Windows" and platform.machine().upper() == "ARM64":
    warnings.append("Windows on ARM: the webcam Desk check has no build for ARM yet, so it is off. "
                    "Everything else works.")

# --- Hardware ---
try:
    import psutil
    ram_gb = psutil.virtual_memory().total / 1024 ** 3
    if ram_gb < 3.5:
        warnings.append(f"{ram_gb:.1f} GB RAM: DriftSync runs, but 4 GB or more is recommended.")
    else:
        oks.append(f"{ram_gb:.0f} GB RAM")
except Exception:
    pass
cores = os.cpu_count() or 0
if cores and cores < 2:
    warnings.append("1 CPU core: expect a slow start. 2 or more cores are recommended.")
elif cores:
    oks.append(f"{cores} CPU threads" + (" (lite visuals will be used)" if cores <= 4 else ""))
try:
    free_mb = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__))).free / 1024 ** 2
    if free_mb < 200:
        warnings.append(f"Only {free_mb:.0f} MB free disk space. Keep at least 200 MB free for the database and logs.")
except Exception:
    pass

# --- Optional extras ---
here = os.path.dirname(os.path.abspath(__file__))
if not (os.path.exists(os.path.join(here, ".env")) or os.path.exists(os.path.join(here, ".env.txt"))):
    warnings.append("No .env file: the AI coach and AI timetable use their offline versions. "
                    "Add GROQ_API_KEY=... to a .env file to turn on the AI.")

# --- Report ---
if not QUIET:
    print("DriftSync setup check\n")
    for line in oks:
        print(f"  OK    {line}")
for line in warnings:
    if not QUIET:
        print(f"  NOTE  {line}")
for line in problems:
    print(f"  FIX   {line}")
if not QUIET:
    print("\nReady to run DriftSync." if not problems else "\nFix the items marked FIX, then start DriftSync again.")
sys.exit(1 if problems else 0)
