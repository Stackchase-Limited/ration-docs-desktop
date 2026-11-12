#!/usr/bin/env python3
"""
#858 (Windows/Linux part) - "Fullscreen mode": no key puts the app in full screen.

macOS got Ctrl+Cmd+F (desktop-apps 483116cf19, issue-0858-mac-full-screen-shortcut).
On Windows and Linux the only full screen was the slide show's own widget
(WindowHelper::constructFullscreenWidget); F11 reached the shell as CEF's
ONKEYBOARDDOWN (cefview.cpp OnPreKeyEvent forwards every raw key down) and the
key switch in CAscApplicationManagerWrapper::processCommonEvent had no case for it.
The editors bind no F11 (sdkjs/web-apps only name the key code), so the key is free.

Fix (desktop-apps b205e256b).  Behaviour chosen: as F11 in browsers - the WHOLE
window (tab bar and title bar still shown) goes full screen, F11 again leaves, and
Esc is not bound (it stays with the editors' dialogs and selection, as browsers do
for F11 full screen). The Qt::WindowFullScreen flag is toggled, so a maximized
window comes back maximized. A window running a slide show (its own full screen
path), a hidden or minimized window and presenter windows are left alone.
  - case 0x7a (VK_F11) -> CAscApplicationManagerWrapper_Private::toggleWindowFullScreen
  - Linux CWindowPlatform::adjustGeometry: no custom-frame border in full screen;
    mouseMoveEvent: no title-bar drag/resize in full screen.
  - Windows cwindowplatform.cpp WM_NCCALCSIZE/WM_NCHITTEST/adjustGeometry and
    caption.h: not compiled or run here (no Windows build) - see NOT claimed.

What this runs.  The REAL key switch (the whole `switch ( data->get_KeyCode() )` of
the ONKEYBOARDDOWN case), the REAL toggleWindowFullScreen, and the REAL Linux
CWindowPlatform::event + adjustGeometry, brace-matched from the sources and
compiled with Qt 5.15 (rd-linux-verify:24.04) against stand-ins for the windows,
view ids and app manager. The windows are real top-level QMainWindows on a real X
server with a window manager that does EWMH full screen (weston's XWayland, nested
in Xvfb). Key events are fed to the switch as CEF would deliver them:
  F11 from a document tab       -> main window full screen, covering the screen, no margins
  Esc while full screen         -> still full screen
  F11 again                     -> back to the earlier normal geometry
  F11 while a slide show runs   -> nothing
  maximized, F11, F11           -> full screen, then maximized again
  F11 from a separate editor    -> that window only
BASELINE=1 (sources from BASE_REF, the parent of the fix): F11 does nothing - FAILS.

NOT claimed.  The Windows half (frameless WM_NCCALCSIZE etc.) needs a Windows build
and GUI check: whether Qt's full screen popup style plus our NC handling gives an
exact screen-sized client area, taskbar on top behaviour, Snap. The real app was not
run on Linux (key delivery from CEF to processCommonEvent is the path Ctrl+N/#200
and Ctrl+Q/#1270 already use); F11 with keyboard focus in Qt chrome rather than a
CEF view is not handled. Real GNOME/KDE window managers not tried.

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  sources from BASE_REF via git show (default b205e256b^) -> FAIL
  RD_IMAGE    docker image (default rd-linux-verify:24.04; weston/xwayland/xvfb are
              installed into the container when missing - needs network)
"""
import io
import os
import re
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', 'b205e256b^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
WRAP = 'win-linux/src/cascapplicationmanagerwrapper.cpp'
PRIV = 'win-linux/src/cascapplicationmanagerwrapper_private.h'
PLAT = 'win-linux/src/windows/platform_linux/cwindowplatform.cpp'


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(text, anchor, start=0, needles=(), optional=False):
    at = text.find(anchor, start)
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


