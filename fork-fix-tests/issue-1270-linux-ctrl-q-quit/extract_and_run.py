#!/usr/bin/env python3
"""
#1270 - "No keyboard shortcut to quit on Linux". Ctrl+Q, the quit key of every Linux
desktop, did nothing; the only way out was the window's close button.

Every key pressed in a CEF view (start page or editor) reaches the wrapper as
ASC_MENU_EVENT_TYPE_CEF_ONKEYBOARDDOWN, handled in
CAscApplicationManagerWrapper::processCommonEvent (desktop-apps
win-linux/src/cascapplicationmanagerwrapper.cpp), which knew Alt+F4 and Ctrl+O only. The
fix adds Ctrl+Q on Linux: AscAppManager::closeAppWindows(), the close the session manager
and the updater already use (every editor window, then the main window, each asking about
unsaved changes; cancelling one stops the quit). A second Ctrl+Q while that close is
running is ignored, as setupSessionManagement does.

What runs here: the REAL `case ASC_MENU_EVENT_TYPE_CEF_ONKEYBOARDDOWN: {...}` block,
brace-matched out of the file and compiled with g++ in the rd-linux-verify:24.04 image
(so __linux is the compiler's own), inside a stub wrapper that counts closeAppWindows()
calls and records what else the block did. Key codes are the Windows virtual-key codes
CEF reports (desktop-sdk cefview.cpp OnPreKeyEvent passes event.windows_key_code).

Claimed: Ctrl+Q starts exactly one app close and is consumed; a repeat while the close
queue is busy or the main window is already closing does not queue the windows again;
Ctrl+Shift+Q, Ctrl+Alt+Q, Alt+Q (the editors' chat panel) and plain Q are left alone;
Ctrl+O and Alt+F4 behave as before. NOT claimed: the real close sequence with save
prompts (unchanged code, needs a GUI check on Linux); Ctrl+W on the start page still
does not quit (the second wish in the report - left as is).

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  source from BASE_REF via git show (default: parent of the fix) -> FAIL
  RD_IMAGE    docker image (default rd-linux-verify:24.04)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'dc2314a372^')
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
REL = 'win-linux/src/cascapplicationmanagerwrapper.cpp'

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()

needle = 'case ASC_MENU_EVENT_TYPE_CEF_ONKEYBOARDDOWN: {'
at = src.find(needle)
if at == -1:
    raise SystemExit('the ONKEYBOARDDOWN case is gone')
depth = 0
for i in range(src.index('{', at), len(src)):
    if src[i] == '{':
        depth += 1
    elif src[i] == '}':
        depth -= 1
        if depth == 0:
            block = src[at:i + 1]
            break
if 'get_KeyCode' not in block or 'VK_F4' not in block:
    raise SystemExit('extracted the wrong block')

harness = r'''
#include <cstdio>
#include <string>
#define VK_F4 0x73
enum { ASC_MENU_EVENT_TYPE_CEF_ONKEYBOARDDOWN = 7 };

static int g_quits = 0, g_openFolder = 0, g_editorClose = 0, g_mainClose = 0;
static bool g_queueBusy = false, g_aboutToClose = false;

struct CAscKeyboardDown {
    int code; bool ctrl, alt, shift;
    int get_KeyCode() { return code; }
    bool get_IsCtrl() { return ctrl; }
    bool get_IsAlt() { return alt; }
    bool get_IsShift() { return shift; }
};
struct CAscCefMenuEvent { int m_nType; void * m_pData; int get_SenderId() { return 1; } };
struct CEditorWindow { int closeWindow() { ++g_editorClose; return 0; } };
struct CMainWindow {
    bool isAboutToClose() const { return g_aboutToClose; }
    bool holdView(int) const { return true; }
    void close() { ++g_mainClose; }
};
struct CloseQueue { bool empty() { return !g_queueBusy; } };
struct Private {
    void sendOpenFolderEvent(int) { ++g_openFolder; }
    bool sendCreateNewEvent(int) { return false; }      /* #200's Ctrl+N case shares the switch */
    bool toggleWindowFullScreen(int) { return false; }  /* #858's F11 case shares the switch */
};
struct QTimer { template <class O, class F> static void singleShot(int, O *, F) {} };   /* #1847's Ctrl+Shift+T */
struct AscAppManager { static void closeAppWindows() { ++g_quits; g_queueBusy = true; } };

struct Wrapper {
    Private priv; Private * m_private = &priv; CloseQueue queue;
    CEditorWindow * editorWindowFromViewId(int) { return nullptr; }
    static CMainWindow * mainWindow() { static CMainWindow w; return &w; }
    CloseQueue & closeQueue() { return queue; }
    static void reopenClosedDocument() {}

    bool processCommonEvent(CAscCefMenuEvent * event) {
        switch ( event->m_nType ) {
        %(block)s
        default: break;
        }
        return false;
    }
};

static int failures = 0;
static void key(const char * what, int code, bool ctrl, bool alt, bool shift, bool wantConsumed, int wantQuits) {
    Wrapper w;
    CAscKeyboardDown d{code, ctrl, alt, shift};
    CAscCefMenuEvent e{ASC_MENU_EVENT_TYPE_CEF_ONKEYBOARDDOWN, &d};
    int before = g_quits;
    bool consumed = w.processCommonEvent(&e);
    int quits = g_quits - before;
    bool ok = consumed == wantConsumed && quits == wantQuits;
    failures += !ok;
    printf("  %%-40s consumed=%%d quits=%%d  %%s\n", what, consumed, quits, ok ? "ok" : "FAILED");
}

int main() {
    key("Ctrl+Q", 0x51, true, false, false, true, 1);
    key("Ctrl+Q again while closing (queue busy)", 0x51, true, false, false, true, 0);
    g_queueBusy = false; g_aboutToClose = true;
    key("Ctrl+Q while main window closes", 0x51, true, false, false, true, 0);
    g_aboutToClose = false;
    key("Ctrl+Shift+Q", 0x51, true, false, true, false, 0);
    key("Ctrl+Alt+Q", 0x51, true, true, false, false, 0);
    key("Alt+Q (editors: chat panel)", 0x51, false, true, false, false, 0);
    key("Q", 0x51, false, false, false, false, 0);
    int of = g_openFolder;
    key("Ctrl+O", 0x4f, true, false, false, true, 0);
    if (g_openFolder != of + 1) { ++failures; printf("  Ctrl+O no longer opens the folder  FAILED\n"); }
    int mc = g_mainClose;
    key("Alt+F4", VK_F4, false, true, false, true, 0);
    if (g_mainClose != mc + 1) { ++failures; printf("  Alt+F4 no longer closes the window  FAILED\n"); }
    printf("\n%%s\n", failures ? "FAILED" : "ok - Ctrl+Q quits the app on Linux");
    return failures ? 1 : 0;
}
''' % dict(block=block)

print('extracted the ONKEYBOARDDOWN case from %s%s' % (REPO, ' @ ' + BASE_REF if os.environ.get('BASELINE') else ''))
sys.stdout.flush()
with tempfile.TemporaryDirectory() as tmp:
    open(os.path.join(tmp, 'harness.cpp'), 'w').write(harness)
    r = subprocess.run(['docker', 'run', '--rm', '-v', tmp + ':/w', IMAGE, 'sh', '-c',
                        'g++ -std=c++14 -w -o /tmp/h /w/harness.cpp && /tmp/h'],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode and 'FAILED' not in r.stdout:
        sys.stderr.write(r.stderr[-3000:])
    sys.exit(r.returncode)
