# PaymentsDemo (iOS)

SwiftUI client for the FastAPI backend in `app/main.py`.

| Tab          | What it does |
| ------------ | ------------ |
| Transactions | `GET /transactions` (pull to refresh, newest first). Tap a row for `GET /transactions/{id}`. |
| New Payment  | Form that `POST`s to `/transactions`; 201 shows the created id/status, 422 `detail` is decoded into an alert. |
| Ops          | Base URL setting, `GET /health`, `GET /ops/jobs` with **Run** (`POST /ops/jobs/{name}/run`, dry-run toggle), and buttons for each `POST /ops/incidents/{scenario}` (always HTTP 500). |

The API keeps transactions in memory, so the list is empty after every server restart; the app shows an empty state for that.

## Layout

```
ios/
  project.yml                 # XcodeGen spec (source of truth for the .xcodeproj)
  PaymentsDemo.xcodeproj      # generated, committed so Xcode users don't need XcodeGen
  PaymentsDemo/
    App/                      # @main app + TabView
    Networking/               # APIClient (async/await + URLSession), Codable models, APIError
    Features/                 # Transactions, NewPayment, Ops screens
    Support/                  # String+Extension (localization), settings, formatting
    Resources/Localization/   # en.lproj/Localizable.strings, InfoPlist.strings
  PaymentsDemoTests/          # model decoding + APIClient tests (stubbed URLProtocol)
  scripts/run-simulator.sh    # backend + simulator bootstrap
  scripts/check-localization.sh
```

## Run

Requires macOS with Xcode 16+ (iOS 17+ simulator). From the repo root:

```bash
# 1. Backend on localhost:8000
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 2. App (in another terminal)
ios/scripts/run-simulator.sh                 # defaults to "iPhone 16"
SIMULATOR="iPhone 17" ios/scripts/run-simulator.sh
```

`run-simulator.sh` starts uvicorn if `/health` isn't reachable, boots the simulator (falling back to the first available iPhone), builds, installs and launches. The manual equivalent:

```bash
cd ios
xcodebuild -scheme PaymentsDemo -destination 'platform=iOS Simulator,name=iPhone 16' \
  -derivedDataPath build/DerivedData build
# If several runtimes have an "iPhone 16", pin one: name=iPhone 16,OS=26.5
xcrun simctl boot "iPhone 16"; open -a Simulator
xcrun simctl install booted build/DerivedData/Build/Products/Debug-iphonesimulator/PaymentsDemo.app
xcrun simctl launch booted com.example.paymentsdemo.PaymentsDemo
xcrun simctl io booted screenshot screenshot.png
```

## Base URL

Defaults to `http://localhost:8000` (the simulator shares the Mac's localhost). Change it in the **Ops** tab, or at launch:

```bash
xcrun simctl launch booted com.example.paymentsdemo.PaymentsDemo -api_base_url http://192.168.1.20:8000
```

For a physical device, run uvicorn with `--host 0.0.0.0` and use the Mac's LAN IP. `NSAllowsLocalNetworking` is set so plain HTTP to local hosts is allowed.

## Tests and checks

```bash
cd ios
xcodebuild test -scheme PaymentsDemo -destination 'platform=iOS Simulator,name=iPhone 16'
scripts/check-localization.sh
```

After editing `project.yml`, regenerate with `xcodegen generate` (`brew install xcodegen`).

User-facing strings live in `Resources/Localization/en.lproj/Localizable.strings` and are accessed via `"key".localized` / `"key".localizedString`.
