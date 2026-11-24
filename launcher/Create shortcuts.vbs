' Puts a DriftSync shortcut (with the DriftSync icon) on the Desktop and in the Start menu.
' Double-click it once. Run with /quiet to skip the "done" message (DriftSync.bat does this on first setup).
' Pin to taskbar: right-click the Desktop shortcut > Show more options > Pin to taskbar.
Option Explicit
Dim fso, sh, root, target, icon, places, p, lnk, quiet

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
quiet = (WScript.Arguments.Count > 0)
If quiet Then quiet = (LCase(WScript.Arguments(0)) = "/quiet")

target = root & "\launcher\DriftSync.vbs"
icon = root & "\launcher\icons\DriftSync.ico"
places = Array(sh.SpecialFolders("Desktop"), sh.SpecialFolders("Programs"))

For Each p In places
    If fso.FolderExists(p) Then
        Set lnk = sh.CreateShortcut(p & "\DriftSync.lnk")
        lnk.TargetPath = sh.ExpandEnvironmentStrings("%WINDIR%\System32\wscript.exe")
        lnk.Arguments = """" & target & """"
        lnk.WorkingDirectory = root
        lnk.IconLocation = icon & ",0"
        lnk.Description = "DriftSync - focus sessions and distraction recovery"
        lnk.WindowStyle = 1
        lnk.Save
    End If
Next

If Not quiet Then
    MsgBox "DriftSync is now on your Desktop and in the Start menu." & vbCrLf & vbCrLf & _
           "To pin it to the taskbar, right-click the Desktop shortcut and choose Pin to taskbar " & _
           "(on Windows 11: Show more options first).", vbInformation, "DriftSync"
End If
