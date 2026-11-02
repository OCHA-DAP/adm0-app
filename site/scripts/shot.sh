#!/usr/bin/env bash
# Usage: scripts/shot.sh '<path?query#zoom/lat/lng>' out.png  (dev server must be running)
set -euo pipefail
url="${BASE_URL:-http://localhost:4321}$1"
playwright-cli open "$url" >/dev/null
playwright-cli run-code "async page => {
  await page.waitForFunction(() => window.map?.loaded() && window.map.areTilesLoaded(), null, { timeout: 60000 });
  await page.screenshot({ path: '$2' });
}" | grep -A3 '### Error' && exit 1
playwright-cli close >/dev/null
echo "$2"
