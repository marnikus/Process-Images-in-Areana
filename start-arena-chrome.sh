#!/bin/bash
# Start Chrome for Arena Image Processor on Linux/Mac
# Uses dedicated profile ~/.arena-images-chrome

CHROME_PROFILE="$HOME/.arena-images-chrome"
PORT=9222

echo "Starting Chrome with remote debugging on port $PORT..."
echo "Profile: $CHROME_PROFILE"
echo "If Chrome is already running, close all windows first."

# Try to find Chrome
if command -v google-chrome &> /dev/null; then
  CHROME="google-chrome"
elif command -v chromium-browser &> /dev/null; then
  CHROME="chromium-browser"
elif [ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  echo "Chrome not found, please install Chrome or edit this script"
  exit 1
fi

"$CHROME" --remote-debugging-port=$PORT --user-data-dir="$CHROME_PROFILE" https://arena.ai &

echo "Chrome started. In Arena app click Diagnose and Refresh tabs."
echo "Test: curl http://127.0.0.1:$PORT/json/list should return JSON"