wrap = read(WRAP)
kb = wrap.find('case ASC_MENU_EVENT_TYPE_CEF_ONKEYBOARDDOWN')
if kb == -1:
    raise SystemExit('ONKEYBOARDDOWN case not found - the extractor needs updating')
SWITCH = extract(wrap, 'switch ( data->get_KeyCode() )', kb, ('case VK_F4', 'case 0x4f'))
HELPER = extract(read(PRIV), 'auto toggleWindowFullScreen(int id) -> bool', optional=True)
plat = read(PLAT)
ADJUST = extract(plat, 'void CWindowPlatform::adjustGeometry()', needles=('setContentsMargins',))
EVENT = extract(plat, 'bool CWindowPlatform::event(QEvent * event)', needles=('WindowStateChange',))

MAIN_SRC = r'''
#include <QApplication>
#include <QMainWindow>
#include <QScreen>
#include <QWindow>
#include <QTimer>
#include <QPointer>
#include <QVariant>
#include <QCursor>
#include <cstdio>
#include <vector>
#include <functional>

#define VK_F4 0x73

// --- stand-ins for what the extracted code touches ---
struct AscAppManager {
    static bool isRtlEnabled() { return false; }
    static void closeAppWindows() { printf("closeAppWindows\n"); }
};
class CWindowBase : public QMainWindow
{
public:
    void updateScaling(bool = true) {}
    virtual void adjustGeometry() = 0;
protected:
    virtual bool event(QEvent *e) override { return QMainWindow::event(e); }
    virtual void applyWindowState() {}
    double m_dpiRatio = 1.0;
    QWidget *m_boxTitleBtns = nullptr;
    QWidget *m_pMainPanel = nullptr;
};
class CX11Decoration
{
public:
    void setMaximized(bool) {}
    bool isDecorated() { return false; }            // the app's custom (frameless) title bar
    static int customWindowBorderWith() { return 4; }
};
class CWindowPlatform : public CWindowBase, public CX11Decoration
{
public:
    virtual void adjustGeometry() override;
protected:
    virtual bool event(QEvent *event) override;
    void onWindowActivate(bool) {}
    void onLayoutDirectionChanged() {}
};

ADJUST_SRC

EVENT_SRC

class CMainWindow : public CWindowPlatform
{
public:
    bool slideshow = false;
    bool holdView(int id) const { return id == 1 || id == 10; }    // start page, a document tab
    bool isSlideshowMode() const { return slideshow; }
    bool isAboutToClose() const { return false; }
};
class CEditorWindow : public CWindowPlatform
{
public:
    bool slideshow = false;
    bool isSlideshowMode() const { return slideshow; }
    int closeWindow() { printf("closeWindow\n"); return 0; }
};

static CMainWindow *g_main = nullptr;
static CEditorWindow *g_editor = nullptr;

struct CAscKeyboardDown {
    int key; bool ctrl, shift, alt;
    int get_KeyCode() const { return key; }
    bool get_IsCtrl() const { return ctrl; }
    bool get_IsShift() const { return shift; }
    bool get_IsAlt() const { return alt; }
};
struct CAscCefMenuEvent {
    void *m_pData; int sender;
    int get_SenderId() const { return sender; }
};
struct AppManager {
    CEditorWindow *editorWindowFromViewId(int id) { return id == 2 ? g_editor : nullptr; }
};
struct Private {
    AppManager m_appmanager;
    CMainWindow *mainWindow() { return g_main; }
    bool sendCreateNewEvent(int) { return false; }
    void sendOpenFolderEvent(int) {}
    HELPER_SRC
};
struct Wrapper : public QObject {
    Private priv;
    Private *m_private = &priv;
    CEditorWindow *editorWindowFromViewId(int id) { return priv.m_appmanager.editorWindowFromViewId(id); }
    CMainWindow *mainWindow() { return g_main; }
    std::vector<int> closeQueue() { return {}; }
    static void reopenClosedDocument() {}
    bool onKey(CAscCefMenuEvent *event)
    {
        CAscKeyboardDown * data = static_cast<CAscKeyboardDown *>(event->m_pData);
        SWITCH_SRC
        return false;
    }
};

static QString st(QMainWindow *w)
{
    Qt::WindowStates s = w->windowState();
    QString r;
    if (s & Qt::WindowFullScreen) r += "full";
    if (s & Qt::WindowMaximized) r += r.isEmpty() ? "max" : "+max";
    if (r.isEmpty()) r = "normal";
    QRect g = w->geometry();
    QMargins m = w->contentsMargins();
    return QString("%1 %2x%3+%4+%5 margins=%6").arg(r).arg(g.width()).arg(g.height())
            .arg(g.x()).arg(g.y()).arg(m.left() + m.top() + m.right() + m.bottom());
}

int main(int argc, char **argv)
{
    QCoreApplication::setAttribute(Qt::AA_DisableHighDpiScaling);
    QApplication app(argc, argv);
    QRect scr = app.primaryScreen()->geometry();
    printf("screen %dx%d\n", scr.width(), scr.height());
    CMainWindow main; CEditorWindow editor;
    g_main = &main; g_editor = &editor;
    main.setGeometry(100, 100, 500, 300); main.show();
    editor.setGeometry(700, 120, 400, 300); editor.show();
    Wrapper wr;
    auto key = [&](int code, int sender, bool ctrl = false) {
        CAscKeyboardDown d{code, ctrl, false, false};
        CAscCefMenuEvent e{&d, sender};
        bool r = wr.onKey(&e);
        printf("key 0x%x from view %d -> handled=%d\n", code, sender, (int)r);
    };
    std::vector<std::function<void()>> steps = {
        [&]{ printf("start main: %s\n", qPrintable(st(&main))); key(0x7a, 10); },
        [&]{ printf("after F11 main: %s editor: %s\n", qPrintable(st(&main)), qPrintable(st(&editor))); key(0x1b, 10); },
        [&]{ printf("after Esc main: %s\n", qPrintable(st(&main))); key(0x7a, 10); },
        [&]{ printf("after F11 again main: %s\n", qPrintable(st(&main))); main.slideshow = true; key(0x7a, 10); },
        [&]{ printf("slideshow F11 main: %s\n", qPrintable(st(&main))); main.slideshow = false; main.showMaximized(); },
        [&]{ printf("maximized main: %s\n", qPrintable(st(&main))); key(0x7a, 1); },
        [&]{ printf("max F11 main: %s\n", qPrintable(st(&main))); key(0x7a, 1); },
        [&]{ printf("max F11 F11 main: %s\n", qPrintable(st(&main))); key(0x7a, 2); },
        [&]{ printf("editor F11 editor: %s main: %s\n", qPrintable(st(&editor)), qPrintable(st(&main))); key(0x7a, 2); },
        [&]{ printf("editor F11 F11 editor: %s\n", qPrintable(st(&editor))); printf("done\n"); fflush(stdout); app.quit(); },
    };
    for (size_t i = 0; i < steps.size(); ++i)
        QTimer::singleShot(800 + 900 * int(i), [&, i]{ steps[i](); fflush(stdout); });
    return app.exec();
}
'''.replace('ADJUST_SRC', ADJUST).replace('EVENT_SRC', EVENT).replace('SWITCH_SRC', SWITCH) \
   .replace('HELPER_SRC', HELPER)

