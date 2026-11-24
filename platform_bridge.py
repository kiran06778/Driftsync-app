"""Everything that differs between macOS and Windows lives here.

desktop_app.py and video_insight.py call these functions and never touch osascript or Win32 directly.

    get_active_window_info()  -> "App Name | Window Title" ("" when it can't be read)
    check_permissions()       -> True when DriftSync may read the foreground window
    bring_app_to_front(pid)   -> raise this process' windows above the distracting app
    hide_app(app_name)        -> minimise/hide the app the user drifted into
    read_browser_tab(app)     -> (title, url) of the active browser tab, ("", "") if unavailable
    notify(title, message)    -> system banner for Level 1 soft reminders (False if it couldn't be shown)
    chime()                   -> short system sound for Level 1 soft reminders (False if it couldn't play)
    idle_seconds()            -> seconds since the last key press or mouse move (None if unknown)
    request_camera_access()   -> asks the OS for the camera (OK / Cancel prompt); True when DriftSync may use it
    camera_problem()          -> Windows: why the camera can't open (privacy switch / another app / none), for the page
    notification_status()     -> Windows: are notifications on? enable_notifications() switches them on (after a yes)
    webview2_installed()      -> Windows: is the Edge WebView2 runtime there (else pywebview falls back to old IE)
    start_alarm/stop_alarm()  -> desk check alarm; turns the speakers up (macOS AppleScript, Windows Core Audio) and back

The Windows code uses only ctypes, winreg and psutil (already in requirements.txt), so it needs no extra install.
App names come back in the same style as macOS ("google chrome", "microsoft edge") so the blocklist
matching in desktop_app.py works unchanged.
"""
import os
import re
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


# ======================================================================
# macOS  (AppleScript)
# ======================================================================
def _osa(script, timeout=3, capture=True):
    return subprocess.run(["osascript", "-e", script], capture_output=capture, text=True, timeout=timeout)


def _mac_check_permissions():
    script = """
    tell application "System Events"
        try
            set frontProc to first application process whose frontmost is true
            set winCount to count of windows of frontProc
            return "OK"
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
    """
    try:
        res = _osa(script)
        if res.returncode != 0 or res.stdout.strip() != "OK":
            print(f"[PERMISSION] check failed: {(res.stdout or res.stderr).strip()[:200]}", flush=True)
            _mac_permission_modal()
            return False
        return True
    except Exception:
        _mac_permission_modal()
        return False


_perm_modal_shown = False
_cam_modal_shown = False


def _mac_permission_modal():
    """Short OK / Cancel. OK opens the Accessibility settings page. Shown once per run: pressing Start again
    after a Cancel must not pop it up every time (the page shows a one-line hint instead)."""
    global _perm_modal_shown
    if _perm_modal_shown:
        return
    _perm_modal_shown = True
    app = _host_app_name().replace('"', '')
    modal_script = f'''
    tell application "System Events"
        activate
        set response to button returned of (display dialog "DriftSync needs Accessibility access to block distracting apps.\\n\\nClick OK, then turn on {app}." buttons {{"Cancel", "OK"}} default button "OK" with icon 2 with title "Accessibility Access")
        if response is "OK" then
            do shell script "open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
        end if
    end tell
    '''
    try:
        _osa(modal_script, timeout=120, capture=False)
    except Exception:
        pass


def _mac_active_window_info():
    script = """
    tell application "System Events"
        try
            set frontProc to first application process whose frontmost is true
            set appName to name of frontProc
            set winTitle to ""
            tell frontProc
                if (count of windows) > 0 then
                    set winTitle to name of window 1
                end if
            end tell
            return appName & " | " & winTitle
        on error errMsg
            return "ERR: " & errMsg
        end try
    end tell
    """
    try:
        res = _osa(script, timeout=5)
        out = res.stdout.strip()
        if res.returncode != 0 or not out or out.startswith("ERR:"):
            print(f"[RADAR DEBUG] empty scan | rc={res.returncode} | {(out or res.stderr.strip())[:200]}", flush=True)
            return ""
        return out
    except subprocess.TimeoutExpired:
        print("[RADAR DEBUG] osascript timed out (>5s)", flush=True)
        return ""
    except Exception as e:
        print(f"[RADAR DEBUG] scan failed: {e}", flush=True)
        return ""


def _mac_bring_to_front(pid):
    cmd = f'''
    tell application "System Events"
        set frontmost of every process whose unix id is {pid} to true
    end tell
    '''
    _osa(cmd)


def _mac_hide_app(app):
    app = (app or "").replace('"', '').replace('\\', '')
    if app:
        _osa(f'tell application "System Events" to set visible of (first process whose name is "{app}") to false')


