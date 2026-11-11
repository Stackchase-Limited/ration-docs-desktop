#!/usr/bin/env python3
"""
#694 - "Working area not expand to window size" (Linux, 4K laptop): the editor
stays a fixed rectangle in the top-left corner of the window and the rest of the
window is an empty gray area; --force-scale=1/2 does not change it.

Cause.  On Linux every editor is drawn into an X window that QCefView owns
(qt_wrapper/src/qcefview.cpp, created in QCefView::Init). Whenever the panel
moves or resizes, QCefView::UpdateSize -> SetWindowSize sizes that X window and
CEF's own child windows with XConfigureWindow(parent->width(), parent->height()).
Those are Qt LOGICAL pixels; X windows are in device pixels. The app sets
AA_DisableHighDpiScaling (desktop-apps main.cpp), but that does not switch off
QT_SCALE_FACTOR (Qt reads it regardless - #1468 already divides it out of the
DPI). With QT_SCALE_FACTOR=2, which users and some distro setups export for 4K
screens, the panel is 2x as large on screen as the editor window: the editor
fills the top-left quarter, exactly the report's screenshot, and the app's own
scaling (--force-scale) cannot change it.

Fix.  SetWindowSize multiplies by the widget's devicePixelRatioF (1 without
QT_SCALE_FACTOR, so nothing changes for anyone else).

What this runs.  The REAL SetWindowSize (and the GetX11Size helper when present),
brace-matched from qcefview.cpp, compiled against Qt 5.15 in the
rd-linux-verify:24.04 image with AA_DisableHighDpiScaling set as the app sets it,
on Xvfb 3840x2160. A real top-level QWidget (800x600 logical) gets an X child
window created and reparented as QCefView::Init does; SetWindowSize is applied and
the X geometry of both is read back with XGetWindowAttributes. Expected: the editor
X window covers the whole panel, for QT_SCALE_FACTOR unset, 1.5 and 2.
  baseline: QT_SCALE_FACTOR=2 -> panel 1600x1200, editor 800x600 - FAILS

NOT claimed.  The app itself is not run on Linux (no Linux build of the app here),
so the screenshot is not reproduced pixel for pixel; QT_SCALE_FACTOR is the cause
that matches the report, but other setups were not investigated. Positions Qt
reports to CEF for drag and drop are still logical pixels under QT_SCALE_FACTOR
(not touched). QT_SCREEN_SCALE_FACTORS/QT_AUTO_SCREEN_SCALE_FACTOR are already
ignored under AA_DisableHighDpiScaling (checked: dpr stays 1).

  RD_REPO     desktop-sdk checkout (default ../../desktop-sdk)
  BASELINE=1  sources from BASE_REF via git show (default: parent of the fix) -> FAIL
  RD_IMAGE    docker image (default rd-linux-verify:24.04)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
BASE_REF = os.environ.get('BASE_REF', '963c2394^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
REL = 'ChromiumBasedEditors/lib/qt_wrapper/src/qcefview.cpp'


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(text, anchor, needles=(), optional=False):
    at = text.find(anchor)
    if at == -1:
        if optional:
            return ''
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    ob = text.index('{', at)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                body = text[at:i + 1]
                for n in needles:
                    if n not in body:
                        raise SystemExit('extracted %r is missing %r - wrong block?' % (anchor, n))
                return body
    raise SystemExit('unbalanced braces after %r' % anchor)


src = read(REL)
x11 = src[src.index('#include <X11/Xlib.h>'):]
helper = extract(x11, 'static int GetX11Size(', optional=True)
set_size = extract(x11, 'void SetWindowSize(Window window, QWidget* parent)', ('XConfigureWindow',))

MAIN_SRC = r'''
#include <QApplication>
#include <QWidget>
#include <X11/Xlib.h>
#include <cstdio>
static Display* g_d = nullptr;
static void* CefGetXDisplay() { return g_d; }

HELPER

SET_SIZE

static void geo(const char* n, Window w)
{
    XWindowAttributes a; XGetWindowAttributes(g_d, w, &a);
    printf("%s=%dx%d ", n, a.width, a.height);
}
int main(int argc, char** argv)
{
    QCoreApplication::setAttribute(Qt::AA_DisableHighDpiScaling);   // as desktop-apps main.cpp
    QApplication app(argc, argv);
    g_d = XOpenDisplay(nullptr);
    QWidget w; w.resize(800, 600); w.show();
    for (int i = 0; i < 20; i++) app.processEvents();
    // as QCefView::Init: an X window reparented into the widget's native window
    Window x11w = XCreateSimpleWindow(g_d, XDefaultRootWindow(g_d), 0, 0, w.width(), w.height(), 0, 0, 0xFFFFFFFF);
    XReparentWindow(g_d, x11w, w.winId(), 0, 0);
    XMapWindow(g_d, x11w);
    XSync(g_d, False);
    for (int i = 0; i < 20; i++) app.processEvents();
    SetWindowSize(x11w, &w);                                            // QCefView::UpdateSize
    XSync(g_d, False);
    printf("result dpr=%.2f ", w.devicePixelRatioF());
    geo("panel", w.winId()); geo("editor", x11w);
    printf("\n");
    return 0;
}
'''.replace('HELPER', helper).replace('SET_SIZE', set_size)

PRO = r'''
QT += widgets
CONFIG += c++11
LIBS += -lX11
TARGET = ws
SOURCES += main.cpp
'''

FACTORS = ['', '1.5', '2']

RUN_SH = r'''set -e
if ! command -v make >/dev/null || ! command -v Xvfb >/dev/null; then
  apt-get update -qq >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    make xvfb >/dev/null 2>&1
fi
cp -r "$1" /w && cd /w
qmake -qt=5 ws.pro >/dev/null 2>&1 || qmake ws.pro >/dev/null
make -s -j4 >build.log 2>&1 || { cat build.log; exit 1; }
Xvfb :62 -screen 0 3840x2160x24 -nolisten tcp -noreset >/dev/null 2>&1 &
xp=$!
for i in $(seq 50); do [ -e /tmp/.X11-unix/X62 ] && break; sleep 0.1; done
for f in FACTORS; do
  if [ "$f" = "-" ]; then
    DISPLAY=:62 QT_QPA_PLATFORM=xcb ./ws 2>/dev/null
  else
    DISPLAY=:62 QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=$f ./ws 2>/dev/null
  fi
done
kill $xp; wait $xp 2>/dev/null || true
'''.replace('FACTORS', ' '.join(f or '-' for f in FACTORS))


def main():
    work = tempfile.mkdtemp(prefix='rd0694-')
    try:
        open(os.path.join(work, 'main.cpp'), 'w').write(MAIN_SRC)
        open(os.path.join(work, 'ws.pro'), 'w').write(PRO)
        open(os.path.join(work, 'run.sh'), 'w').write(RUN_SH)
        out = subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % work, IMAGE,
                              'sh', '/t/run.sh', '/t'], capture_output=True, text=True)
        if out.returncode != 0:
            sys.stderr.write(out.stdout + out.stderr)
            raise SystemExit('harness failed to build/run')
        rows = [l for l in out.stdout.splitlines() if l.startswith('result ')]
        if len(rows) != len(FACTORS):
            sys.stderr.write(out.stdout + out.stderr)
            raise SystemExit('unexpected harness output')
        bad = 0
        for f, row in zip(FACTORS, rows):
            m = re.search(r'dpr=([\d.]+) panel=(\d+)x(\d+) editor=(\d+)x(\d+)', row)
            dpr, pw, ph, ew, eh = float(m.group(1)), *map(int, m.groups()[1:])
            if f and abs(dpr - float(f)) > 0.01:
                raise SystemExit('Qt did not apply QT_SCALE_FACTOR=%s (dpr %.2f) - harness broken, not a verdict' % (f, dpr))
            ok = (ew, eh) == (pw, ph)
            bad += not ok
            print('%s QT_SCALE_FACTOR=%-4s panel %dx%d, editor X window %dx%d' %
                  ('ok  ' if ok else 'FAIL', f or '-', pw, ph, ew, eh))
        label = 'BASELINE (%s)' % BASE_REF if BASELINE else 'fix'
        if bad:
            print('FAIL [%s]: the editor window does not fill its panel in %d of %d cases' % (label, bad, len(FACTORS)))
            sys.exit(1)
        print('PASS [%s]: the editor X window fills its panel at every QT_SCALE_FACTOR' % label)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
