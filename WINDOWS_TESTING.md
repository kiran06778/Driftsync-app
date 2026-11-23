# Testing DriftSync on a Windows PC

The Windows code has been checked with simulated Windows parts (`tests/test_windows.py`) but **not yet on a real
Windows PC**. This list is for whoever runs it on Windows first. It takes about 25 minutes. Write down anything
that doesn't match and send the black console window's text with it.

## 0. Before you start
- Windows 10 or 11, Python 3.12 or 3.13 from python.org (64-bit, "Add python.exe to PATH" ticked).
- Optional: a `.env` file with `GROQ_API_KEY=...` in the DriftSync folder.
- Have Edge or Chrome open with YouTube and Instagram/Reddit tabs.

## 1. Start-up (3 min)
| # | Do this | Expected |
|---|---------|----------|
| 1.1 | Double-click `DriftSync.bat` | First time: it asks to install into `.venv`. Type Y. Then the sign-in window opens. |
| 1.2 | Look at the window | It fits on the screen (nothing cut off at the bottom), fonts look like the Mac version, no "Internet Explorer" look. |
| 1.3 | In the DriftSync folder run `.venv\Scripts\python tests\windows_smoke.py` | It ends with "N of N checks OK". You may see one test notification and hear a beep. |

## 2. Blocking (Level 2, Balanced) (5 min)
| # | Do this | Expected |
|---|---------|----------|
| 2.1 | Setup: Level 2, blocklist with Instagram + YouTube, Smart YouTube off. Start a focus block. | Timer runs. |
| 2.2 | Switch to an **Edge** tab with Instagram | Within ~2 s the intention popup appears **on top** of Edge. The console shows `[RADAR SCAN] microsoft edge | Instagram - Microsoft Edge` (no "Personal", no odd characters). |
| 2.3 | Click "Back to focus" | Edge is minimised, DriftSync stays in front. |
| 2.4 | Repeat 2.2 in **Chrome** and **Firefox** | Same popup. |
| 2.5 | Open a Word/Notepad file named `reddit_notes.txt` | Nothing happens (only browsers' titles are checked). |
| 2.6 | Close the main window (X) during the block | A "Quit DriftSync?" box appears **in front** (not hidden behind). Pick "Keep focusing". |

## 3. Smart YouTube (3 min)
| # | Do this | Expected |
|---|---------|----------|
| 3.1 | Goal "studying data structures", Smart YouTube on. In Edge, open a DSA lecture. | Allowed. Console: `[SMART YOUTUBE] Allowed "..."` with the clean video title. |
| 3.2 | Open a music video or a Short | Blocked with the popup. |

## 4. Level 1 notifications (4 min)
| # | Do this | Expected |
|---|---------|----------|
| 4.1 | Setup: Level 1, "Notification", press **Test** | A Windows notification appears bottom-right (sender: Windows PowerShell). |
| 4.2 | Turn notifications off (Settings > System > Notifications), back in DriftSync press **Test** | DriftSync asks "Notifications are turned off" with **Turn on notifications**. Click it: a notification appears **without** opening Settings. *(If none appears, note it: Windows may need a restart of Explorer for this switch.)* |
| 4.3 | Start a block and open Instagram | A notification, no popup. Ignore it 3 times: it also beeps. |

## 5. Desk check camera (6 min)
| # | Do this | Expected |
|---|---------|----------|
| 5.1 | Setup: turn on Desk check | Intro dialog, then "Camera allowed". **Test camera** shows you with a green box. |
| 5.2 | Settings > Privacy & security > Camera: turn off "Let desktop apps access your camera". In DriftSync turn Desk check off and on. | DriftSync says "Windows is keeping the camera off" and **Open the switch** opens that exact page. Turn it on: DriftSync shows "Camera allowed" by itself. |
| 5.3 | Join a Zoom/Teams/Camera-app video, then turn Desk check on | It names the app that holds the camera and offers **Try again**. |
| 5.4 | Start a block, walk away past the allowed time | Dark-red full screen "Come back to your desk", the alarm rings, **the PC unmutes and gets louder**. |
| 5.5 | Sit back down | Alarm stops, red screen goes, **volume returns to where it was** (also if it was muted). |

## 6. Level 3 (Strict) (3 min)
| # | Do this | Expected |
|---|---------|----------|
| 6.1 | Start a Level 3 block, press Alt+F4 on DriftSync | Box "DriftSync stays open (Level 3)" in front; app stays open. |
| 6.2 | End DriftSync from Task Manager, start it again | The block carries on; Insights shows "Quit DriftSync" as a drift. |

## 7. Other
- Insights, Timetable, Leaderboard, all themes: pages open and look like on the Mac.
- Laptop on battery + Desk check on: battery warning appears.
- Python from the **Microsoft Store** only (no python.org): `DriftSync.bat` should still find it.

## What could not be checked without a real PC
- Whether Windows shows the PowerShell toast (Do not disturb hides it silently; nothing can detect that).
- Whether switching notifications back on from the app takes effect immediately on every Windows build.
- The Core Audio volume code (unmute + louder + put back) and the "bring DriftSync to the front" trick.
- Camera opening speed and the second camera backend on unusual laptop webcams.
