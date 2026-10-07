@echo off
rem One scheduled tick for Windows Task Scheduler. It runs the same due check
rem the console loop uses; when a weekday slot has passed the pipeline
rem refreshes every ticker and exits, so Task Scheduler restarts it cleanly
rem next time instead of leaving a long-lived process behind. Pass --force to
rem run immediately, which is what manual repair uses.
setlocal
for %%I in ("%~dp0..") do set "PROG5_DIR=%%~fI"
cd /d "%PROG5_DIR%"
if not exist "data" mkdir "data"
set "LOG=%PROG5_DIR%\data\scheduler.log"
rem setx does not update running processes, and Task Scheduler inherits the
rem environment from logon, so a freshly set PROG5_DATABASE_URL would stay
rem invisible to the task. Re-read the user REG_SZ values every tick.
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v PROG5_DATABASE_URL 2^>nul ^| findstr PROG5_DATABASE_URL') do set "PROG5_DATABASE_URL=%%B"
set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--once"
where python >nul 2>&1 && (set "PYTHON=python") || (set "PYTHON=py -3")
echo [%date% %time%] %PYTHON% -m prog5.cli schedule %ARGS% >> "%LOG%"
call %PYTHON% -m prog5.cli schedule %ARGS% >> "%LOG%" 2>&1
echo [%date% %time%] exit=%errorlevel% >> "%LOG%"
endlocal
