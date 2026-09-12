#!/bin/bash
# Build sdkjs from this tree and drop it into the app bundle, so the editor you
# launch is running our source.
#
#   harness/bin/inject-sdkjs.sh [cell|word|slide|pdf ...]   inject (default: cell)
#   harness/bin/inject-sdkjs.sh --restore                   put the originals back
#
# The bundle is code-signed, and replacing resources breaks the seal, so we
# re-sign ad-hoc afterwards. That is fine for a local harness; it does not
# produce a distributable build.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh
rd_require_app

SDKJS="$(cd .. && pwd)/sdkjs"
EDITORS="$(rd_editors_dir)"
[ -d "$EDITORS/sdkjs" ] || { echo "harness: $EDITORS/sdkjs missing - is $RD_APP an editor build?" >&2; exit 1; }

resign() {
	if [ "$(uname)" = "Darwin" ]; then
		echo "Re-signing $RD_APP (ad-hoc)"
		codesign --force --sign - "$RD_APP" >/dev/null 2>&1 || \
			echo "  note: ad-hoc re-sign failed; the app may refuse to launch" >&2
	fi
}

if [ "${1:-}" = "--restore" ]; then
	restored=0
	for backup in "$EDITORS"/sdkjs/*.orig; do
		[ -d "$backup" ] || continue
		target="${backup%.orig}"
		echo "Restoring $(basename "$target")"
		rm -rf "$target" && mv "$backup" "$target"
		restored=1
	done
	[ "$restored" = 1 ] || { echo "Nothing to restore."; exit 0; }
	resign
	echo "Done. The app is back to its shipped sdkjs."
	exit 0
fi

PRODUCTS=("$@")
[ ${#PRODUCTS[@]} -eq 0 ] && PRODUCTS=(cell)

for p in "${PRODUCTS[@]}"; do
	echo "== building sdkjs product: $p"
	( cd "$SDKJS" && python3 build/build.py --product "$p" --desktop )

	src="$SDKJS/deploy/sdkjs/$p"
	dst="$EDITORS/sdkjs/$p"
	[ -d "$src" ] || { echo "harness: build produced no $src" >&2; exit 1; }

	if [ ! -d "$dst.orig" ] && [ -d "$dst" ]; then
		echo "   backing up shipped $p -> $(basename "$dst").orig"
		cp -R "$dst" "$dst.orig"
	fi

	echo "   installing -> $dst"
	rm -rf "$dst"
	cp -R "$src" "$dst"
done

# common/ carries AllFonts.js and other shared assets; only copy what we built.
if [ -d "$SDKJS/deploy/sdkjs/common" ]; then
	echo "== merging sdkjs/common"
	[ -d "$EDITORS/sdkjs/common.orig" ] || cp -R "$EDITORS/sdkjs/common" "$EDITORS/sdkjs/common.orig"
	cp -R "$SDKJS/deploy/sdkjs/common/." "$EDITORS/sdkjs/common/"
fi

resign
echo
echo "Injected. Now: harness/bin/run-editor.sh [document]"
echo "Undo with:   harness/bin/inject-sdkjs.sh --restore"
