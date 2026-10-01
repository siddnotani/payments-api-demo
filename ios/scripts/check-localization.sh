#!/usr/bin/env bash
# Fails if any Localizable.strings file is missing keys from (or has extra keys vs) en.lproj.
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)/PaymentsDemo/Resources/Localization"
keys() { grep -oE '^"[^"]+"[[:space:]]*=' "$1" | sed -E 's/[[:space:]]*=$//' | sort -u; }
base=$(keys "$dir/en.lproj/Localizable.strings")
status=0
for f in "$dir"/*.lproj/Localizable.strings; do
  [ "$f" = "$dir/en.lproj/Localizable.strings" ] && continue
  if ! d=$(diff <(echo "$base") <(keys "$f")); then
    echo "Key mismatch in $f (< missing, > extra):"; echo "$d"; status=1
  fi
done
echo "Localization keys OK ($(echo "$base" | wc -l | tr -d ' ') keys in en)"
exit $status
