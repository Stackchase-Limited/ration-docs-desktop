#!/usr/bin/env python3
"""
#2501 - "Changing resolution breaks layout on Ubuntu 26.04" (Linux, snap 9.4.0):
switching a laptop between its high-DPI built-in display and a 1080p external
one left the window half in the old scale - opened on the external screen and
moved to the built-in one, the tabs/title bar stayed tiny next to a large editor;
the other way round, huge tabs. Only closing and reopening helped.

Cause.  Two halves of the window are scaled by two different mechanisms on
Linux. The editor (CEF) re-zooms itself for the screen its view is on whenever
the view is resized (cefview.cpp CCefView_Private::UpdateSize -> CheckZoom ->
QDpiChecker::GetWidgetImplDpi). The Qt part - tab bar, title bar, buttons,
stylesheets - takes its scale once, when the window is built, and is re-scaled
only by CWindowBase::updateScaling. On Windows WM_DPICHANGED calls it; on Linux
nothing did: the old "mouse released after a move -> updateScaling()" check in
CWindowPlatform::event was removed as unused code in 2022 (upstream cdc9803fe)
and nothing replaced it. So when the window landed on a screen of another scale,
the editor followed and the chrome did not - the report's screenshots.

Fix.  CWindowPlatform::event (platform_linux/cwindowplatform.cpp) handles
QEvent::ScreenChangeInternal - what Qt sends a top-level widget when its window
moves to another QScreen (dragged there, or its screen was removed) - by calling
updateScaling() once the event queue is idle.

What this runs.  The REAL CWindowPlatform::event, brace-matched from
cwindowplatform.cpp, compiled with Qt 5.15 (rd-linux-verify:24.04 image) inside a
stub CWindowPlatform whose updateScaling() records the screen the window is on
when it is called. The window is a real top-level QMainWindow on a real two-output
X server: weston (x11 backend, --output-count=2, nested in Xvfb) with Xwayland, so
Qt sees two QScreens as on a laptop + external display under XWayland. The window
is shown on output 1 and moved to output 2 (weston's X window manager then puts it
back on output 1, a second screen change; both are counted).
  expected: updateScaling() runs after the screen change
  baseline: it never runs - FAILS

NOT claimed.  The real CWindowBase::updateScaling / setScreenScalingFactor (which
re-read the DPI and re-scale the chrome) are not run here, nor is the app; the two
weston outputs have the same DPI, so no scale change is shown, only that the
re-scale is now asked for. Whether the reporter's screens differ in DPI as our DPI
checker sees them (Xft.dpi wins since #1468) was not checked on their setup. The
editor-zoom half was traced by reading cefview.cpp, not run. Under the 9.4.0 build
the screenshot where both halves stay large (built-in -> external) is only partly
explained (CheckZoom runs on resize and may read the DPI before the desktop updates
it).

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  sources from BASE_REF via git show (default: parent of the fix) -> FAIL
  RD_IMAGE    docker image (default rd-linux-verify:24.04; weston/xwayland are
              installed into the container when missing - needs network)
"""
import os
import re
import subprocess
import sys
import io
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '276791931^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
REL = 'win-linux/src/windows/platform_linux/cwindowplatform.cpp'


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


EVENT = extract(read(REL), 'bool CWindowPlatform::event(QEvent * event)',
                ('WindowStateChange', 'CWindowBase::event(event)'))

