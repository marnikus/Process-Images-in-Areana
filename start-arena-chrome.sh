#!/bin/bash
# Start Chrome for Arena Image Processor — USER CONFIGURABLE
# Usage: ./start-arena-chrome.sh [port] [user_data_dir] [url]
# Example: ./start-arena-chrome.sh 9222 ~/.arena-images-chrome https://arena.ai
#          ./start-arena-chrome.sh 9223 ~/.arena-9223 https://arena.ai

PORT=${1:-9222}
USERDIR=${2:-$HOME/.arena-images-chrome}
URL=${3:-https://arena.ai}

echo "Starting Chrome with remote debugging..."
echo "Port: $PORT"
echo "User-Data-Dir: $USERDIR"
echo "URL: $URL"
echo "If Chrome already running, close all windows first."

if command -v google-chrome &> /dev/null; then
  CHROME="google-chrome"
elif command -v chromium-browser &> /dev/null; then
  CHROME="chromium-browser"
elif [ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  echo "Chrome not found"
  exit 1
fi

"$CHROME" --remote-debugging-port=$PORT --user-data-dir="$USERDIR" "$URL" &

echo "Chrome started. In Arena app: Settings -> set Port $PORT and Dir $USERDIR -> Save CDP -> Diagnose"
echo "Test: curl http://127.0.0.1:$PORT/json/list"
