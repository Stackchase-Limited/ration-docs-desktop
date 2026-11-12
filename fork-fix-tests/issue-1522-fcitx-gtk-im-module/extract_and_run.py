#!/usr/bin/env python3
"""
#1522 - fcitx5 cannot be used in the editors on KDE Plasma 6 Wayland (Linux):
Ctrl+Space does nothing in the document and only Latin text can be typed.

Cause: desktop-apps win-linux/src/main.cpp forces QT_QPA_PLATFORM=xcb and
GDK_BACKEND=x11, so the app runs on XWayland and the document view (CEF, which
takes keyboard input through a GTK input method context) finds an input method
only through GTK_IM_MODULE. fcitx5's own advice for Plasma 6 Wayland is to set
XMODIFIERS=@im=fcitx and leave GTK_IM_MODULE unset (native Wayland apps use the
compositor's text-input protocol); the thread's workaround is to set
GTK_IM_MODULE=fcitx by hand.
Fix: main.cpp sets GTK_IM_MODULE=fcitx itself, only when XMODIFIERS names fcitx
and GTK_IM_MODULE is not set at all. Any GTK_IM_MODULE the user sets (to
anything, e.g. "xim" or "gtk-im-context-simple") is left alone, so nobody who
configured an input method sees a change.

How it is tested: the REAL statement (the `if` after the #1522 comment that
follows qputenv("GDK_BACKEND", "x11")) is extracted from main.cpp and compiled
with qgetenv/qputenv/qEnvironmentVariableIsSet stand-ins over the real process
environment (getenv/setenv), then run for: Plasma 6 Wayland as fcitx advises;
the same with GTK_IM_MODULE set by the user (fcitx / ibus / empty string);
ibus as the session's method; no input method at all.
BASELINE=1 reads main.cpp from BASE_REF: there GTK_IM_MODULE stays unset in the
fcitx case, so the test FAILS.

  ./extract_and_run.py             RD_REPO (default ../../desktop-apps), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL

NOT claimed: that fcitx then works in the document on a real Plasma 6 Wayland
session - it needs fcitx5's GTK 3 module (fcitx5-gtk) installed, which GTK loads;
without it GTK falls back to its simple context, as today. Qt widgets (dialogs,
the tab bar) are not affected: the bundled Qt has no fcitx plugin. Needs a Linux
GUI check with fcitx5.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '301edac68^')
BASELINE = bool(os.environ.get('BASELINE'))
MAIN = 'win-linux/src/main.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', APPS, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(APPS, rel), encoding='utf-8').read()


src = read(MAIN)
at = src.find('qputenv("GDK_BACKEND", "x11");')
if at == -1:
    raise SystemExit('GDK_BACKEND line not found in main.cpp')
# the statements between the GDK_BACKEND line and InputArgs::init: the #1522 if (if any)
end = src.index('InputArgs::init(argc, argv);', at)
between = src[at + len('qputenv("GDK_BACKEND", "x11");'):end]
code = re.sub(r'/\*.*?\*/', '', between, flags=re.S).strip()

HARNESS = r'''
#include <string>
#include <stdio.h>
#include <stdlib.h>
struct QByteArray { std::string s; bool contains(const char* x) const { return s.find(x) != std::string::npos; } };
static QByteArray qgetenv(const char* n) { const char* v = getenv(n); return QByteArray{v ? v : ""}; }
static bool qEnvironmentVariableIsSet(const char* n) { return getenv(n) != nullptr; }
static bool qputenv(const char* n, const char* v) { return setenv(n, v, 1) == 0; }
int main()
{
    %s
    const char* g = getenv("GTK_IM_MODULE");
    printf("%%s\n", g ? (std::string("GTK_IM_MODULE=") + g).c_str() : "GTK_IM_MODULE unset");
    return 0;
}
''' % code

CASES = [
    ('Plasma 6 Wayland, fcitx5 as advised', {'XMODIFIERS': '@im=fcitx'}, 'GTK_IM_MODULE=fcitx'),
    ('fcitx, user set GTK_IM_MODULE=fcitx', {'XMODIFIERS': '@im=fcitx', 'GTK_IM_MODULE': 'fcitx'}, 'GTK_IM_MODULE=fcitx'),
    ('fcitx, user set GTK_IM_MODULE=ibus', {'XMODIFIERS': '@im=fcitx', 'GTK_IM_MODULE': 'ibus'}, 'GTK_IM_MODULE=ibus'),
    ('fcitx, user set GTK_IM_MODULE empty', {'XMODIFIERS': '@im=fcitx', 'GTK_IM_MODULE': ''}, 'GTK_IM_MODULE='),
    ('ibus session', {'XMODIFIERS': '@im=ibus'}, 'GTK_IM_MODULE unset'),
    ('no input method', {}, 'GTK_IM_MODULE unset'),
]

tmp = tempfile.mkdtemp(prefix='rd1522-')
failures = 0
try:
    open(os.path.join(tmp, 't.cpp'), 'w').write(HARNESS)
    cxx = shutil.which('clang++') or shutil.which('g++')
    subprocess.run([cxx, '-std=c++14', '-w', os.path.join(tmp, 't.cpp'), '-o', os.path.join(tmp, 't')], check=True)
    print('#1522 GTK input method module at start-up:')
    for what, env, want in CASES:
        e = {k: v for k, v in os.environ.items() if k not in ('XMODIFIERS', 'GTK_IM_MODULE')}
        e.update(env)
        got = subprocess.run([os.path.join(tmp, 't')], env=e, capture_output=True, text=True).stdout.strip()
        ok = got == want
        failures += not ok
        print('  %-40s -> %-24s %s' % (what, got, 'ok' if ok else 'FAILED, want ' + want))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
