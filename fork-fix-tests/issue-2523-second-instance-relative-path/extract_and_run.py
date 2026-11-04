#!/usr/bin/env python3
"""
#2523 - with the editors already running, "onlyoffice-desktopeditors ../doc.docx"
typed in another directory opens the wrong file, or a new blank document.

Cause.  A second instance does not open anything itself: in main.cpp
(`if ( !app.isPrimary() )`) it joins its plain arguments with \\x01 and sends them
to the running instance, which parses them in handleInputCmd
(win-linux/src/cascapplicationmanagerwrapper.cpp).  On Linux that resolves a
relative path with QDir::current() - the working directory of the PRIMARY
process, not of the shell the user typed in.  On Windows handleInputCmd does
not resolve it at all and _waccess() is relative to the primary's directory as
well.  The sender forwarded the path exactly as typed, so the one process that
knew the right directory threw it away.

Fix.  main.cpp: forwardablePath() makes a relative local path absolute in the
sending process before it is forwarded; URLs and deep links (anything with a
scheme of two or more letters that is not an existing file here) pass
unchanged, a Windows drive letter is not mistaken for a scheme, and flags
("--new:...", "--key=value") keep going through the existing filter untouched.

What this runs: the REAL forwarding loop from main.cpp and the REAL
forwardablePath, extracted by brace matching and compiled against the real
QtCore (Homebrew qt@5), in a process whose working directory is a temp dir
(the "caller" directory).  The payload that would go to sendMessage() is
decoded and checked.  Baseline (BASELINE=1, sources from BASE_REF): the
relative-path cases MUST FAIL - they are forwarded relative.

NOT claimed: no Linux or Windows build, no real second instance or socket; the
primary's parsing of an absolute path is existing code and is not exercised
here; the Windows native-separator form is reasoned (primary calls
replaceBackslash on it), not run.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '831fd6f334^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC_PATH = 'win-linux/src/main.cpp'
QT = os.environ.get('QT_DIR', '/opt/homebrew/opt/qt@5')


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
at = src.find('static QString forwardablePath(const QString& arg)')
helper = brace_match(src, at) if at >= 0 else '/* forwardablePath: not present in this revision */'

at = src.find('    if ( !app.isPrimary() ) {')
if at < 0:
    raise SystemExit('the !app.isPrimary() branch was not found in main.cpp - the extractor needs updating')
branch = brace_match(src, at)
a = branch.find('        QString _out_args;')
b = branch.find('        bool res = app.sendMessage(_out_args.toUtf8());')
if a < 0 or b < 0:
    raise SystemExit('forwarding loop not recognised - the extractor needs updating')
loop = branch[a:b]

PROGRAM = r'''
#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QString>
#include <QStringList>
#include <cstdio>
#include <string>
#include <vector>

/* the parsed command line, as InputArgs keeps it */
namespace InputArgs {
    static std::vector<std::wstring> g_args;
    static const std::vector<std::wstring>& arguments() { return g_args; }
}

%(helper)s

static QStringList forwarded(const std::vector<std::wstring>& argv)
{
    InputArgs::g_args = argv;
%(loop)s
    QStringList out = QString::fromUtf8(_out_args.toUtf8()).split("\x01");
    out.removeAll(QString());
    return out;
}

static int failures = 0;
static void check(const std::vector<std::wstring>& argv, const QStringList& want, const char *what)
{
    QStringList got = forwarded(argv);
    bool ok = got == want;
    printf("  %%-52s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) {
        printf("      sent: %%s\n      want: %%s\n", qPrintable(got.join(" | ")), qPrintable(want.join(" | ")));
        failures++;
    }
}

int main()
{
    const QString cwd = QDir::currentPath();               /* the caller's directory */
    const QString up  = QDir::cleanPath(cwd + "/..");
    check({L"../doc.docx"}, {up + "/doc.docx"}, "../doc.docx -> absolute in the CALLER's dir (report)");
    check({L"doc.docx"}, {cwd + "/doc.docx"}, "doc.docx -> absolute");
    check({L"./sub/../doc.docx"}, {cwd + "/doc.docx"}, "./sub/../doc.docx -> cleaned absolute");
    check({L"/srv/a.xlsx"}, {"/srv/a.xlsx"}, "absolute path unchanged");
    check({L"https://example.com/a.docx"}, {"https://example.com/a.docx"}, "https URL unchanged");
    check({L"file:///home/u/a.docx"}, {"file:///home/u/a.docx"}, "file:// URL unchanged");
    check({L"oo-office://open|f.docx"}, {"oo-office://open|f.docx"}, "app deep link unchanged");
    check({L"--new:word", L"--force-use-window", L"--view=../a.docx", L"rel.pptx"},
          {"--new:word", cwd + "/rel.pptx"}, "flags filtered as before, path resolved");
    check({L"note:1.docx"}, {cwd + "/note:1.docx"}, "existing file named like a scheme -> path");
    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

prog = PROGRAM % {'helper': helper, 'loop': loop}
out = tempfile.mkdtemp(prefix='rd2523_')
cpp = os.path.join(out, 'main.cpp')
with open(cpp, 'w', encoding='utf-8') as f:
    f.write(prog)
binp = os.path.join(out, 'run')
fw = os.path.join(QT, 'lib')
cc = subprocess.run(['c++', '-std=c++17', '-F' + fw, '-I' + os.path.join(fw, 'QtCore.framework', 'Headers'),
                     '-o', binp, cpp, '-framework', 'QtCore', '-Wl,-rpath,' + fw],
                    capture_output=True, text=True)
if cc.returncode != 0:
    sys.stderr.write(cc.stdout + cc.stderr)
    sys.stderr.write('\ncompilation of the extracted source failed: %s\n' % cpp)
    raise SystemExit(2)

caller = os.path.join(out, 'caller')        # where the user typed the command
os.makedirs(caller)
open(os.path.join(caller, 'note:1.docx'), 'w').close()
print('revision under test: %s' % ('BASELINE ' + BASE_REF if BASELINE else REPO), flush=True)
r = subprocess.run([binp], cwd=caller)
print('\n(extracted source: %s)' % cpp)
raise SystemExit(r.returncode)