_SAFARI_LIKE = {"safari", "safari technology preview", "orion"}
_CHROMIUM_LIKE = {"google chrome", "google chrome canary", "chromium", "brave browser",
                  "microsoft edge", "arc", "vivaldi", "opera", "dia", "comet"}


def _mac_read_browser_tab(app_name, timeout=4):
    app = (app_name or "").strip().replace('"', '')
    key = app.lower()
    if key in _SAFARI_LIKE:
        tab = "current tab of front window"
        script = f'tell application "{app}" to return (name of {tab}) & linefeed & (URL of {tab})'
    elif key in _CHROMIUM_LIKE:
        tab = "active tab of front window"
        script = f'tell application "{app}" to return (title of {tab}) & linefeed & (URL of {tab})'
    else:
        return "", ""      # Firefox and others have no AppleScript tab access: use the window title
    try:
        res = _osa(script, timeout=timeout)
        if res.returncode != 0:
            return "", ""
        title, _, url = res.stdout.rstrip("\n").partition("\n")
        return title.strip(), url.strip()
    except Exception:
        return "", ""


# ======================================================================
# Windows  (ctypes + psutil, no extra packages)
# ======================================================================
# process name -> the macOS-style name the blocklist matching expects
_WIN_APP_NAMES = {
    "chrome.exe": "google chrome",
    "msedge.exe": "microsoft edge",
    "firefox.exe": "firefox",
    "brave.exe": "brave browser",
    "opera.exe": "opera",
    "opera_gx.exe": "opera",
    "vivaldi.exe": "vivaldi",
    "arc.exe": "arc",
    "zen.exe": "zen browser",
    "duckduckgo.exe": "duckduckgo",
    "chromium.exe": "chromium",
    "comet.exe": "comet",
}


def _win_friendly_name(exe):
    exe = (exe or "").strip()
    low = exe.lower()
    if low in _WIN_APP_NAMES:
        return _WIN_APP_NAMES[low]
    return low[:-4] if low.endswith(".exe") else low


