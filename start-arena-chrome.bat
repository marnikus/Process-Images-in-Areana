@echo off
REM ===============================================================
REM  Start Chrome for Arena Image Processor — USER CONFIGURABLE
REM
REM  Usage:
REM    start-arena-chrome.bat
REM    start-arena-chrome.bat 9222
REM    start-arena-chrome.bat 9222 "C:\arena-images-chrome"
REM    start-arena-chrome.bat 9223 "C:\arena-9223" https://arena.ai
REM
REM  Opens Chrome on a DEDICATED profile with DevTools port.
REM  Your everyday Chrome profile is NOT touched.
REM  App will remember port/dir in config/session.json
REM ===============================================================

set PORT=%1
if "%PORT%"=="" set PORT=9222

set USERDIR=%2
if "%USERDIR%"=="" set USERDIR=C:\arena-images-chrome

set URL=%3
if "%URL%"=="" set URL=https://arena.ai

echo Starting Chrome with remote debugging...
echo Port: %PORT%
echo User-Data-Dir: %USERDIR%
echo URL: %URL%
echo.
echo If Chrome is already running, close ALL Chrome windows first (check Task Manager).
echo If port %PORT% is blocked, try different port e.g. 9223
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=%PORT% --user-data-dir="%USERDIR%" %URL%

echo.
echo Chrome should open with %URL%. Then in Arena app:
echo 1) Settings -> Chrome Debug Connection -> set same Port and Dir -> Save CDP
echo 2) Click Diagnose -> should show ✅ Found X tabs
echo 3) Refresh tabs -> Connect
echo.
echo Test manually: open http://127.0.0.1:%PORT%/json/list in browser — should show JSON.
pause
