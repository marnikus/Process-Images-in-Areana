@echo off
REM ===============================================================
REM  Start Chrome for Arena Image Processor
REM
REM  Opens Chrome on a DEDICATED profile (C:\arena-images-chrome)
REM  with the DevTools port the app connects to. Your everyday
REM  Chrome profile, tabs and extensions are NOT touched, and this
REM  works even when Chrome is already running. Log in to arena.ai
REM  once in this window; the login is remembered in the profile.
REM
REM  If 9222 is blocked, try 9223 and change port in settings.
REM ===============================================================
echo Starting Chrome with remote debugging...
echo If Chrome is already running, close ALL Chrome windows first (check Task Manager).
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome" https://arena.ai
echo.
echo Chrome should open with arena.ai. Then in Arena app click "Diagnose" and "Refresh tabs".
echo If you see "site can't be reached" for http://127.0.0.1:9222/json/list, check firewall/antivirus.
pause
