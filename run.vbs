Dim wsh, fso, dir, cacheFile, pythonw, f
Set wsh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
cacheFile = dir & ".pythonw_cache"
pythonw = ""

' --- 1. Fast path: use cached path from previous run ---
If fso.FileExists(cacheFile) Then
    Set f = fso.OpenTextFile(cacheFile, 1)
    pythonw = Trim(f.ReadAll())
    f.Close
    If Not fso.FileExists(pythonw) Then pythonw = "" ' stale
End If

' --- 2. Slow path: scan registry (no subprocess, no console) ---
If pythonw = "" Then
    Dim oReg, arrKeys, i, installPath, candidate
    Const HKCU = &H80000001
    Const HKLM = &H80000002

    On Error Resume Next
    Set oReg = GetObject("winmgmts:\\.\root\default:StdRegProv")
    If Err.Number = 0 Then
        Dim hives(3)
        hives(0) = HKCU : hives(1) = HKLM
        hives(2) = HKCU : hives(3) = HKLM
        Dim bases(3)
        bases(0) = "SOFTWARE\Python\PythonCore"
        bases(1) = "SOFTWARE\Python\PythonCore"
        bases(2) = "SOFTWARE\Wow6432Node\Python\PythonCore"
        bases(3) = "SOFTWARE\Wow6432Node\Python\PythonCore"

        Dim hi
        For hi = 0 To 3
            oReg.EnumKey hives(hi), bases(hi), arrKeys
            If Not IsNull(arrKeys) Then
                For i = UBound(arrKeys) To 0 Step -1
                    installPath = ""
                    oReg.GetStringValue hives(hi), bases(hi) & "\" & arrKeys(i) & "\InstallPath", "", installPath
                    If installPath <> "" Then
                        If Right(installPath, 1) <> "\" Then installPath = installPath & "\"
                        candidate = installPath & "pythonw.exe"
                        If fso.FileExists(candidate) Then
                            pythonw = candidate
                            Exit For
                        End If
                    End If
                Next
            End If
            If pythonw <> "" Then Exit For
        Next
    End If
    On Error GoTo 0
End If

' --- Launch ---
If pythonw <> "" Then
    Set f = fso.CreateTextFile(cacheFile, True)
    f.Write pythonw
    f.Close
    wsh.Run """" & pythonw & """ """ & dir & "main.py""", 0, False
Else
    MsgBox "Python installation not found.", 16, "Hoarder"
End If
