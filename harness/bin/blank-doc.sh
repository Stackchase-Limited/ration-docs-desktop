#!/bin/bash
# Produce a blank document to open in the editor.
#
#   harness/bin/blank-doc.sh xlsx /tmp/blank.xlsx
#
# Prefers the app's own template from converter/empty, which is exactly what the
# "new document" menu uses, and falls back to a generated minimal workbook.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh

KIND="${1:-xlsx}"
OUT="${2:-/tmp/ration-harness-blank.$KIND}"

if [ -n "${RD_APP:-}" ] && [ -d "$RD_APP" ]; then
	for loc in en-US default en-GB; do
		T="$RD_APP/Contents/Resources/converter/empty/$loc/new.$KIND"
		if [ -f "$T" ]; then
			cp "$T" "$OUT"
			echo "$OUT (from the app's $loc template)"
			exit 0
		fi
	done
fi

if [ "$KIND" = "xlsx" ]; then
	python3 bin/make-blank-xlsx.py "$OUT" >/dev/null
	echo "$OUT (generated)"
	exit 0
fi

echo "blank-doc.sh: no template for .$KIND and no generator" >&2
exit 1
