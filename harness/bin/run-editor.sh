#!/bin/bash
# Launch the desktop editor with remote debugging reachable, optionally opening
# a document, and wait until the CDP endpoint answers.
#
#   harness/bin/run-editor.sh [document]
#   RD_PORT=9333 harness/bin/run-editor.sh doc.xlsx
#
# Needs a build that contains the Init_CEF remote-debugging fix (see README).
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh
rd_require_app

DOC="${1:-}"
EXE="$(rd_executable)"

cdp_up() { curl -fsS --max-time 2 "http://127.0.0.1:$RD_PORT/json/version" >/dev/null 2>&1; }

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

	echo "Launching $RD_APP (version $(rd_app_version)) with CDP on $RD_PORT"
	if [ -n "$DOC" ]; then
		"$EXE" --ascdesktop-support-debug-info --remote-debugging-port="$RD_PORT" "$DOC" >/tmp/ration-editor.log 2>&1 &
	else
		"$EXE" --ascdesktop-support-debug-info --remote-debugging-port="$RD_PORT" >/tmp/ration-editor.log 2>&1 &
	fi
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
[ -n "$DOC" ] && echo "Opened: $DOC"
curl -fsS "http://127.0.0.1:$RD_PORT/json" | python3 -c 'import json,sys; [print("  page:", t.get("url","")) for t in json.load(sys.stdin) if t.get("type")=="page"]'
