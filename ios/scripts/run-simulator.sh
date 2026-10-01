#!/usr/bin/env bash
# Start the FastAPI backend (if it isn't already running), then build PaymentsDemo,
# boot an iOS simulator, install and launch the app.
#
# Usage: ios/scripts/run-simulator.sh            # defaults to "iPhone 16"
#        SIMULATOR="iPhone 17" ios/scripts/run-simulator.sh
#        API_BASE_URL=http://127.0.0.1:9000 ios/scripts/run-simulator.sh
set -euo pipefail

IOS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$IOS_DIR/.." && pwd)"
SIMULATOR="${SIMULATOR:-iPhone 16}"
API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
BUNDLE_ID="com.example.paymentsdemo.PaymentsDemo"
DERIVED_DATA="$IOS_DIR/build/DerivedData"

# 1. Backend
if curl -fsS "$API_BASE_URL/health" >/dev/null 2>&1; then
  echo "Backend already running at $API_BASE_URL"
else
  echo "Starting backend: uvicorn app.main:app --reload (logs: $IOS_DIR/build/uvicorn.log)"
  mkdir -p "$IOS_DIR/build"
  (
    cd "$REPO_ROOT"
    if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi
    nohup uvicorn app.main:app --reload --port 8000 >"$IOS_DIR/build/uvicorn.log" 2>&1 &
  )
  for _ in $(seq 1 30); do
    curl -fsS "$API_BASE_URL/health" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS "$API_BASE_URL/health" >/dev/null || { echo "Backend failed to start"; exit 1; }
fi

# 2. Simulator: use the requested device, or fall back to the first available iPhone.
UDID="$(xcrun simctl list devices available | grep -E "^\s+$SIMULATOR \(" | head -1 | grep -oE '[0-9A-F-]{36}' || true)"
if [ -z "$UDID" ]; then
  echo "Simulator '$SIMULATOR' not found; falling back to the first available iPhone."
  UDID="$(xcrun simctl list devices available | grep -E '^\s+iPhone' | head -1 | grep -oE '[0-9A-F-]{36}')"
fi
echo "Using simulator $UDID"
xcrun simctl boot "$UDID" 2>/dev/null || true
open -a Simulator
xcrun simctl bootstatus "$UDID" -b >/dev/null

# 3. Build
if command -v xcodegen >/dev/null 2>&1; then (cd "$IOS_DIR" && xcodegen generate --quiet); fi
xcodebuild \
  -project "$IOS_DIR/PaymentsDemo.xcodeproj" \
  -scheme PaymentsDemo \
  -destination "platform=iOS Simulator,id=$UDID" \
  -derivedDataPath "$DERIVED_DATA" \
  build | tail -1

# 4. Install + launch
APP="$DERIVED_DATA/Build/Products/Debug-iphonesimulator/PaymentsDemo.app"
xcrun simctl install "$UDID" "$APP"
xcrun simctl launch "$UDID" "$BUNDLE_ID" -api_base_url "$API_BASE_URL"
echo "Launched PaymentsDemo. Screenshot: xcrun simctl io $UDID screenshot shot.png"
