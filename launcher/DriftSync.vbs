' DriftSync launcher for Windows: starts DriftSync with no console window.
' The Desktop and Start menu shortcuts point here (they are made by "Create shortcuts.vbs").
'
' - Uses the .venv inside the DriftSync folder, or the Python launcher (pyw), or pythonw.
' - If anything is missing (first run), it opens DriftSync.bat instead, which explains and installs.
' - DriftSync writes its output to logs\DriftSync.log. If it stops with an error, a message box says so.
Option Explicit
Dim fso, sh, root, py, rc, logPath, msg, f, text, lines, i

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.CurrentDirectory = root

If Not fso.FileExists(root & "\desktop_app.py") Then
    MsgBox "DriftSync can't find desktop_app.py in" & vbCrLf & root & vbCrLf & vbCrLf & _
           "Keep the launcher folder inside the DriftSync folder.", vbCritical, "DriftSync"
    WScript.Quit 1
End If

' Run a program with no window and wait; returns its exit code
Function RunHidden(cmd)
    RunHidden = sh.Run(cmd, 0, True)
End Function

py = ""
If fso.FileExists(root & "\.venv\Scripts\pythonw.exe") Then
    py = ".venv\Scripts\pythonw.exe"
ElseIf fso.FileExists(root & "\venv\Scripts\pythonw.exe") Then
    py = "venv\Scripts\pythonw.exe"
ElseIf RunHidden("cmd /c where pyw >nul 2>nul") = 0 Then
    py = "pyw -3"
ElseIf RunHidden("cmd /c where pythonw >nul 2>nul") = 0 Then
    py = "pythonw"
End If

' First run, or something missing: DriftSync.bat shows what's wrong and offers to install it
If py = "" Then
    sh.Run """" & root & "\DriftSync.bat""", 1, False
    WScript.Quit 0
End If
If RunHidden(py & " check_setup.py --quiet") <> 0 Then
    sh.Run """" & root & "\DriftSync.bat""", 1, False
    WScript.Quit 0
End If

logPath = root & "\logs\DriftSync.log"   ' desktop_app.py writes it when there is no console
rc = RunHidden(py & " desktop_app.py")

If rc <> 0 Then
    ' Show the last lines of the log so the error can be read (and reported)
    text = ""
    On Error Resume Next
    Set f = fso.OpenTextFile(logPath, 1, False, 0)
    If Err.Number = 0 Then
        lines = Split(f.ReadAll, vbLf)
        f.Close
        For i = UBound(lines) - 12 To UBound(lines)
            If i >= 0 Then text = text & Replace(lines(i), vbCr, "") & vbCrLf
        Next
    End If
    On Error GoTo 0
    msg = "DriftSync stopped with an error." & vbCrLf & vbCrLf & text & vbCrLf & _
          "Full log: " & logPath & vbCrLf & vbCrLf & "Open the log now?"
    If MsgBox(msg, vbYesNo + vbExclamation, "DriftSync") = vbYes Then
        sh.Run "notepad.exe """ & logPath & """", 1, False
    End If
End If
