@echo off
rem ============================================================================
rem  A-Share Watch launcher
rem ----------------------------------------------------------------------------
rem  Rules for this file (enforced by tests/test_launcher.py):
rem    1. 100% ASCII. cmd.exe splits a .bat at fixed byte offsets, so multi-byte
rem       characters can break parsing mid-line.
rem    2. CRLF line endings. cmd.exe mis-parses multi-line if(...) blocks in
rem       LF-only files and the window closes instantly.
rem    3. Single-line ifs only, for the same reason.
rem    4. Keep a trailing pause, otherwise the window vanishes on error.
rem
rem  Why Python discovery is this verbose:
rem    Windows ships a FAKE python.exe under WindowsApps. It exists, it is on
rem    PATH, and "where python" finds it - but running it just opens the
rem    Microsoft Store and exits with code 9009. So a path that merely exists
rem    proves nothing. We probe every candidate by actually executing it and
rem    keep the first one that really works.
rem ============================================================================

cd /d "%~dp0"
title A-Share Watch
setlocal

set "PYEXE="

rem 1) every python.exe that PATH knows about, in search order
for /f "delims=" %%P in ('where python 2^>nul') do call :probe "%%P"

rem 2) the official Python launcher
call :probe py

rem 3) common install locations that are often missing from PATH
call :probe "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :probe "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :probe "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
call :probe "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
call :probe "%USERPROFILE%\anaconda3\python.exe"
call :probe "%USERPROFILE%\miniconda3\python.exe"
call :probe "%ProgramData%\Anaconda3\python.exe"
call :probe "%ProgramData%\miniconda3\python.exe"
call :probe "C:\anaconda3\python.exe"
call :probe "D:\anaconda\python.exe"

if not defined PYEXE echo.
if not defined PYEXE echo [ERROR] No working Python found on this computer.
if not defined PYEXE echo.
if not defined PYEXE echo NOTE: Windows has a fake "python.exe" that only opens the
if not defined PYEXE echo Microsoft Store. If you saw a Store message, that is it -
if not defined PYEXE echo it is not a real Python installation.
if not defined PYEXE echo.
if not defined PYEXE echo Option A - install real Python:
if not defined PYEXE echo   1. Go to https://www.python.org/downloads/
if not defined PYEXE echo   2. IMPORTANT: tick "Add python.exe to PATH" while installing
if not defined PYEXE echo   3. Close this window, then double-click start.bat again
if not defined PYEXE echo.
if not defined PYEXE echo Option B - turn off the fake alias:
if not defined PYEXE echo   Settings ^> Apps ^> Advanced app settings ^>
if not defined PYEXE echo   App execution aliases ^> switch OFF python.exe and python3.exe
if not defined PYEXE echo.
if not defined PYEXE echo Option C - Anaconda is installed somewhere else:
if not defined PYEXE echo   Open Anaconda Prompt and run these two lines:
if not defined PYEXE echo     cd /d %~dp0
if not defined PYEXE echo     python scripts\serve.py
if not defined PYEXE echo.
if not defined PYEXE pause
if not defined PYEXE exit /b 1

echo Using Python: %PYEXE%
echo.

"%PYEXE%" -u scripts\serve.py
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" echo [ERROR] Service exited with code %CODE%.
if not "%CODE%"=="0" echo See README.md, section: window closes instantly.
if "%CODE%"=="0" echo Service stopped.
echo.
pause
exit /b %CODE%

rem ----------------------------------------------------------------------------
rem  :probe - accept a candidate only if it actually runs.
rem  A candidate is good only when executing it succeeds. This is what filters
rem  out the Microsoft Store stub, whose exit code is 9009.
rem ----------------------------------------------------------------------------
:probe
if defined PYEXE goto :eof
"%~1" -c "import sys" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof
