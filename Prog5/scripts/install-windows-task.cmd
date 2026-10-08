@echo off
rem Register the weekday refresh with Windows Task Scheduler. No Docker and no
rem administrator rights: the tasks run as the signed-in user and only while
rem that user is logged on. Re-running replaces the tasks in place.
setlocal
set "TASK_AM=Prog5 daily refresh"
set "TASK_PM=Prog5 daily refresh evening"
for %%I in ("%~dp0..") do set "PROG5_DIR=%%~fI"
set "RUNNER=%PROG5_DIR%\scripts\run-scheduled-refresh.cmd"

if not exist "%RUNNER%" (
  echo Missing %RUNNER%
  exit /b 1
)

echo Registering "%TASK_AM%" ...
schtasks /create /f /tn "%TASK_AM%" /sc weekly /d MON,TUE,WED,THU,FRI /st 17:35 /tr "\"%RUNNER%\""
rem Drop the battery and idle defaults that stop weekday runs (0x800710E0).
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $s=(Get-ScheduledTask -TaskName '%TASK_AM%').Settings; $s.DisallowStartIfOnBatteries=$false; $s.StopIfGoingOnBatteries=$false; $s.StartWhenAvailable=$true; $s.WakeToRun=$true; $s.IdleSettings.StopOnIdleEnd=$false; Set-ScheduledTask -TaskName '%TASK_AM%' -Settings $s | Out-Null"
if errorlevel 1 (
  echo.
  echo Could not harden "%TASK_AM%". Re-run from a normal user terminal.
  exit /b 1
)
if errorlevel 1 (
  echo.
  echo Could not register the task. Run this script from a normal user terminal.
  exit /b 1
)

echo Registering "%TASK_PM%" ...
schtasks /create /f /tn "%TASK_PM%" /sc weekly /d MON,TUE,WED,THU,FRI /st 21:05 /tr "\"%RUNNER%\""
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $s=(Get-ScheduledTask -TaskName '%TASK_PM%').Settings; $s.DisallowStartIfOnBatteries=$false; $s.StopIfGoingOnBatteries=$false; $s.StartWhenAvailable=$true; $s.WakeToRun=$true; $s.IdleSettings.StopOnIdleEnd=$false; Set-ScheduledTask -TaskName '%TASK_PM%' -Settings $s | Out-Null"
if errorlevel 1 (
  echo.
  echo Could not harden "%TASK_PM%". Re-run from a normal user terminal.
  exit /b 1
)
if errorlevel 1 (
  echo.
  echo Could not register the evening task. Run this script from a normal user terminal.
  exit /b 1
)

echo.
echo Registered two weekday slots, both shortly after the 17:30 and 21:00
echo pipeline times so the due check cannot race the trigger:
echo   %TASK_AM%  - 17:35
echo   %TASK_PM% - 21:05
echo   Log:     %PROG5_DIR%\data\scheduler.log
echo   Run now: schtasks /run /tn "%TASK_AM%"
echo   Remove:  schtasks /delete /f /tn "%TASK_AM%" ^& schtasks /delete /f /tn "%TASK_PM%"
echo.
echo The tasks refresh whichever database the app is configured for. To write
echo to the deployed Neon database from this host, set the connection string
echo once and sign out and back in so Task Scheduler inherits it:
echo   setx PROG5_DATABASE_URL "postgresql://..."
echo.
echo Without that variable the tasks keep the local SQLite database current.
endlocal