def _win_foreground():
    """(hwnd, pid, title) of the foreground window, or None."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, pid.value, buf.value


# Windows browsers put extra parts in their window titles that macOS doesn't have:
#   Edge:    "Lofi beats - YouTube and 3 more pages - Personal - Microsoft​ Edge"  (zero-width space, profile name)
#   Chrome:  "Lofi beats - YouTube - Google Chrome"  (some versions add " - <profile>" at the end)
#   Firefox: "Lofi beats - YouTube — Mozilla Firefox Private Browsing"
# They are cleaned to "Lofi beats - YouTube - Microsoft Edge", the shape the blocklist and video code expect.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿"), None)
_MORE_TABS = re.compile(r"\s+and\s+\d+\s+more\s+(pages?|tabs?)\s*$", re.IGNORECASE)
_PROFILE_BROWSERS = {   # friendly app name -> (title suffix, folder under %LOCALAPPDATA% with "Local State")
    "microsoft edge": ("Microsoft Edge", r"Microsoft\Edge\User Data"),
    "google chrome": ("Google Chrome", r"Google\Chrome\User Data"),
    "brave browser": ("Brave", r"BraveSoftware\Brave-Browser\User Data"),
}
_DEFAULT_PROFILES = {"personal", "work", "default", "guest", "inprivate", "person 1", "your chrome"}
_profile_cache = {}


def _browser_profile_names(app):
    """Profile names the browser shows in its window titles (read once from its "Local State" file)."""
    if app in _profile_cache:
        return _profile_cache[app]
    names = set(_DEFAULT_PROFILES) | {f"profile {i}" for i in range(1, 10)}
    folder = _PROFILE_BROWSERS.get(app, (None, None))[1]
    base = os.environ.get("LOCALAPPDATA", "")
    if folder and base:
        try:
            import json
            with open(os.path.join(base, folder, "Local State"), encoding="utf-8") as f:
                cache = (json.load(f).get("profile") or {}).get("info_cache") or {}
            for info in cache.values():
                for key in ("name", "gaia_name", "shortcut_name"):
                    if info.get(key):
                        names.add(str(info[key]).strip().lower())
        except Exception:
            pass
    _profile_cache[app] = names
    return names


def _win_clean_title(app, title):
    title = (title or "").translate(_INVISIBLE).strip()
    suffix = _PROFILE_BROWSERS.get(app, (None,))[0]
    if not suffix:
        return title
    parts = re.split(r"\s+[-–—]\s+", title)
    if len(parts) < 2:
        return title
    profiles = _browser_profile_names(app)
    tail = []
    # "... - Google Chrome - Kiran": the profile comes after the browser name
    if len(parts) >= 3 and parts[-2].lower() == suffix.lower() and parts[-1].strip().lower() in profiles:
        parts = parts[:-1]
    if parts[-1].lower() == suffix.lower():
        tail = [suffix]
        parts = parts[:-1]
        # "... - Personal - Microsoft Edge": the profile comes before it
        if len(parts) >= 2 and parts[-1].strip().strip("[]").lower() in profiles:   # "[InPrivate]" too
            parts = parts[:-1]
    if parts:
        parts[-1] = _MORE_TABS.sub("", parts[-1])
    return " - ".join(parts + tail)


_last_foreground = {}   # friendly app name -> its last foreground window (to minimise Store apps later)


def _win_active_window_info():
    try:
        import psutil
        fg = _win_foreground()
        if not fg:
            return ""
        hwnd, pid, title = fg
        name = _win_friendly_name(psutil.Process(pid).name())
        title = _win_clean_title(name, title)
        # Store apps (Calculator, Settings...) all report ApplicationFrameHost
        if name == "applicationframehost":
            name = title.lower() or name
        _last_foreground[name] = hwnd
        return f"{name} | {title}"
    except Exception as e:
        print(f"[RADAR DEBUG] scan failed: {e}", flush=True)
        return ""


def _win_windows_of(pid=None, exe_name=None):
    """All visible top-level window handles owned by a pid or by a process name."""
    import ctypes
    from ctypes import wintypes
    import psutil
    user32 = ctypes.windll.user32
    found = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        try:
            if pid is not None and p.value == pid:
                found.append(hwnd)
            elif exe_name is not None and _win_friendly_name(psutil.Process(p.value).name()) == exe_name:
                found.append(hwnd)
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return found


def _win_bring_to_front(pid):
    """Raises DriftSync above the app you drifted into. Windows normally refuses this to a background
    process, so we briefly join the input of the window in front (the usual, documented workaround);
    the old "press Alt" trick is only the fallback, because Alt opens the menu bar in Firefox and Office."""
    import ctypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    windows = _win_windows_of(pid=pid)   # top of the stack first: the on-top popup comes before the main window
    if not windows:
        return False
    hwnd = windows[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    if not ok:
        user32.keybd_event(0x12, 0, 0, 0)    # Alt down / up, then try again
        ok = bool(user32.SetForegroundWindow(hwnd))
        user32.keybd_event(0x12, 0, 2, 0)
    return ok


def _win_hide_app(app):
    import ctypes
    user32 = ctypes.windll.user32
    name = (app or "").strip().lower()
    if not name:
        return
    windows = _win_windows_of(exe_name=name)
    if not windows and _last_foreground.get(name):
        windows = [_last_foreground[name]]   # Store apps (all ApplicationFrameHost): the window we saw in front
    for hwnd in windows:
        user32.ShowWindow(hwnd, 6)   # SW_MINIMIZE


def webview2_installed():
    """Windows: is the Microsoft Edge WebView2 runtime there? (the same registry keys pywebview checks)"""
    if not IS_WINDOWS:
        return True
    try:
        import winreg
    except Exception:
        return True
    for guid in ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",   # runtime, beta
                 "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}"):  # dev, canary
        key = "Microsoft\\EdgeUpdate\\Clients\\" + guid
        for hive, path in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + key),
                           (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + key),
                           (winreg.HKEY_CURRENT_USER, "SOFTWARE\\" + key)):
            if str(_reg_get(path, "pv", hive) or "0.0.0.0") not in ("", "0.0.0.0"):
                return True
    return False


# ======================================================================
# Public API
# ======================================================================
def check_permissions():
    """Windows needs no permission to read the foreground window."""
    if IS_MAC:
        return _mac_check_permissions()
    return True


def get_active_window_info():
    if IS_MAC:
        return _mac_active_window_info()
    if IS_WINDOWS:
        return _win_active_window_info()
    return ""   # Linux is not supported


def bring_app_to_front(pid):
    try:
        if IS_MAC:
            _mac_bring_to_front(pid)
        elif IS_WINDOWS:
            _win_bring_to_front(pid)
    except Exception as e:
        print(f"Error raising window: {e}", flush=True)


def hide_app(app_name):
    try:
        if IS_MAC:
            _mac_hide_app(app_name)
        elif IS_WINDOWS:
            _win_hide_app(app_name)
    except Exception as e:
        print(f"Error hiding {app_name}: {e}", flush=True)


def _applescript_text(text):
    return '"' + str(text or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


# Windows 10/11 toast through the built-in PowerShell (no extra packages). Text comes in through
# environment variables so quotes in a goal can't break the script.
_WIN_TOAST = (
    "$ErrorActionPreference='Stop';"
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
    "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$x=$t.GetElementsByTagName('text');"
    "$x.Item(0).AppendChild($t.CreateTextNode($env:DS_TITLE)) > $null;"
    "$x.Item(1).AppendChild($t.CreateTextNode($env:DS_MSG)) > $null;"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe')"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
)


def notify(title, message, sound=False):
    """System notification (Level 1 reminders). sound=True also plays a sound with it.
    Returns False when no notification could be shown, so the caller can play a sound instead."""
    try:
        if IS_MAC:
            # macOS lists these notifications under "Script Editor" in System Settings > Notifications
            script = f"display notification {_applescript_text(message[:180])} with title {_applescript_text(title)}"
            if sound:
                script += ' sound name "Glass"'
            res = _osa(script)
            return res.returncode == 0
        if IS_WINDOWS:
            if notification_status().get("enabled") is False:
                return False   # Windows would swallow it silently: let the caller play a sound instead
            env = dict(os.environ, DS_TITLE=str(title), DS_MSG=str(message)[:180])
            proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                     "-Command", _WIN_TOAST], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

            def _watch():   # PowerShell takes a second to start: don't hold up the radar, but chime if it failed
                try:
                    if proc.wait(timeout=20) != 0:
                        print("[NOTIFY] Windows toast failed; played a sound instead.", flush=True)
                        chime()
                except Exception:
                    pass
            _threading.Thread(target=_watch, daemon=True).start()
            if sound:
                chime()
            return True
    except Exception as e:
        print(f"Error showing notification: {e}", flush=True)
    return False


# Where Windows keeps the notification switches (all per user, no admin needed)
_WIN_PUSH_KEY = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"
_WIN_NOTIF_KEY = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
_WIN_TOAST_APP = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"   # who sends our toasts


def _reg_get(path, name, hive=None):
    try:
        import winreg
        with winreg.OpenKey(hive or winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def _reg_set_dword(path, name, value):
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))
        return True
    except Exception as e:
        print(f"[NOTIFY] couldn't change a notification setting: {e}", flush=True)
        return False


def notification_status():
    """{"enabled": True / False / None (can't tell), "reason": ..., "canFix": the app can switch it on itself}.
    Windows: notifications can be off for every app, or only for the sender DriftSync uses (PowerShell).
    macOS gives no way to read this, so it's None there and the Setup test shows the result."""
    if not IS_WINDOWS:
        return {"enabled": None, "reason": None, "canFix": False}
    if _reg_get(_WIN_PUSH_KEY, "ToastEnabled") == 0 or _reg_get(_WIN_NOTIF_KEY, "NOC_GLOBAL_SETTING_TOASTS_ENABLED") == 0:
        return {"enabled": False, "reason": "all-off", "canFix": True}
    if _reg_get(_WIN_NOTIF_KEY + "\\" + _WIN_TOAST_APP, "Enabled") == 0:
        return {"enabled": False, "reason": "app-off", "canFix": True}
    return {"enabled": True, "reason": None, "canFix": False}


def enable_notifications():
    """Windows: turns notifications back on for DriftSync's reminders, after the user said yes in the app.
    These are the same per-user switches as Settings > System > Notifications. Returns the new status."""
    if IS_WINDOWS:
        st = notification_status()
        if st["reason"] == "all-off":
            _reg_set_dword(_WIN_PUSH_KEY, "ToastEnabled", 1)
            if _reg_get(_WIN_NOTIF_KEY, "NOC_GLOBAL_SETTING_TOASTS_ENABLED") == 0:
                _reg_set_dword(_WIN_NOTIF_KEY, "NOC_GLOBAL_SETTING_TOASTS_ENABLED", 1)
        if _reg_get(_WIN_NOTIF_KEY + "\\" + _WIN_TOAST_APP, "Enabled") == 0:
            _reg_set_dword(_WIN_NOTIF_KEY + "\\" + _WIN_TOAST_APP, "Enabled", 1)
    return notification_status()


def open_notification_settings():
    """Opens the place where banners can be allowed (macOS: Notifications; Windows: Notifications & actions)."""
    try:
        if IS_MAC:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.notifications"])
            return True
        if IS_WINDOWS:
            os.startfile("ms-settings:notifications")
            return True
    except Exception as e:
        print(f"Error opening notification settings: {e}", flush=True)
    return False


def chime():
    try:
        if IS_MAC:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if IS_WINDOWS:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return True
    except Exception as e:
        print(f"Error playing chime: {e}", flush=True)
    return False


# ======================================================================
# Camera permission (desk check)
# ======================================================================
# Run in a separate Python process so OpenCV asks macOS for the camera from its main thread:
# that is what makes macOS show its own "would like to access the camera" OK / Don't Allow prompt.
_CAMERA_PROBE = (
    "import sys, cv2\n"
    "if sys.platform == 'darwin': backends = [cv2.CAP_AVFOUNDATION]\n"
    "elif sys.platform == 'win32': backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF]\n"   # some laptop cameras only work with one
    "else: backends = [cv2.CAP_ANY]\n"
    "ok = False\n"
    "for b in backends:\n"
    "    cap = cv2.VideoCapture(0, b)\n"
    "    ok = cap.isOpened() and cap.read()[0]\n"
    "    cap.release()\n"
    "    if ok: break\n"
    "sys.exit(0 if ok else 3)\n"
)
_camera_granted = False


def _host_app_name():
    """The app macOS gives the camera permission to: the one DriftSync was started from."""
    if os.environ.get("DRIFTSYNC_LAUNCHER") == "app":
        return "DriftSync"   # opened with DriftSync.app
    term = os.environ.get("TERM_PROGRAM", "")
    return {"Apple_Terminal": "Terminal", "vscode": "Visual Studio Code", "iTerm.app": "iTerm"}.get(term, term or "Terminal")


def _camera_probe():
    env = dict(os.environ)
    env.pop("OPENCV_AVFOUNDATION_SKIP_AUTH", None)   # let OpenCV ask macOS for permission
    try:
        res = subprocess.run([sys.executable, "-c", _CAMERA_PROBE], env=env, timeout=120,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))   # no black box flashing up
        return res.returncode == 0
    except Exception as e:
        print(f"[DESK CHECK] camera probe failed: {e}", flush=True)
        return False


def _mac_camera_denied_dialog():
    """Camera was refused earlier, so macOS won't ask again: our own OK / Cancel opens the right settings page.
    Shown once per run."""
    global _cam_modal_shown
    if _cam_modal_shown:
        return
    _cam_modal_shown = True
    app = _host_app_name().replace('"', '')
    script = f'''
    tell application "System Events"
        activate
        set response to button returned of (display dialog "DriftSync needs your camera for the desk check.\\n\\nClick OK, then turn on {app} in the Camera list." buttons {{"Cancel", "OK"}} default button "OK" with icon 2 with title "Camera Access")
        if response is "OK" then
            do shell script "open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Camera'"
        end if
    end tell
    '''
    try:
        _osa(script, timeout=120, capture=False)
    except Exception:
        pass


_WIN_CAMERA_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


def win_camera_privacy():
    """Windows privacy switches for the camera: "ok", "off-for-all" (Camera access off), "off-for-desktop-apps"
    ("Let desktop apps access your camera" off) or "off-by-admin" (turned off for the whole PC)."""
    if not IS_WINDOWS:
        return "ok"
    try:
        import winreg
        if str(_reg_get(_WIN_CAMERA_KEY, "Value", winreg.HKEY_LOCAL_MACHINE) or "").lower() == "deny":
            return "off-by-admin"
    except Exception:
        pass
    if str(_reg_get(_WIN_CAMERA_KEY, "Value") or "").lower() == "deny":
        return "off-for-all"
    if str(_reg_get(_WIN_CAMERA_KEY + r"\NonPackaged", "Value") or "").lower() == "deny":
        return "off-for-desktop-apps"
    return "ok"


def camera_problem():
    """Why the camera can't be opened, for the in-app message: "privacy" (a Windows switch is off),
    "admin" (off for the whole PC), "busy" (another app holds it; on Windows only one app can use it),
    or "missing" (no camera found)."""
    privacy = win_camera_privacy()
    if privacy == "off-by-admin":
        return {"reason": "admin", "apps": []}
    if privacy != "ok":
        return {"reason": "privacy", "detail": privacy, "apps": []}
    apps = camera_apps_running()
    if apps:
        return {"reason": "busy", "apps": apps}
    return {"reason": "missing", "apps": []}


def open_camera_settings():
    """One click to the exact switch: Windows Camera privacy page / macOS Privacy > Camera."""
    try:
        if IS_WINDOWS:
            os.startfile("ms-settings:privacy-webcam")
            return True
        if IS_MAC:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"])
            return True
    except Exception as e:
        print(f"Error opening camera settings: {e}", flush=True)
    return False


def request_camera_access():
    """True when the camera can be used. The first time on macOS this shows the system's own
    OK / Don't Allow prompt; if it was refused before, an OK / Cancel dialog opens the settings page.
    On Windows there is no system prompt for desktop apps: the page explains what's wrong (camera_problem)."""
    global _camera_granted
    if _camera_granted:
        return True
    if IS_WINDOWS and win_camera_privacy() != "ok":
        return False   # opening it would just fail; the page shows the one switch to turn on
    # macOS may need two tries: the first one shows the prompt, the second opens the camera
    if _camera_probe() or (IS_MAC and _camera_probe()):
        _camera_granted = True
        return True
    if IS_MAC:
        _mac_camera_denied_dialog()
    return False


# ======================================================================
# Warnings: power, other camera apps, yes/no questions
# ======================================================================
def on_battery():
    """True on battery, False when plugged in, None if unknown (desktop PCs, errors)."""
    try:
        if IS_MAC:
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
            if "Battery Power" in out:
                return True
            if "AC Power" in out:
                return False
            return None
        import psutil
        batt = psutil.sensors_battery()
        return None if batt is None else not batt.power_plugged
    except Exception:
        return None


# apps that often hold the camera: process name (lower case) -> what to call it
_CAMERA_APPS = {
    "zoom.us": "Zoom", "zoom": "Zoom", "zoom.exe": "Zoom",
    "facetime": "FaceTime", "photo booth": "Photo Booth",
    "microsoft teams": "Microsoft Teams", "msteams": "Microsoft Teams", "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams", "msteams.exe": "Microsoft Teams",
    "webex": "Webex", "webexmta": "Webex", "ciscowebexstart.exe": "Webex",
    "obs": "OBS", "obs64.exe": "OBS", "skype": "Skype", "skype.exe": "Skype",
    "windowscamera.exe": "Camera",   # (Discord left out: it runs all day and rarely uses the camera)
}


def camera_apps_running():
    """Names of open apps that may be using the camera (Zoom, FaceTime, Teams...)."""
    try:
        import psutil
        found = []
        for p in psutil.process_iter(["name"]):
            name = _CAMERA_APPS.get((p.info.get("name") or "").lower())
            if name and name not in found:
                found.append(name)
        return found
    except Exception:
        return []


# The quit questions come from a background thread with no parent window: without these flags Windows can
# open the box BEHIND DriftSync, so the window looks frozen. MB_TOPMOST | MB_SETFOREGROUND
_MB_ON_TOP = 0x40000 | 0x10000


def confirm(title, message, ok="OK", cancel="Cancel"):
    """A native yes/no box, for when no page is open to show our own (e.g. quitting). True = OK."""
    try:
        if IS_MAC:
            script = (f"display dialog {_applescript_text(message)} with title {_applescript_text(title)} "
                      f"buttons {{{_applescript_text(cancel)}, {_applescript_text(ok)}}} "
                      f"default button {_applescript_text(cancel)} cancel button {_applescript_text(cancel)} with icon caution")
            res = _osa(script, timeout=300)
            return res.returncode == 0 and ok in res.stdout
        if IS_WINDOWS:
            import ctypes
            MB_OKCANCEL, MB_ICONWARNING, MB_DEFBUTTON2, IDOK = 0x1, 0x30, 0x100, 1
            return ctypes.windll.user32.MessageBoxW(None, message, title, MB_OKCANCEL | MB_ICONWARNING | MB_DEFBUTTON2
                                                    | _MB_ON_TOP) == IDOK
    except Exception:
        pass
    return True   # can't ask: don't trap the user in the app


def inform(title, message, button="OK"):
    """A native message box with one button (e.g. why DriftSync won't quit during a Level 3 block).
    False if it couldn't be shown."""
    try:
        if IS_MAC:
            b = _applescript_text(button)
            script = (f"display dialog {_applescript_text(message)} with title {_applescript_text(title)} "
                      f"buttons {{{b}}} default button {b} with icon caution")
            return _osa(script, timeout=300).returncode == 0
        if IS_WINDOWS:
            import ctypes
            MB_OK, MB_ICONWARNING = 0x0, 0x30
            ctypes.windll.user32.MessageBoxW(None, message, title, MB_OK | MB_ICONWARNING | _MB_ON_TOP)
            return True
    except Exception:
        pass
    return False


def set_window_icon(window, ico_path):
    """Windows: give a pywebview window the DriftSync icon (title bar, Alt+Tab, taskbar). pywebview always
    uses python.exe's icon. Safe to call from any thread; does nothing on macOS (the Dock icon covers it)."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        form = getattr(window, "native", None)
        if form is None or not os.path.exists(str(ico_path)):
            return False
        hwnd = int(form.Handle.ToInt64())
        user32 = ctypes.WinDLL("user32", use_last_error=True)   # own handle: don't change shared argtypes
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON, ICON_SMALL, ICON_BIG = 1, 0x10, 0x80, 0, 1
        SM_CXICON, SM_CYICON, SM_CXSMICON, SM_CYSMICON = 11, 12, 49, 50
        done = False
        for which, cx, cy in ((ICON_BIG, SM_CXICON, SM_CYICON), (ICON_SMALL, SM_CXSMICON, SM_CYSMICON)):
            h = user32.LoadImageW(None, str(ico_path), IMAGE_ICON, user32.GetSystemMetrics(cx),
                                  user32.GetSystemMetrics(cy), LR_LOADFROMFILE)
            if h:
                user32.SendMessageW(hwnd, WM_SETICON, which, h)
                done = True
        return done
    except Exception as e:
        print(f"[APP ICON] window icon not set: {e}", flush=True)
        return False


def idle_seconds():
    """Seconds since the last keyboard or mouse input. The desk check uses it so typing with the
    camera blocked, or reading with your head down, still counts as being at the desk."""
    try:
        if IS_MAC:
            res = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4", "-r", "-k", "HIDIdleTime"],
                                 capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                if '"HIDIdleTime"' in line:
                    return int(line.split("=")[-1].strip()) / 1_000_000_000   # nanoseconds
            return None
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
            return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return None
    return None


# ---------- Desk check alarm: rings nonstop and gets louder until you're back ----------
import atexit as _atexit
import threading as _threading

_alarm_stop = _threading.Event()
_alarm_thread = None
_alarm_player = None
_saved_volume = None   # (output volume, muted) before the alarm, restored when it stops
ALARM_START_VOLUME = 40   # speaker volume (macOS and Windows) when the alarm starts...
ALARM_VOLUME_STEP = 15    # ...raised by this much every ~2 seconds, up to 100


def _alarm_wav():
    """Alarm-clock "beep beep ... beep beep" (two short beeps, then a pause; 2 seconds), written once."""
    import math
    import struct
    import tempfile
    import wave
    path = os.path.join(tempfile.gettempdir(), "driftsync_alarm_beepbeep.wav")
    if os.path.exists(path):
        return path
    rate = 22050
    frames = bytearray()
    for i in range(rate * 2):
        t = i / rate
        c = t % 1.0                                      # one "beep beep" every second
        beep = c < 0.13 or 0.22 <= c < 0.35
        freq = 2000                                      # high piezo tone, like an alarm clock
        v = (1 if math.sin(2 * math.pi * freq * t) >= 0 else -1) * 0.9 if beep else 0.0   # square wave
        frames += struct.pack("<h", int(v * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


def _mac_get_volume():
    try:
        res = _osa("get {output volume of (get volume settings), output muted of (get volume settings)}")
        vol, muted = [x.strip() for x in res.stdout.split(",")]
        return int(vol), muted == "true"
    except Exception:
        return None


def _mac_set_volume(vol, muted=False):
    try:
        _osa(f"set volume output volume {int(vol)}" + (" with output muted" if muted else " without output muted"))
    except Exception:
        pass


# ---------- Windows speaker volume (Core Audio through ctypes: no extra package) ----------
# IMMDeviceEnumerator -> default speakers -> IAudioEndpointVolume. Method numbers are the COM vtable slots.
_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"


def _win_endpoint_volume():
    """The default speakers' IAudioEndpointVolume as (pointer, call), or None. COM must be set up on this thread."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    def guid(text):
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    def call(obj, slot, *args, argtypes=()):
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[slot])
        return fn(obj, *args)

    ole32 = ctypes.oledll.ole32
    enum = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(guid(_CLSID_MMDeviceEnumerator)), None, 23,   # CLSCTX_ALL
                           ctypes.byref(guid(_IID_IMMDeviceEnumerator)), ctypes.byref(enum))
    device = ctypes.c_void_p()
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eMultimedia=1, &device)  (slot 4)
    call(enum, 4, 0, 1, ctypes.byref(device), argtypes=(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)))
    volume = ctypes.c_void_p()
    # IMMDevice::Activate(iid, CLSCTX_ALL, NULL, &volume)  (slot 3)
    call(device, 3, ctypes.byref(guid(_IID_IAudioEndpointVolume)), 23, None, ctypes.byref(volume),
         argtypes=(ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)))
    for obj in (device, enum):   # IUnknown::Release (slot 2); the volume object keeps what it needs
        _com_release(obj)
    return volume, call


