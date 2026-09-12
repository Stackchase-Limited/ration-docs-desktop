#!/bin/bash
# Launch the desktop editor with remote debugging reachable, optionally opening
# a document, and wait until the CDP endpoint answers.
#
#   harness/bin/run-editor.sh [document]
#   RD_PORT=9333 harness/bin/run-editor.sh doc.xlsx
#
# Needs a build that contains the Init_CEF remote-debugging fix (see README).
#
# A document has to arrive as an `open -a` Apple Event. Passing the path on the
# command line does nothing: the app starts, the start window appears, and no
# editor - so no CEF browser, so no CDP page target - is ever created. So the
# app is launched bare and the document is sent afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh
rd_require_app

DOC="${1:-}"
EXE="$(rd_executable)"

cdp_up() { curl -fsS --max-time 2 "http://127.0.0.1:$RD_PORT/json/version" >/dev/null 2>&1; }
page_count() { curl -fsS --max-time 3 "http://127.0.0.1:$RD_PORT/json" 2>/dev/null | grep -c '"type": "page"' || true; }
editor_up() { curl -fsS --max-time 3 "http://127.0.0.1:$RD_PORT/json" 2>/dev/null | grep -q 'api/documents'; }

# PFMoveApplication asks "Move to Applications folder?" from
# applicationDidFinishLaunching whenever the bundle is not in an Applications
# folder - and an .app built into desktop-apps/build never is. The alert is
# modal and, launched from a terminal, usually never gets drawn, so the app sits
# there alive with no window and no browser: exactly the symptom that reads as a
# broken build. Its own suppression key gets us past it.
suppress_move_alert() {
	local id
	id="$(rd_bundle_id)"
	[ -n "$id" ] || return 0
	if [ "$(defaults read "$id" moveToApplicationsFolderAlertSuppress 2>/dev/null)" != "1" ]; then
		defaults write "$id" moveToApplicationsFolderAlertSuppress -bool YES
		echo "Suppressed PFMoveApplication's \"Move to Applications folder?\" alert for $id"
		echo "  (it is modal, invisible on a terminal launch, and blocks startup entirely)"
	fi
}

if cdp_up; then
	echo "CDP already listening on port $RD_PORT - reusing the running app"
else
	# A foreign listener on the port looks exactly like "debugging is off".
	if lsof -nP -iTCP:"$RD_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
		echo "harness: port $RD_PORT is already taken by something else:" >&2
		lsof -nP -iTCP:"$RD_PORT" -sTCP:LISTEN 2>/dev/null | tail -n +2 >&2
		echo "         pick another with RD_PORT=<port>" >&2
		exit 1
	fi

	if pgrep -f "$EXE" >/dev/null 2>&1; then
		echo "harness: the app is already running without debugging on port $RD_PORT." >&2
		echo "         quit it first, then rerun this." >&2
		exit 1
	fi

	suppress_move_alert

	echo "Launching $RD_APP (version $(rd_app_version)) with CDP on $RD_PORT"
	"$EXE" --ascdesktop-support-debug-info --remote-debugging-port="$RD_PORT" >/tmp/ration-editor.log 2>&1 &
	echo "  stdout/stderr -> /tmp/ration-editor.log"

	for _ in $(seq 1 45); do
		cdp_up && break
		sleep 1
	done
fi

if ! cdp_up; then
	cat >&2 <<MSG

harness: the app started but exposes no CDP endpoint on port $RD_PORT.

This is expected on a build without our Init_CEF fix. CEF starts the DevTools
server from CefSettings.remote_debugging_port, and upstream only ever appends a
--remote-debugging-port switch from OnBeforeCommandLineProcessing, which runs
after Init_CEF has already built the browser command line - so the switch
reaches only the child processes, where the server does not live.

Two ways forward:
  * Build the app from this tree (desktop-sdk carries the fix), then rerun.
  * Right now, in the running app: press F1 in an editor window to open
    DevTools directly. That path works on the shipped build because the
    check is made at runtime - but it is manual, not scriptable.
MSG
	exit 1
fi

echo "CDP ready on http://127.0.0.1:$RD_PORT"

if [ -n "$DOC" ]; then
	[ -f "$DOC" ] || { echo "harness: no such document: $DOC" >&2; exit 1; }
	if editor_up; then
		echo "An editor is already open; sending $DOC as well"
	fi
	# Apple Event, not argv - see the header.
	open -a "$RD_APP" "$DOC"
	for _ in $(seq 1 40); do
		editor_up && break
		sleep 1
	done
	if ! editor_up; then
		cat >&2 <<MSG

harness: $DOC did not produce an editor page target.

The app is up and CDP answers, but nothing under apps/api/documents appeared.
$(page_count) page target(s) are open. If the only one is login/index.html then the
start window is all there is and the document never opened - check
/tmp/ration-editor.log, and that the file really is a format the app handles.
MSG
		exit 1
	fi
	echo "Opened: $DOC"
fi

curl -fsS "http://127.0.0.1:$RD_PORT/json" | python3 -c 'import json,sys; [print("  page:", t.get("url","")) for t in json.load(sys.stdin) if t.get("type")=="page"]'

cat <<'MSG'

The editor itself lives in an iframe of the apps/api/documents page, which CEF
does not expose as its own target. editor-eval.js reaches into it for you.
MSG
