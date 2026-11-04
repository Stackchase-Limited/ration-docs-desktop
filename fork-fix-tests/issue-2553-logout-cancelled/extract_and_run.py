#!/usr/bin/env python3
"""
#2553 - "Flatpak on KDE Plasma: logging out is always cancelled by DesktopEditors",
including the case with no unsaved document at all.

Cause.  When the session ends, Qt 5 emits commitDataRequest and then, because
"fallback session management" is on by default, asks every top-level window to
close; if any window ignores its QCloseEvent it calls QSessionManager::cancel()
(QGuiApplicationPrivate::commitData -> tryCloseAllWindows).  Our windows ALWAYS
ignore the event: CMainWindow::closeEvent / CEditorWindow::closeEvent hand the
window to the asynchronous close queue and call e->ignore().  So on any desktop
that drives Qt's own session manager (KDE Plasma over XSMP) the logout was vetoed
unconditionally, and the close queue then went on to close the app anyway - which
is exactly the reporter's four cases (saved, unsaved+Save, unsaved+Don't save,
unsaved+Cancel: the app closes, the logout is cancelled every time).
desktop-apps/win-linux/src/platform_linux/singleapplication.cpp only handled the
GNOME D-Bus protocol; nothing touched Qt's own path.

Fix.  setupSessionManagement() in that file turns the fallback off and answers
commitDataRequest itself: veto only when AscAppManager::hasUnsavedChanges(),
otherwise let the session end.

Follow-up (user's decision).  A silent veto left the user wondering why the logout
did not happen.  Now, when the logout is vetoed, the handler also starts the app's
normal quit close - AscAppManager::closeAppWindows(), the close queue that asks
"save changes?" per document - deferred with QTimer::singleShot so the session
manager callback returns first, after raising the main window.  It starts at most
once per logout attempt: a repeated commitDataRequest while that close is still
scheduled or running (close queue not empty, or the main window isAboutToClose())
only vetoes again.  Saving/discarding everything then quits as on any quit.

What this runs.  The REAL Qt 5 (Homebrew qt@5, offscreen platform plugin):
a QApplication, a shown top-level widget whose closeEvent is the real
CMainWindow::closeEvent body extracted from cmainwindow.cpp, the real
setupSessionManagement() extracted from singleapplication.cpp, and Qt's real
QGuiApplicationPrivate::commitData() - the very function Qt's XSMP backend calls
on "save yourself".  Only the platform session manager underneath QSessionManager
is replaced by a recorder (allowsInteraction() = true, as KDE grants it; cancel()
recorded), because there is no XSMP server on this host.  AscAppManager is a stub:
closeQueue() records enter()/cancel() and answers empty(), hasUnsavedChanges() is
set by the scenario, closeAppWindows() is counted and enters the main window into
the queue as the real one does, and bringToTop()/isAboutToClose() on the window
are recorded/set by the scenario.

Baseline (BASELINE=1, sources from BASE_REF via git show): setupSessionManagement
does not exist, so nothing is installed - which is precisely what a KDE session
got (the GNOME branch is not taken there).  Scenario A must then FAIL: the logout
is cancelled with nothing to save, and the close queue is entered.
Against the parent of the follow-up commit (the default BASE_REF; the integrator
re-pins it after cherry-picking) A passes but B/C must FAIL: the logout is vetoed
silently - no close is started, no window raised, no dialog would appear.

NOT claimed: no KDE/XSMP session was driven; the save dialogs themselves are not
shown (closeAppWindows and the close queue are stubs - that the queue prompts for
modified documents is the app's existing quit path, not re-tested here); window
raising is only checked as a bringToTop() call, not on a real window manager; the "die" phase after a successful
commit (Qt sends a Quit event, the close queue closes the windows) is not run;
Qt 6 builds (no fallback there) are not exercised; GNOME's D-Bus path is unchanged.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', 'bb8dcab024^')
BASELINE = bool(os.environ.get('BASELINE'))
QT = os.environ.get('QT5_DIR', '/opt/homebrew/opt/qt@5')

SINGLEAPP = 'win-linux/src/platform_linux/singleapplication.cpp'
MAINWIN = 'win-linux/src/windows/cmainwindow.cpp'


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces from offset %d' % start)


sa = read(SINGLEAPP)
mw = read(MAINWIN)

anchor = 'void CMainWindow::closeEvent(QCloseEvent * e)'
at = mw.find(anchor)
if at < 0:
    raise SystemExit('CMainWindow::closeEvent not found - the extractor needs updating')
close_event = brace_match(mw, at).replace('void CMainWindow::closeEvent', 'void closeEvent', 1)
if 'e->ignore()' not in close_event:
    raise SystemExit('CMainWindow::closeEvent no longer ignores the event - revisit this test')

at = sa.find('static void setupSessionManagement(QApplication *app)')
if at >= 0:
    setup = brace_match(sa, at)
    call = 'setupSessionManagement(&app);'
    if 'setupSessionManagement(this);' not in sa:
        raise SystemExit('setupSessionManagement is defined but the constructor no longer calls it')
else:
    setup = '/* not present in this revision: a KDE session got Qt defaults */'
    call = ''

PROGRAM = r'''
#include <QApplication>
#include <QWidget>
#include <QCloseEvent>
#include <QSessionManager>
#include <QTimer>
#include <QtCore/private/qobject_p.h>
#include <QtGui/private/qguiapplication_p.h>
#include <QtGui/private/qsessionmanager_p.h>
#include <qpa/qplatformsessionmanager.h>
#include <cstdio>
#include <cstddef>

/* ---- stubs for the app manager the extracted code talks to ------------- */
#define CLOSE_QUEUE_WIN_TYPE_MAIN 1
struct sWinTag { int type; size_t ptr; };
static int  g_queueEntered = 0;
static int  g_queued = 0;            /* windows waiting in the close queue */
static int  g_closeAppWindows = 0;
static int  g_raised = 0;
static bool g_unsaved = false;
static bool g_aboutToClose = false;
struct CloseQueue {
    void enter(const sWinTag &) { ++g_queueEntered; ++g_queued; }
    void cancel() { g_queued = 0; }
    bool empty() { return g_queued == 0; }
};
struct AppManagerStub {
    CloseQueue q;
    CloseQueue &closeQueue() { return q; }
};
class CMainWindow;
namespace AscAppManager {
    static AppManagerStub &getInstance() { static AppManagerStub s; return s; }
    static bool hasUnsavedChanges() { return g_unsaved; }
    static CMainWindow *mainWindow();
    static void closeAppWindows();
}

/* ---- a top-level window with the real CMainWindow::closeEvent ---------- */
class CMainWindow : public QWidget {
public:
    bool isAboutToClose() const { return g_aboutToClose; }
    void bringToTop() { ++g_raised; }
protected:
%(close_event)s
};

static CMainWindow *g_main = nullptr;
namespace AscAppManager {
    static CMainWindow *mainWindow() { return g_main; }
    /* as the real one: the visible main window goes into the close queue */
    static void closeAppWindows() {
        ++g_closeAppWindows;
        if (g_main && g_main->isVisible())
            getInstance().closeQueue().enter(sWinTag{CLOSE_QUEUE_WIN_TYPE_MAIN, size_t(g_main)});
    }
}

/* ---- the real fix (or nothing, on baseline) ---------------------------- */
%(setup)s

/* ---- recorder in place of the XSMP backend ----------------------------- */
class Recorder : public QPlatformSessionManager {
public:
    Recorder() : QPlatformSessionManager(QString(), QString()) {}
    bool allowsInteraction() override { return true; }
    void cancel() override { cancelled = true; }
    bool cancelled = false;
};

static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-62s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static bool endSession(QGuiApplication &app, Recorder &rec)
{
    QGuiApplicationPrivate *gp = static_cast<QGuiApplicationPrivate *>(QObjectPrivate::get(&app));
    QSessionManagerPrivate *sp = static_cast<QSessionManagerPrivate *>(QObjectPrivate::get(gp->session_manager));
    QPlatformSessionManager *old = sp->platformSessionManager;
    sp->platformSessionManager = &rec;
    rec.cancelled = false;
    gp->commitData();
    sp->platformSessionManager = old;
    return rec.cancelled;
}

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    %(call)s
    CMainWindow w;
    w.show();
    g_main = &w;
    Recorder rec;

    printf("fallback session management: %%s\n",
           QGuiApplication::isFallbackSessionManagementEnabled() ? "ON (Qt default)" : "off");

    printf("\nA - logout with NO unsaved document (reporter's case 4)\n");
    g_unsaved = false; g_queueEntered = 0;
    bool cancelledA = endSession(app, rec);
    printf("    logout cancelled: %%s, close queue entered: %%d\n", cancelledA ? "yes" : "no", g_queueEntered);
    check(!cancelledA, "the logout is NOT vetoed");

    printf("\nB - logout with an unsaved document\n");
    g_unsaved = true; g_queueEntered = 0; g_queued = 0; g_closeAppWindows = 0; g_raised = 0;
    bool cancelledB = endSession(app, rec);
    printf("    logout cancelled: %%s, close queue entered during the callback: %%d\n",
           cancelledB ? "yes" : "no", g_queueEntered);
    check(cancelledB, "the logout IS vetoed (no data loss)");
    check(g_queueEntered == 0 && g_closeAppWindows == 0, "nothing is closed inside the session-manager callback");
    QCoreApplication::processEvents();
    printf("    after the callback: closeAppWindows() %%d time(s), main window raised %%d time(s)\n",
           g_closeAppWindows, g_raised);
    check(g_closeAppWindows == 1, "then the normal quit close (save dialogs) is started");
    check(g_raised >= 1, "and the main window is raised so the dialog is seen");
    check(g_queueEntered == 1, "the main window is in the close queue (it will prompt)");

    printf("\nC - the session manager asks again during the same logout\n");
    g_closeAppWindows = 0; g_raised = 0;
    bool cancelledC1 = endSession(app, rec);     /* queue still busy: dialog is up */
    QCoreApplication::processEvents();
    g_queued = 0; g_aboutToClose = true;         /* queue moved on to CMainWindow::close() */
    bool cancelledC2 = endSession(app, rec);
    QCoreApplication::processEvents();
    printf("    logout cancelled: %%s/%%s, closeAppWindows() again: %%d time(s)\n",
           cancelledC1 ? "yes" : "no", cancelledC2 ? "yes" : "no", g_closeAppWindows);
    check(cancelledC1 && cancelledC2, "the repeated requests are vetoed too");
    check(g_closeAppWindows == 0, "but no second close / second dialog is started");

    printf("\nD - two requests before the deferred close has run, then a new logout\n");
    g_aboutToClose = false; g_queued = 0; g_closeAppWindows = 0;   /* user pressed Cancel */
    endSession(app, rec);
    endSession(app, rec);
    QCoreApplication::processEvents();
    printf("    closeAppWindows(): %%d time(s)\n", g_closeAppWindows);
    check(g_closeAppWindows == 1, "one close for back-to-back requests, and a new logout prompts again");

    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

src = PROGRAM % {'close_event': close_event, 'setup': setup, 'call': call}
out = tempfile.mkdtemp(prefix='rd2553_')
cpp = os.path.join(out, 'main.cpp')
with open(cpp, 'w', encoding='utf-8') as f:
    f.write(src)

ver = os.path.basename(os.path.realpath(QT))
lib = os.path.join(QT, 'lib')
inc = []
for fw in ('QtCore', 'QtGui', 'QtWidgets'):
    h = os.path.join(lib, fw + '.framework', 'Headers')
    inc += ['-I' + h, '-I' + os.path.join(h, ver), '-I' + os.path.join(h, ver, fw)]
inc.append('-I' + os.path.join(QT, 'mkspecs', 'macx-clang'))   # qplatformdefs.h
binp = os.path.join(out, 'run')
cc = subprocess.run(['c++', '-std=c++17', '-fPIC', '-F' + lib] + inc +
                    ['-o', binp, cpp, '-framework', 'QtCore', '-framework', 'QtGui',
                     '-framework', 'QtWidgets', '-Wl,-rpath,' + lib],
                    capture_output=True, text=True)
if cc.returncode != 0:
    sys.stderr.write(cc.stdout + cc.stderr)
    sys.stderr.write('\ncompilation of the extracted source failed: %s\n' % cpp)
    raise SystemExit(2)

env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
           QT_QPA_PLATFORM_PLUGIN_PATH=os.path.join(QT, 'plugins', 'platforms'))
print('revision under test: %s' % ('BASELINE ' + BASE_REF if BASELINE else REPO), flush=True)
r = subprocess.run([binp], env=env)
print('\n(extracted source: %s)' % cpp)
raise SystemExit(r.returncode)
