#!/usr/bin/env python3
"""
#2528 - switching document tabs flashes white (Linux, dark theme).

On Linux each editor is embedded in an X window that QCefView::Init creates with
XCreateSimpleWindow and a fixed background pixel - 0xF4F4F4 for editors, white
otherwise. The X server fills a window with its background pixel whenever it is
mapped, before any client draws. A tab switch unmaps the panel being left and
maps the one being shown, so until Chromium presents its next frame the shown
tab is light gray: a white flash on every switch in a dark theme. The theme color
already reached QCefView (SetBackgroundCefColor, from CTabPanel and on theme
change) but only for the Qt stylesheet and the CEF browser settings.

This extracts the real QCefView::Init (the X11 one), QCefView::SetBackgroundCefColor
and any static helpers they use from qt_wrapper/src/qcefview.cpp by brace matching,
compiles them into a stub QCefView, and checks what background the X server would
fill the embed window with when a tab is shown, in the three orders the app uses:
  1. CTabPanel: SetBackgroundCefColor(theme) then Init (editor tabs)
  2. start page: Init then SetBackgroundCefColor(theme)
  3. theme change on an existing tab: SetBackgroundCefColor(new theme)
and that a view nobody colors keeps its old white background.

By default Xlib is a stub that records each window's background pixel. With
RD_REAL_X11=1 it links real libX11 and needs a DISPLAY (e.g. Xvfb): the harness
then maps/unmaps the parent like a tab switch and reads back the pixel the server
painted with XGetImage, with no client drawing at all.

NOT claimed: that nothing else can flash. Chromium's own frame presentation after
the map is not exercised (no CEF here), and Windows/macOS are separate code paths
(this file's X11 section only).

BASELINE=1 reads the source at BASE_REF, where the window is light gray: must fail.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk'))
REL = 'ChromiumBasedEditors/lib/qt_wrapper/src/qcefview.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', 'ce7cdbdb^')
REAL = bool(os.environ.get('RD_REAL_X11'))

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()


def matched(text, start):
    depth = 0
    for i in range(text.index('{', start), len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


# the X11 section of the file
x11_at = src.index('#include <X11/Xlib.h>')
x11 = src[x11_at:]

init_at = x11.index('void QCefView::Init()')
init = matched(x11, init_at)
assert 'XCreateSimpleWindow' in init, 'extracted the wrong Init'

set_at = src.index('void QCefView::SetBackgroundCefColor(')
set_bg = matched(src, set_at)
assert 'setStyleSheet' in set_bg, 'extracted the wrong SetBackgroundCefColor'

# static helpers defined between the Xlib include and Init (none at baseline)
helpers = []
for m in re.finditer(r'^static [^\n;]*\([^\n;]*\)\n\{', x11[:init_at], re.M):
    helpers.append(matched(x11, m.start()))

PRELUDE_STUB = r'''
#include <cstdio>
#include <map>
typedef unsigned long Window;
struct Display {};
static Display g_display;
static std::map<Window, unsigned long> g_bg;  // what the server fills each window with
static Window g_next = 100;
static Window XDefaultRootWindow(Display*) { return 1; }
static Window XCreateSimpleWindow(Display*, Window, int, int, unsigned, unsigned, unsigned, unsigned long, unsigned long bg)
{ Window w = g_next++; g_bg[w] = bg; return w; }
static int XReparentWindow(Display*, Window, Window, int, int) { return 0; }
static int XMapWindow(Display*, Window) { return 0; }
static int XDestroyWindow(Display*, Window) { return 0; }
static int XSetWindowBackground(Display*, Window w, unsigned long bg) { g_bg[w] = bg; return 0; }
static int XFlush(Display*) { return 0; }
void* CefGetXDisplay() { return &g_display; }
static Window make_parent() { return g_next++; }
static unsigned long shown_pixel(Window, Window cef) { return g_bg[cef] & 0xFFFFFF; }
'''

PRELUDE_REAL = r'''
#include <cstdio>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
static Display* g_display = XOpenDisplay(nullptr);
void* CefGetXDisplay() { return g_display; }
static Window make_parent()
{
    XSetWindowAttributes a; a.background_pixmap = None;   // like Qt's native windows
    Window w = XCreateWindow(g_display, XDefaultRootWindow(g_display), 0, 0, 64, 64, 0, CopyFromParent,
                             InputOutput, CopyFromParent, CWBackPixmap, &a);
    XSync(g_display, False);
    return w;
}
// a tab switch: the panel is unmapped, then mapped again; nothing draws in between
static unsigned long shown_pixel(Window parent, Window)
{
    XUnmapWindow(g_display, parent); XSync(g_display, False);
    XMapWindow(g_display, parent); XSync(g_display, False);
    XImage* img = XGetImage(g_display, parent, 32, 32, 1, 1, AllPlanes, ZPixmap);
    unsigned long p = XGetPixel(img, 0, 0) & 0xFFFFFF;
    XDestroyImage(img);
    return p;
}
'''

QT_STUB = r'''
#include <string>
enum CefViewWrapperType { cvwtSimple = 0, cvwtEditor = 1 };
typedef unsigned long WindowHandleId;
struct QString {
    std::string s;
    QString(const char* c = "") : s(c) {}
    QString(const std::string& c) : s(c) {}
    static QString number(int v, int base) { char b[16]; std::snprintf(b, 16, base == 16 ? "%x" : "%d", v); return QString(b); }
    int length() const { return (int)s.size(); }
};
static QString operator+(const QString& a, const QString& b) { return QString(a.s + b.s); }
static QString operator+(const char* a, const QString& b) { return QString(std::string(a) + b.s); }
static QString operator+(const QString& a, const char* b) { return QString(a.s + b); }
struct QWindow { WindowHandleId winId() { return 0; } };
struct CCefView { CefViewWrapperType t; CefViewWrapperType GetType() { return t; } };
struct QCefViewProps { QWindow* m_window; };
struct QCefView;
struct QCefEmbedWindow : QWindow { QCefEmbedWindow(QCefView*) {} };
struct QCefView {
    unsigned char backgroundR = 255, backgroundG = 255, backgroundB = 255;   // CCefViewWidgetImpl defaults
    WindowHandleId cef_handle = 0;
    unsigned int cef_width = 0, cef_height = 0;
    CCefView* m_pCefView = nullptr;
    QCefViewProps* m_pProperties = nullptr;
    Window parent;
    QString style;
    int width() { return 64; }
    int height() { return 64; }
    Window winId() { return parent; }
    void setAcceptDrops(bool) {}
    void setStyleSheet(const QString& s) { style = s; }
    bool IsSupportLayers() { return true; }
    void Init();
    void SetBackgroundCefColor(unsigned char r, unsigned char g, unsigned char b);
};
'''

MAIN = r'''
static int fails = 0;
static void check(const char* what, unsigned long got, unsigned long want)
{
    std::printf("%s %s: shown 0x%06lx, want 0x%06lx\n", got == want ? "ok  " : "FAIL", what, got, want);
    if (got != want) fails++;
}
int main()
{
    CCefView editor{cvwtEditor}, simple{cvwtSimple};
    {   // CTabPanel: color first (dark theme window background), then Create -> Init
        QCefView v; v.parent = make_parent(); v.m_pCefView = &editor;
        v.SetBackgroundCefColor(0x33, 0x33, 0x33);
        v.Init();
        check("editor tab in a dark theme", shown_pixel(v.parent, v.cef_handle), 0x333333);
        // theme change: CAscTabWidget::applyUITheme -> CTabPanel::setBackground
        v.SetBackgroundCefColor(0x22, 0x22, 0x22);
        check("same tab after switching to another dark theme", shown_pixel(v.parent, v.cef_handle), 0x222222);
    }
    {   // start page: Create -> Init first, SetBackgroundCefColor after
        QCefView v; v.parent = make_parent(); v.m_pCefView = &simple;
        v.Init();
        v.SetBackgroundCefColor(0x33, 0x33, 0x33);
        check("start page in a dark theme", shown_pixel(v.parent, v.cef_handle), 0x333333);
    }
    {   // a non-editor view nobody colors: unchanged white
        QCefView v; v.parent = make_parent(); v.m_pCefView = &simple;
        v.Init();
        check("uncolored view stays white", shown_pixel(v.parent, v.cef_handle), 0xFFFFFF);
    }
    {   // CTabPanel without a theme passes 244,244,244: unchanged light gray
        QCefView v; v.parent = make_parent(); v.m_pCefView = &editor;
        v.SetBackgroundCefColor(244, 244, 244);
        v.Init();
        check("editor tab with the default panel color", shown_pixel(v.parent, v.cef_handle), 0xF4F4F4);
    }
    return fails ? 1 : 0;
}
'''

code = (PRELUDE_REAL if REAL else PRELUDE_STUB) + QT_STUB + '#define _LINUX\n' \
    + '\n'.join(helpers) + '\n' + set_bg + '\n' + init + '\n' + MAIN

with tempfile.TemporaryDirectory() as tmp:
    cpp = os.path.join(tmp, 'harness.cpp')
    exe = os.path.join(tmp, 'harness')
    open(cpp, 'w').write(code)
    cxx = os.environ.get('CXX', 'c++')
    cmd = [cxx, '-std=c++14', '-w', cpp, '-o', exe] + (['-lX11'] if REAL else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(2)
    r = subprocess.run([exe], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    print('PASS' if r.returncode == 0 else 'FAIL (#2528: the X window a tab is embedded in is not in the theme color)')
    sys.exit(r.returncode)