def _com_release(obj):
    try:
        import ctypes
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(obj)
    except Exception:
        pass


def _win_get_volume():
    """(volume 0-100, muted) of the speakers, or None."""
    try:
        import ctypes
        from ctypes import wintypes
        ctypes.windll.ole32.CoInitialize(None)
        vol, call = _win_endpoint_volume()
        level, muted = ctypes.c_float(), wintypes.BOOL()
        call(vol, 9, ctypes.byref(level), argtypes=(ctypes.POINTER(ctypes.c_float),))     # GetMasterVolumeLevelScalar
        call(vol, 15, ctypes.byref(muted), argtypes=(ctypes.POINTER(wintypes.BOOL),))     # GetMute
        _com_release(vol)
        return int(round(level.value * 100)), bool(muted.value)
    except Exception as e:
        print(f"[ALARM] can't read the Windows volume: {e}", flush=True)
        return None


def _win_set_volume(vol, muted=False):
    try:
        import ctypes
        from ctypes import wintypes
        ctypes.windll.ole32.CoInitialize(None)
        v, call = _win_endpoint_volume()
        call(v, 7, ctypes.c_float(max(0, min(100, vol)) / 100.0), None,                    # SetMasterVolumeLevelScalar
             argtypes=(ctypes.c_float, ctypes.c_void_p))
        call(v, 14, bool(muted), None, argtypes=(wintypes.BOOL, ctypes.c_void_p))          # SetMute
        _com_release(v)
    except Exception as e:
        print(f"[ALARM] can't change the Windows volume: {e}", flush=True)


