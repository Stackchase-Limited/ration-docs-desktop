#!/usr/bin/env python3
"""
#661 - "Windows are generated under the taskbar when taskbar is in top position".
The report is from Windows; a second reporter (Fedora/GNOME, two monitors) saw the
same on Linux: an editor window placed so high that its title bar sat under the top
panel and could not be grabbed.

Cause (Linux).  Every window's first geometry goes through CWindowBase::startRect
(desktop-apps win-linux/src/windows/cwindowbase.cpp): the saved/cascaded rect is
intersected with Utils::getScreenGeometry(topLeft) so it lands on a screen.  On
Windows that function returns the monitor's rcWork (the area outside the taskbar),
but the Linux branch returned QDesktopWidget::screenGeometry - the WHOLE screen,
panels included.  So a saved "position" (or the +50,+50 cascade of an editor, or a
window dragged up and saved) with a top above the panel's bottom edge was kept as
is, and the window opened under the top panel.  Our window is frameless by default
on Linux (custom title bar, CX11Decoration), so the window manager does not pull a
title bar it does not know about back into view.

Fix.  The Linux branch returns availableGeometry() of the same (closest) screen -
the X work area (_NET_WORKAREA, what panels reserve), as rcWork on Windows.

What this runs.  The REAL Utils::getScreenGeometry (utils.cpp, the whole function
with both #ifdef branches, brace-matched) and CWindowBase::startRect
(cwindowbase.cpp), compiled against Qt 5.15 in the rd-linux-verify:24.04 image and
run on Xvfb (1920x1080) whose root window carries _NET_WORKAREA "0,32,1920,1016" - a
32 px top panel, as GNOME Shell / a top KDE or Xfce panel sets it.  Qt's xcb plugin
reads that property for QScreen/QDesktopWidget::availableGeometry.  Only
Utils::getScreenDpiRatio is a stub (1.0, i.e. 100% scaling); MAIN_WINDOW_DEFAULT_SIZE
comes from the real cwindowbase.h.

Scenarios (expected: the window's top edge is at or below the panel, y >= 32):
  A saved rect at y=0                       baseline keeps y=0 (under the panel) - FAILS
  B saved rect dragged up to y=-20          baseline keeps y=0 after clipping - FAILS
  C no saved rect (first start)             default rect, centered - same both ways
  D saved rect already inside the work area unchanged both ways

NOT claimed.  The Windows report itself is not reproduced (no Windows here); there
startRect already clips to rcWork, so what places a window under a TOP taskbar on
Windows is elsewhere (window/frame geometry of the borderless window) and is not
touched.  Restoring from maximized (the Fedora reporter's double-click) uses the
geometry the window started with plus whatever the window manager does; that is not
driven here.  No window manager runs; multi-monitor work areas are not exercised.

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  sources from BASE_REF via git show (default: parent of the fix) -> FAIL
  RD_IMAGE    docker image (default rd-linux-verify:24.04)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '706e29c81^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')

UTILS = 'win-linux/src/utils.cpp'
WINBASE = 'win-linux/src/windows/cwindowbase.cpp'
WINBASE_H = 'win-linux/src/windows/cwindowbase.h'


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(text, anchor, needles=()):
    at = text.find(anchor)
    if at == -1:
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


get_geom = extract(read(UTILS), 'QRect Utils::getScreenGeometry(const QPoint& leftTop)', ('#ifdef __linux',))
start_rect = extract(read(WINBASE), 'QRect CWindowBase::startRect(const QRect &rc, double &dpi)',
                     ('Utils::getScreenGeometry',))
default_size = [l for l in read(WINBASE_H).splitlines() if l.startswith('#define MAIN_WINDOW_DEFAULT_SIZE')]
if not default_size:
    raise SystemExit('MAIN_WINDOW_DEFAULT_SIZE not found in cwindowbase.h')

MAIN_SRC = r'''
#include <QApplication>
#include <QDesktopWidget>
#include <QScreen>
#include <QRect>
#include <cstdio>
#include <cstdlib>

DEFAULT_SIZE

struct Utils {
    static QRect getScreenGeometry(const QPoint&);
    static double getScreenDpiRatio(const QPoint&) { return 1.0; }   // stub: 100%
};
struct CWindowBase {
    static QRect startRect(const QRect &rc, double &dpi);
};

GET_GEOM

START_RECT

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QRect avail = app.primaryScreen()->availableGeometry();
    printf("screen=%d,%d %dx%d avail=%d,%d %dx%d\n",
           app.primaryScreen()->geometry().x(), app.primaryScreen()->geometry().y(),
           app.primaryScreen()->geometry().width(), app.primaryScreen()->geometry().height(),
           avail.x(), avail.y(), avail.width(), avail.height());
    for (int i = 1; i + 3 < argc; i += 4) {
        QRect in(atoi(argv[i]), atoi(argv[i + 1]), atoi(argv[i + 2]), atoi(argv[i + 3]));
        double dpi = 0;
        QRect out = CWindowBase::startRect(in, dpi);
        printf("rect in=%d,%d %dx%d out=%d,%d %dx%d\n", in.x(), in.y(), in.width(), in.height(),
               out.x(), out.y(), out.width(), out.height());
    }
    return 0;
}
'''.replace('DEFAULT_SIZE', default_size[0]).replace('GET_GEOM', get_geom).replace('START_RECT', start_rect)

PRO = r'''
QT += widgets
CONFIG += c++11
TARGET = sr
SOURCES += main.cpp
'''

# name, input rect (x y w h; 0 0 0 0 = empty), predicate on the output rect
PANEL = 32
SCENARIOS = [
    ('A saved rect at y=0 (top under the panel)', (100, 0, 1200, 740),
     lambda o: o[1] >= PANEL),
    ('B saved rect dragged up to y=-20', (300, -20, 1000, 700),
     lambda o: o[1] >= PANEL),
    ('C first start (no saved rect): default, centered', (0, 0, 0, 0),
     lambda o: o[1] >= PANEL and o[2:] == (1200, 740)),
    ('D rect inside the work area: unchanged', (200, 100, 1000, 700),
     lambda o: o == (200, 100, 1000, 700)),
]

RUN_SH = r'''set -e
if ! command -v make >/dev/null || ! command -v Xvfb >/dev/null || ! command -v xprop >/dev/null; then
  apt-get update -qq >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    make xvfb x11-utils >/dev/null
fi
cd "$1"
qmake -qt=5 sr.pro >/dev/null 2>&1 || qmake sr.pro >/dev/null
make -s -j4 >build.log 2>&1 || { cat build.log; exit 1; }
Xvfb :61 -screen 0 1920x1080x24 -nolisten tcp -noreset >/dev/null 2>&1 &
xp=$!
for i in $(seq 50); do [ -e /tmp/.X11-unix/X61 ] && break; sleep 0.1; done
DISPLAY=:61 xprop -root -f _NET_WORKAREA 32c -set _NET_WORKAREA "0, 32, 1920, 1016"
DISPLAY=:61 QT_QPA_PLATFORM=xcb ./sr ARGS 2>/dev/null
kill $xp; wait $xp 2>/dev/null || true
'''.replace('ARGS', ' '.join('%d %d %d %d' % s[1] for s in SCENARIOS))


def main():
    work = tempfile.mkdtemp(prefix='rd0661-')
    try:
        open(os.path.join(work, 'main.cpp'), 'w').write(MAIN_SRC)
        open(os.path.join(work, 'sr.pro'), 'w').write(PRO)
        open(os.path.join(work, 'run.sh'), 'w').write(RUN_SH)
        out = subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % work, IMAGE,
                              'sh', '/t/run.sh', '/t'], capture_output=True, text=True)
        if out.returncode != 0:
            sys.stderr.write(out.stdout + out.stderr)
            raise SystemExit('harness failed to build/run')
        lines = out.stdout.splitlines()
        head = [l for l in lines if l.startswith('screen=')]
        rects = [l for l in lines if l.startswith('rect ')]
        if not head or len(rects) != len(SCENARIOS):
            sys.stderr.write(out.stdout + out.stderr)
            raise SystemExit('unexpected harness output')
        print(head[0])
        if 'avail=0,%d ' % PANEL not in head[0]:
            raise SystemExit('Qt did not pick up _NET_WORKAREA - harness broken, not a verdict')
        bad = 0
        for (name, _, ok_fn), line in zip(SCENARIOS, rects):
            o = line.split('out=')[1]
            xy, wh = o.split()
            x, y = map(int, xy.split(','))
            w, h = map(int, wh.split('x'))
            ok = ok_fn((x, y, w, h))
            bad += not ok
            print('%s  %-50s %s' % ('ok  ' if ok else 'FAIL', name, line))
        label = 'BASELINE (%s)' % BASE_REF if BASELINE else 'fix'
        if bad:
            print('FAIL [%s]: %d of %d start rects wrong' % (label, bad, len(SCENARIOS)))
            sys.exit(1)
        print('PASS [%s]: every start rect is inside the work area (below a %d px top panel)' % (label, PANEL))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
