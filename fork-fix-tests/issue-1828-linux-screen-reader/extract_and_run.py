#!/usr/bin/env python3
"""
#1828 - "Not accessible with any screen reader on Linux": with Orca running, the
editors were silent - not even the toolbar or the menus were read.

Cause: Chromium keeps a page's accessibility tree off until the embedder enables it
(CefBrowserHost::SetAccessibilityState, or the --force-renderer-accessibility
switch), and on Linux (Chromium 107, ui/accessibility/platform/atk_util_auralinux.cc
ShouldEnableAccessibility) it registers its ATK root with AT-SPI only when
ACCESSIBILITY_ENABLED, GNOME_ACCESSIBILITY or QT_ACCESSIBILITY is "1" in the
environment at start-up. desktop-apps win-linux/src/main.cpp did neither, and the
macOS fix (#1872, desktop-sdk accessibility_state.h) is driven by VoiceOver only.

Fix: main.cpp asks the session's AT-SPI bus (org.a11y.Bus /org/a11y/bus,
org.a11y.Status.ScreenReaderEnabled, without auto-starting it) before Init_CEF; when a
screen reader runs, or the user passed --force-renderer-accessibility, it sets
ACCESSIBILITY_ENABLED=1 and hands CEF argv plus the switch. Otherwise argv and the
environment are what they were.

How it is tested: the REAL screenReaderEnabled / prepareAccessibility functions and
the REAL statements that build the CEF argv (from `std::vector<char*> cef_args` to the
Init_CEF call) are extracted from main.cpp and compiled against Qt5 DBus in the
rd-linux-verify:24.04 image, with InputArgs, AscAppManager and CApplicationCEF stubbed
(Init_CEF records argc/argv). Each case runs under its own dbus-run-session; a mock
org.a11y.Bus service (QDBusVirtualObject) answers Properties.Get. Cases:
  1. no AT-SPI bus service                 -> argv unchanged, env unset
  2. bus up, IsEnabled=true but no screen reader -> unchanged (no behaviour change for
     on-screen keyboards etc.)
  3. bus up, ScreenReaderEnabled=true      -> env ACCESSIBILITY_ENABLED=1, argv + switch,
     original arguments kept in order, argv[argc] == NULL
  4. no bus service, user passed the switch -> env set, switch not duplicated
  5. no session bus at all                  -> unchanged, does not hang
BASELINE=1 reads main.cpp from BASE_REF: the functions are not there (the extractor
reports it), so the test FAILS.

NOT claimed: that Orca then reads the editors well. That needs a Linux GUI check with
Orca (the bundled CEF 107 ATK bridge and the shipped Qt's AT-SPI bridge are not
exercised here). The document body is a canvas and stays unreadable, and the X11
PRIMARY selection (#1592) is unchanged. A screen reader started after the editors
needs the editors restarted (Chromium reads the environment once).

  RD_REPO=<desktop-apps> (default ../../desktop-apps)
  BASELINE=1 [BASE_REF=<ref>]  - must fail. Needs docker + rd-linux-verify:24.04 (77 if absent).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/main.cpp'
BASE_REF = os.environ.get('BASE_REF', '35f7c442c^')
IMAGE = os.environ.get('RD_LINUX_IMAGE', 'rd-linux-verify:24.04')


def block(src, name):
    """'static <type> name(...) { ... }' by brace matching, or None."""
    at = src.find(' ' + name + '(')
    while at != -1:
        start = src.rfind('\n', 0, at) + 1
        line = src[start:src.find('\n', at)]
        if line.startswith('static ') and not line.rstrip().endswith(';'):
            i = src.index('{', at)
            depth = 0
            for j in range(i, len(src)):
                if src[j] == '{':
                    depth += 1
                elif src[j] == '}':
                    depth -= 1
                    if depth == 0:
                        return src[start:j + 1]
        at = src.find(' ' + name + '(', at + 1)
    return None


def cef_args_statements(src):
    """The statements in main() from `std::vector<char*> cef_args` to the Init_CEF call."""
    at = src.find('std::vector<char*> cef_args')
    if at == -1:
        return None
    end = src.index(';', src.index('Init_CEF(', at)) + 1
    return src[at:end]


HARNESS = r'''
#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusVariant>
#include <QDBusVirtualObject>
#include <string>
#include <vector>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace InputArgs {
    std::vector<std::wstring> in_args;
    // the real one also matches "--x=..."; an exact match is all these cases need
    bool contains(const std::wstring& p) { for (auto& a : in_args) if (a == p) return true; return false; }
}
struct AscAppManager { static AscAppManager& getInstance() { static AscAppManager m; return m; } };
struct CApplicationCEF {
    int Init_CEF(AscAppManager*, int argc, char* argv[]) {
        printf("argc=%%d", argc);
        for (int i = 0; i < argc; ++i) printf(" [%%s]", argv[i]);
        printf(" null_terminated=%%d\n", argv[argc] == nullptr ? 1 : 0);
        return 0;
    }
};

%(fns)s

// mock of at-spi-bus-launcher's org.a11y.Status properties
class A11yStatus : public QDBusVirtualObject {
public:
    bool sr = false, en = false;
    QString introspect(const QString&) const override { return QString(); }
    bool handleMessage(const QDBusMessage& m, const QDBusConnection& c) override {
        if (m.member() != "Get" || m.arguments().size() != 2) return false;
        QString prop = m.arguments().at(1).toString();
        bool v = prop == "ScreenReaderEnabled" ? sr : prop == "IsEnabled" ? en : false;
        c.send(m.createReply(QVariant::fromValue(QDBusVariant(v))));
        return true;
    }
};

int main(int argc, char* argv[])
{
    QCoreApplication app(argc, argv);
    if (argc > 1 && !strcmp(argv[1], "serve")) {
        A11yStatus st;
        st.sr = argc > 2 && !strcmp(argv[2], "1");
        st.en = argc > 3 && !strcmp(argv[3], "1");
        QDBusConnection::sessionBus().registerVirtualObject("/org/a11y/bus", &st);
        QDBusConnection::sessionBus().registerService("org.a11y.Bus");
        return app.exec();
    }
    // the app as started: <exe> [user args...]
    for (int i = 2; i < argc; ++i) {
        std::string s(argv[i]);
        InputArgs::in_args.push_back(std::wstring(s.begin(), s.end()));
    }
    argv[1] = (char*)"doc.docx";
    CApplicationCEF* application_cef = new CApplicationCEF();
    %(stmts)s
    const char* e = getenv("ACCESSIBILITY_ENABLED");
    printf("env=%%s\n", e ? e : "(unset)");
    return 0;
}
'''

SCRIPT = r'''
cd /tmp
g++ -std=c++14 -fPIC -o h /work/h.cpp $(pkg-config --cflags --libs Qt5DBus Qt5Core) || exit 3
# the mock bus service runs in the background of its session and is killed when the case is done
serve() { ./h serve "$1" "$2" >/dev/null 2>&1 & SRV=$!; for i in $(seq 50); do gdbus call --session -d org.freedesktop.DBus -o /org/freedesktop/DBus -m org.freedesktop.DBus.NameHasOwner org.a11y.Bus 2>/dev/null | grep -q true && return; sleep 0.1; done; }
echo "== nobus";   dbus-run-session -- bash -c './h run' 2>&1
echo "== enabled"; dbus-run-session -- bash -c "$(declare -f serve); serve 0 1; ./h run; kill \$SRV" 2>&1
echo "== reader";  dbus-run-session -- bash -c "$(declare -f serve); serve 1 1; ./h run --keep-me; kill \$SRV" 2>&1
echo "== user";    dbus-run-session -- bash -c './h run --force-renderer-accessibility' 2>&1
echo "== nosession"; env -u DBUS_SESSION_BUS_ADDRESS DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent timeout 20 ./h run 2>&1; echo "rc=$?"
'''

SW = '[--force-renderer-accessibility]'
CASES = [
    ('nobus', 'no AT-SPI bus service', 'argc=2 [./h] [doc.docx] null_terminated=1', 'env=(unset)'),
    ('enabled', 'a11y on, no screen reader', 'argc=2 [./h] [doc.docx] null_terminated=1', 'env=(unset)'),
    ('reader', 'screen reader running', 'argc=4 [./h] [doc.docx] [--keep-me] %s null_terminated=1' % SW, 'env=1'),
    ('user', 'user passed the switch', 'argc=3 [./h] [doc.docx] %s null_terminated=1' % SW, 'env=1'),
    ('nosession', 'no session bus', 'argc=2 [./h] [doc.docx] null_terminated=1', 'env=(unset)'),
]


def main():
    if not shutil.which('docker') or subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True).returncode:
        print('SKIP docker or %s not available' % IMAGE); return 77
    if os.environ.get('BASELINE'):
        src = subprocess.run(['git', '-C', REPO, 'show', BASE_REF + ':' + REL], capture_output=True, text=True, check=True).stdout
    else:
        src = open(os.path.join(REPO, REL), encoding='utf-8').read()
    f1, f2, stmts = block(src, 'screenReaderEnabled'), block(src, 'prepareAccessibility'), cef_args_statements(src)
    if not (f1 and f2 and stmts):
        print('FAILED - main.cpp has no screen reader check before Init_CEF (screenReaderEnabled %s, '
              'prepareAccessibility %s, cef_args %s)' % tuple('found' if x else 'missing' for x in (f1, f2, stmts)))
        return 1
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, 'h.cpp'), 'w').write(HARNESS % {'fns': f1 + '\n\n' + f2, 'stmts': stmts})
        open(os.path.join(d, 'run.sh'), 'w').write(SCRIPT)
        r = subprocess.run(['docker', 'run', '--rm', '--memory=2g', '-v', d + ':/work:ro', IMAGE, 'bash', '/work/run.sh'],
                           capture_output=True, text=True, timeout=600)
    if r.returncode == 3:
        print(r.stdout + r.stderr); print('FAILED - harness did not build'); return 1
    sections, cur = {}, None
    for line in r.stdout.splitlines():
        if line.startswith('== '):
            cur = line[3:]; sections[cur] = []
        elif cur:
            sections[cur].append(line.strip())
    fails = 0
    print('#1828 CEF arguments and environment at start-up (Linux):')
    for key, what, want_args, want_env in CASES:
        out = sections.get(key, [])
        ok = want_args in out and want_env in out and not (key == 'nosession' and 'rc=124' in out)
        fails += not ok
        got = ' | '.join(l for l in out if l.startswith(('argc=', 'env=')))
        print('  %-26s %s  %s' % (what, got, 'ok' if ok else 'FAILED, want %s | %s' % (want_args, want_env)))
    print('FAILED' if fails else 'ok - a running screen reader (or the switch) turns Chromium accessibility on; nothing else changes')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