def _get_volume():
    return _mac_get_volume() if IS_MAC else (_win_get_volume() if IS_WINDOWS else None)


def _set_volume(vol, muted=False):
    if IS_MAC:
        _mac_set_volume(vol, muted)
    elif IS_WINDOWS:
        _win_set_volume(vol, muted)


def can_raise_volume():
    """True when the alarm can unmute and turn the speakers up (macOS always; Windows if Core Audio answers)."""
    return IS_MAC or (IS_WINDOWS and _win_get_volume() is not None)


def _alarm_loop(path):
    global _alarm_player
    volume = ALARM_START_VOLUME
    if _saved_volume:
        volume = max(volume, _saved_volume[0])
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)   # this thread talks to Core Audio
        except Exception:
            pass
    while not _alarm_stop.is_set():
        if IS_MAC:
            if _saved_volume is not None:                # only touch the volume if we can put it back later
                _mac_set_volume(volume)                  # unmute and get louder each round
            volume = min(100, volume + ALARM_VOLUME_STEP)
            _alarm_player = subprocess.Popen(["afplay", "-v", "1", path],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while _alarm_player.poll() is None and not _alarm_stop.is_set():
                _alarm_stop.wait(0.1)
            if _alarm_player.poll() is None:
                _alarm_player.kill()
        else:
            # Windows: winsound loops the sound by itself; we only unmute and turn it up every 2 seconds
            if IS_WINDOWS and _saved_volume is not None:
                _win_set_volume(volume)
                volume = min(100, volume + ALARM_VOLUME_STEP)
            _alarm_stop.wait(2.0)


def start_alarm():
    """Starts the desk check alarm (does nothing if it's already ringing). True if it could start."""
    global _alarm_thread, _saved_volume
    if _alarm_thread and _alarm_thread.is_alive():
        return True
    try:
        path = _alarm_wav()
        _alarm_stop.clear()
        _saved_volume = _get_volume()
        if IS_WINDOWS:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        _alarm_thread = _threading.Thread(target=_alarm_loop, args=(path,), daemon=True)
        _alarm_thread.start()
        return True
    except Exception as e:
        print(f"Error starting alarm: {e}", flush=True)
        return chime()


def _stop_alarm_at_exit():
    try:
        stop_alarm()
    except Exception:
        pass


def stop_alarm():
    """Stops the alarm and puts the speaker volume (and mute) back the way it was."""
    global _alarm_thread, _saved_volume
    if not (_alarm_thread and _alarm_thread.is_alive()):
        return
    _alarm_stop.set()
    try:
        if _alarm_player and _alarm_player.poll() is None:
            _alarm_player.kill()
        if IS_WINDOWS:
            import winsound
            winsound.PlaySound(None, 0)
    except Exception:
        pass
    _alarm_thread.join(timeout=4)   # let a volume change in progress finish before we restore it
    _alarm_thread = None
    if _saved_volume:
        _set_volume(*_saved_volume)
    _saved_volume = None


def read_browser_tab(app_name, timeout=4):
    """(title, url). Windows cannot read a tab's URL without a browser extension, so it returns ("", "")
    and the caller falls back to the window title."""
    if IS_MAC:
        return _mac_read_browser_tab(app_name, timeout)
    return "", ""


# Ctrl+C or a crash must not leave the alarm ringing or the Mac's volume stuck at 100
_atexit.register(_stop_alarm_at_exit)