PRO = r'''
QT += widgets
CONFIG += c++11
TARGET = fs
SOURCES += main.cpp
'''

RUN_SH = r'''
if ! command -v weston >/dev/null || ! command -v Xwayland >/dev/null || ! command -v Xvfb >/dev/null; then
  apt-get update -qq >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    weston xwayland xvfb make >/dev/null 2>&1
fi
cd /w
qmake -qt=5 fs.pro >/dev/null 2>&1 || qmake fs.pro >/dev/null
make -s -j4 >build.log 2>&1 || { cat build.log; exit 1; }
export XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p -m 700 $XDG_RUNTIME_DIR
Xvfb :62 -screen 0 1800x1000x24 -nolisten tcp >/dev/null 2>&1 &
for i in $(seq 50); do [ -e /tmp/.X11-unix/X62 ] && break; sleep 0.1; done
DISPLAY=:62 weston --backend=x11 --renderer=pixman --width=1600 --height=900 \
  --xwayland --socket=wl-rd858 --log=/tmp/weston.log >/dev/null 2>&1 &
for i in $(seq 100); do [ -e /tmp/.X11-unix/X0 ] && break; sleep 0.1; done
sleep 1
DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 40 ./fs 2>/dev/null
pkill weston; pkill Xvfb
exit 0
'''


