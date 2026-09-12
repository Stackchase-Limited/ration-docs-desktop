#!/bin/bash
# Turn CEF remote debugging on (or off) for the desktop editor.
#
# The app only passes --remote-debugging-port to CEF when debug-info support is
# on (client_app.h: `if (m_manager->GetDebugInfoSupport())`), and that flag is
# read from settings.xml as ascdesktop-support-debug-info-keep. Setting it here
# means we can drive an already-built app without rebuilding anything.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh
rd_require_app

WANT=1
[ "${1:-}" = "--off" ] && WANT=0

SETTINGS="$(rd_settings_file)"
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || printf '<Settings></Settings>' > "$SETTINGS"

python3 - "$SETTINGS" "$WANT" <<'PY'
import io, re, sys
path, want = sys.argv[1], sys.argv[2]
s = io.open(path, encoding='utf-8').read().strip() or '<Settings></Settings>'
key = 'ascdesktop-support-debug-info-keep'
s = re.sub(r'<%s>.*?</%s>' % (key, key), '', s, flags=re.S)
if want == '1':
    if '</Settings>' not in s:
        s = '<Settings></Settings>'
    s = s.replace('</Settings>', '<%s>1</%s></Settings>' % (key, key))
io.open(path, 'w', encoding='utf-8').write(s)
print(('enabled' if want == '1' else 'disabled') + ' remote debugging in ' + path)
print(s)
PY

echo
echo "App:     $RD_APP  (version $(rd_app_version))"
echo "Restart the app for this to take effect: harness/bin/run-editor.sh"