MAIN_SRC = r'''
#include <QApplication>
#include <QMainWindow>
#include <QScreen>
#include <QWindow>
#include <QTimer>
#include <QCursor>
#include <QVariant>
#include <cstdio>

// --- stubs for what CWindowPlatform::event touches ---
struct AscAppManager { static bool isRtlEnabled() { return false; } };
class CWindowBase : public QMainWindow
{
public:
    void updateScaling(bool resize = true)
    {
        printf("updateScaling(resize=%d) on %s\n", (int)resize, qPrintable(screen()->name()));
        fflush(stdout);
        ++calls;
    }
    int calls = 0;
protected:
    virtual bool event(QEvent *e) override { return QMainWindow::event(e); }
    virtual void applyWindowState() {}
    virtual void adjustGeometry() {}
    QWidget *m_boxTitleBtns = nullptr;
    QWidget *m_pMainPanel = nullptr;
};
class CX11Decoration
{
public:
    void setMaximized(bool) {}
};
class CWindowPlatform : public CWindowBase, public CX11Decoration
{
public:
protected:
    virtual bool event(QEvent *event) override;
    void onWindowActivate(bool) {}
    void onLayoutDirectionChanged() {}
};

EVENT_SRC

int main(int argc, char **argv)
{
    QCoreApplication::setAttribute(Qt::AA_DisableHighDpiScaling);   // as desktop-apps main.cpp
    QApplication app(argc, argv);
    const QList<QScreen*> scr = app.screens();
    printf("screens %d\n", scr.size());
    if (scr.size() < 2) return 3;
    CWindowPlatform w;
    w.setGeometry(QRect(scr[0]->geometry().topLeft() + QPoint(100, 100), QSize(500, 300)));
    w.show();
    QTimer::singleShot(800, [&]() {
        printf("on %s, moving to %s\n", qPrintable(w.screen()->name()), qPrintable(scr[1]->name()));
        fflush(stdout);
        w.move(scr[1]->geometry().topLeft() + QPoint(100, 100));
    });
    QTimer::singleShot(2500, [&]() {
        printf("result calls=%d\n", w.calls);
        app.quit();
    });
    return app.exec();
}
'''.replace('EVENT_SRC', EVENT)

PRO = r'''
QT += widgets
CONFIG += c++11
TARGET = ws
SOURCES += main.cpp
'''

RUN_SH = r'''
if ! command -v weston >/dev/null || ! command -v Xwayland >/dev/null || ! command -v Xvfb >/dev/null; then
  apt-get update -qq >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    weston xwayland xvfb make >/dev/null 2>&1
fi
cd /w
qmake -qt=5 ws.pro >/dev/null 2>&1 || qmake ws.pro >/dev/null
make -s -j4 >build.log 2>&1 || { cat build.log; exit 1; }
export XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p -m 700 $XDG_RUNTIME_DIR
Xvfb :62 -screen 0 3400x1000x24 -nolisten tcp >/dev/null 2>&1 &
for i in $(seq 50); do [ -e /tmp/.X11-unix/X62 ] && break; sleep 0.1; done
DISPLAY=:62 weston --backend=x11 --renderer=pixman --output-count=2 --width=1600 --height=900 \
  --xwayland --socket=wl-rd2501 --log=/tmp/weston.log >/dev/null 2>&1 &
for i in $(seq 100); do [ -e /tmp/.X11-unix/X0 ] && break; sleep 0.1; done
sleep 1
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 30 ./ws 2>/dev/null
pkill weston; pkill Xvfb
exit 0
'''


def main():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, text in (('main.cpp', MAIN_SRC), ('ws.pro', PRO), ('run.sh', RUN_SH)):
            data = text.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    # sources are streamed in (host bind mounts may not reach the Docker VM)
    out = subprocess.run(['docker', 'run', '--rm', '-i', IMAGE, 'sh', '-c',
                          'mkdir /w && cd /w && tar xf - && sh run.sh >/tmp/out 2>&1; cat /tmp/out'],
                         input=buf.getvalue(), capture_output=True)
    text = out.stdout.decode(errors='replace')
    if 'result calls=' not in text:
        sys.stderr.write(text + out.stderr.decode(errors='replace'))
        raise SystemExit('harness failed to build/run (not a verdict)')
    for line in text.splitlines():
        if re.match(r'(screens|on |updateScaling|result)', line):
            print('  ' + line)
    m = re.search(r'screens (\d+)', text)
    if not m or int(m.group(1)) < 2:
        raise SystemExit('Qt did not see two screens - harness broken, not a verdict')
    if not re.search(r'on (\S+), moving to (\S+)', text):
        raise SystemExit('window was not moved - harness broken, not a verdict')
    calls = int(re.search(r'result calls=(\d+)', text).group(1))
    label = 'BASELINE (%s)' % BASE_REF if BASELINE else 'fix'
    if calls == 0:
        print('FAIL [%s]: the window moved to another screen and was never re-scaled' % label)
        sys.exit(1)
    print('PASS [%s]: a screen change re-runs updateScaling (%d call(s))' % (label, calls))


if __name__ == '__main__':
    main()