def main():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, text in (('main.cpp', MAIN_SRC), ('fs.pro', PRO), ('run.sh', RUN_SH)):
            data = text.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    out = subprocess.run(['docker', 'run', '--rm', '-i', IMAGE, 'sh', '-c',
                          'mkdir /w && cd /w && tar xf - && sh run.sh >/tmp/out 2>&1; cat /tmp/out'],
                         input=buf.getvalue(), capture_output=True)
    text = out.stdout.decode(errors='replace')
    if 'done' not in text:
        sys.stderr.write(text + out.stderr.decode(errors='replace'))
        raise SystemExit('harness failed to build/run (not a verdict)')
    lines = {}
    for line in text.splitlines():
        if re.match(r'(screen|start|after|slideshow|maximized|max |editor|key )', line):
            print('  ' + line)
        head = re.match(r'([a-zA-Z0-9 ]+?) (?:main|editor):', line)
        for m in re.finditer(r'(main|editor): (\S+) (\d+)x(\d+)\+(-?\d+)\+(-?\d+) margins=(\d+)', line):
            lines[head.group(1) + ' ' + m.group(1)] = (m.group(2), int(m.group(3)), int(m.group(4)),
                                                       int(m.group(5)), int(m.group(6)), int(m.group(7)))
    sw, sh = map(int, re.search(r'screen (\d+)x(\d+)', text).groups())

    def get(k):
        if k not in lines:
            raise SystemExit('missing output %r - harness broken, not a verdict' % k)
        return lines[k]

    fails = []

    def check(ok, what):
        print('  %s %s' % ('ok  ' if ok else 'FAIL', what))
        if not ok:
            fails.append(what)

    start = get('start main')
    full = get('after F11 main')
    check(full[0] == 'full' and full[1:3] == (sw, sh) and full[5] == 0,
          'F11 from a tab: main window full screen over the whole screen, no border margins')
    check(get('after Esc main')[0] == 'full', 'Esc does not leave full screen')
    back = get('after F11 again main')
    check(back[0] == 'normal' and back[1:3] == start[1:3], 'F11 again: back to the earlier window size')
    check(get('slideshow F11 main')[0] == 'normal', 'F11 during a slide show leaves the window alone')
    check(get('max F11 main')[0].startswith('full'), 'maximized window: F11 enters full screen')
    check(get('max F11 F11 main')[0] == 'max', 'maximized window: F11 again comes back maximized')
    ed = get('editor F11 editor')
    check(ed[0] == 'full' and get('editor F11 main')[0] == 'max',
          'F11 in a separate editor window: that window only')
    check(get('editor F11 F11 editor')[0] == 'normal', 'editor window: F11 again leaves full screen')

    label = 'BASELINE (%s)' % BASE_REF if BASELINE else 'fix'
    if fails:
        print('FAIL [%s]: %d check(s) failed' % (label, len(fails)))
        sys.exit(1)
    print('PASS [%s]: F11 toggles whole-window full screen' % label)


if __name__ == '__main__':
    main()
