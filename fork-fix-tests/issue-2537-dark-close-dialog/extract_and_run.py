#!/usr/bin/env python3
"""
#2537 - Windows, theme "Same as system" with Windows in dark mode: the "More than
one document is open. Close the window anyway?" confirmation is unreadable - dark
blue text (~RGB 0,34,102) on a near-black background (~RGB 25,25,25), ~1.2:1.

Cause.  CMainWindow asks through CMessage::showMessage
(desktop-apps/win-linux/src/components/cmessage.cpp), which on Windows always
went to WinMsg::showMessage - a native TaskDialogIndirect.  The task dialog has
no dark style: when the process is allowed dark mode (CEF does that while the
OS is dark) Windows 11 paints its background dark but keeps the light-theme
main-instruction colour, which is the dark blue the reporter measured, and the
footer/verification area comes out mixed.  Nothing in our code styles it; the
Qt dialog next to it (QtMsg) is the one that follows the app theme through
message.qss.

Fix.  CMessage::showMessage now uses the native dialog only when neither the
system colour scheme nor the app theme is dark (isNativeMsgDark()); otherwise
it falls through to QtMsg.

What this runs: the REAL CMessage::showMessage and isNativeMsgDark, extracted by
brace matching and compiled with _WIN32 defined, against stubs that record
which dialog implementation was chosen.  AscAppManager::themes() is a stub whose
system-dark flag and app-theme darkness the scenarios set; WinMsg/QtMsg are
recorders.  Baseline (BASELINE=1, sources from BASE_REF): the scenarios with a
dark side MUST FAIL - they reach the native task dialog.

NOT claimed: no Windows build or screenshot; that Windows paints the task dialog
dark is taken from the report (colours sampled there), not reproduced here; the
QtMsg dark styling itself (message.qss, theme-dark / theme-contrast-dark) is
existing code and is not exercised; Linux (GTK) is untouched.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', 'c946559b75^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC_PATH = 'win-linux/src/components/cmessage.cpp'


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


src = read(SRC_PATH)
at = src.find('int CMessage::showMessage(QWidget *parent,')
if at < 0:
    raise SystemExit('CMessage::showMessage not found - the extractor needs updating')
show = brace_match(src, at)
if 'WinMsg::showMessage' not in show or 'QtMsg::showMessage' not in show:
    raise SystemExit('CMessage::showMessage no longer dispatches to WinMsg/QtMsg - revisit this test')

at = src.find('static bool isNativeMsgDark()')
helper = brace_match(src, at) if at >= 0 else '/* not present in this revision */'

PROGRAM = r'''
#include <cstdio>
#include <string>

/* ---- minimal stand-ins for the types the dispatcher passes along -------- */
struct QWidget {};
typedef std::string QString;
enum class MsgType { MSG_INFO, MSG_WARN, MSG_CONFIRM, MSG_ERROR, MSG_BRAND };
enum class MsgBtns { mbOk, mbYesNo, mbYesDefNo };
struct CMessageOpts {};

static bool g_systemDark = false, g_themeDark = false;
static const char *g_used = "none";

struct CTheme  { bool isDark() const { return g_themeDark; } };
struct CThemes {
    CTheme t;
    const CTheme &current() { return t; }
    auto isSystemSchemeDark() -> const bool { return g_systemDark; }
};
namespace AscAppManager { static CThemes &themes() { static CThemes s; return s; } }
namespace WindowHelper  { static bool useNativeDialog() { return true; } }
namespace WinMsg { static int showMessage(QWidget *, const QString &, MsgType, MsgBtns, const CMessageOpts &)
                   { g_used = "native task dialog"; return 0; } }
namespace QtMsg  { static int showMessage(QWidget *, const QString &, MsgType, MsgBtns, const CMessageOpts &)
                   { g_used = "themed Qt dialog"; return 0; } }
struct CMessage { static int showMessage(QWidget *, const QString &, MsgType, MsgBtns, const CMessageOpts &); };

%(helper)s

%(show)s

static int failures = 0;
static void run(bool sys_dark, bool theme_dark, bool want_native, const char *what)
{
    g_systemDark = sys_dark; g_themeDark = theme_dark; g_used = "none";
    QWidget w;
    CMessage::showMessage(&w, "More than one document is open.<br>Close the window anyway?",
                          MsgType::MSG_WARN, MsgBtns::mbYesNo, CMessageOpts());
    bool native = std::string(g_used) == "native task dialog";
    bool ok = native == want_native;
    printf("  %%-48s -> %%-20s %%s\n", what, g_used, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main()
{
    run(true,  true,  false, "Windows dark, theme Same as system (report)");
    run(true,  false, false, "Windows dark, app theme light");
    run(false, true,  false, "Windows light, app theme dark");
    run(false, false, true,  "Windows light, app theme light");
    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

prog = PROGRAM % {'helper': helper, 'show': show}
out = tempfile.mkdtemp(prefix='rd2537_')
cpp = os.path.join(out, 'main.cpp')
with open(cpp, 'w', encoding='utf-8') as f:
    f.write(prog)
binp = os.path.join(out, 'run')
cc = subprocess.run(['c++', '-std=c++14', '-D_WIN32', '-o', binp, cpp], capture_output=True, text=True)
if cc.returncode != 0:
    sys.stderr.write(cc.stdout + cc.stderr)
    sys.stderr.write('\ncompilation of the extracted source failed: %s\n' % cpp)
    raise SystemExit(2)
print('revision under test: %s' % ('BASELINE ' + BASE_REF if BASELINE else REPO), flush=True)
r = subprocess.run([binp])
print('\n(extracted source: %s)' % cpp)
raise SystemExit(r.returncode)
