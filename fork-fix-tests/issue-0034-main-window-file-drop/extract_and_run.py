#!/usr/bin/env python3
"""
#34 - "Drag-and-drop (Windows)": dropping a .docx on the app window gave the "no"
cursor instead of opening it.

What already worked in 9.4 (read, not changed): a drop on the START PAGE opens
the file on every platform - CEF's own drop target (Windows OLE) collects the
names (cefview.cpp OnDragEnter -> set_drop_files), the start page's ondrop
(common/loginpage/src/panels.js) calls DropOfficeFiles, and desktop-sdk sends
ASC_MENU_EVENT_TYPE_CEF_LOCALFILES_OPEN for every office file. An editor takes
drops itself (images etc.).

What did not: the main window's own drop handling - the tab bar, title bar and
the strip around them, where a drop lands whenever a document tab is open - was
compiled for Linux only: setAcceptDrops(true) and CMainWindow::dragEnterEvent /
dropEvent sat inside #ifdef __linux__ (cmainwindow.cpp, cmainwindow.h). And the
code itself was not fit for Windows: QUrl::path() gives "/C:/Users/..." there,
and the suffix check was case-sensitive (REPORT.DOCX refused).

Fix (desktop-apps f7e1ac479): handlers and setAcceptDrops on every platform,
toLocalFile(), lower-cased suffix, macro/template/legacy/flat types added,
non-local URLs refused, last-open folder = the file's folder.

What this runs.
 1. The C preprocessor (g++ -E inside rd-linux-verify:24.04) over the REAL
    constructor block and class declaration with _WIN32 defined and __linux__
    undefined: setAcceptDrops(true) and the two handler declarations must survive.
 2. The REAL CMainWindow::dragEnterEvent and dropEvent, brace-matched from
    cmainwindow.cpp and compiled with Qt 5.15 against a stand-in CMainWindow
    (doOpenLocalFile / keepLastPath record their arguments), fed real
    QDragEnterEvent/QDropEvent objects with real QMimeData URLs, Qt offscreen:
      file:///home/me/Q3%20REPORT.DOCX      (capitals, as Windows names often are)
      file:///home/me/a%23b.docx            (# in the name - worked before too)
      file:///home/me/budget.xlsm
      https://example.com/a.docx            (not a local file -> refused)
BASELINE=1 (sources from BASE_REF, the fix's parent): the Windows build has no
drop handling, REPORT.DOCX and .xlsm are refused, a web link is opened as the
path "/a.docx" - FAILS.

NOT claimed.  The drive-letter conversion: Qt's QUrl::toLocalFile strips the
slash of "/C:/..." only when Qt is built for Windows (on Linux both path() and
toLocalFile() give "/C:/Users/..."), so it is Qt's documented behaviour, not run
here. No Windows build: the OLE drop on the real tab bar/title bar
(Caption is a native child HWND - OLE should fall through to the top-level's
Qt drop target) and Explorer drags need a Windows GUI check. Multi-file drops
on the tab bar still open nothing (one file per drop, as before; the start
page takes several). Dropping a document INTO an open editor is the editor's
business and is unchanged.

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  sources from BASE_REF via git show (default f7e1ac479^) -> FAIL
  RD_IMAGE    docker image (default rd-linux-verify:24.04)
"""
import io
import os
import re
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', 'f7e1ac479^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
CPP = 'win-linux/src/windows/cmainwindow.cpp'
HDR = 'win-linux/src/windows/cmainwindow.h'


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


def between(text, a, b):
    i = text.find(a)
    j = text.find(b, i)
    if i == -1 or j == -1:
        raise SystemExit('%r..%r not found - the extractor needs updating' % (a, b))
    return text[i:j]


cpp, hdr = read(CPP), read(HDR)
CTOR = between(cpp, 'QString css{AscAppManager::getWindowStylesheets(m_dpiRatio)};', 'm_pMainPanel->setStyleSheet(css);')
DECL = between(hdr, 'void aboutToClose();', '/** MainPanel **/')
ENTER = extract(cpp, 'void CMainWindow::dragEnterEvent(QDragEnterEvent *event)', ('acceptProposedAction',))
DROP = extract(cpp, 'void CMainWindow::dropEvent(QDropEvent *event)', ('doOpenLocalFile',))

MAIN_SRC = r'''
#include <QApplication>
#include <QMainWindow>
#include <QMimeData>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QFileInfo>
#include <QSet>
#include <QUrl>
#include <cstdio>
#include <string>

#define LOCAL_PATH_OPEN 1
enum AscEditorType { etLocalFile = 1 };
struct COpenOptions {
    COpenOptions(QString name, AscEditorType type, QString url) : name(name), type(type), url(url) {}
    QString name; AscEditorType type; QString url; std::wstring wurl;
};
struct Utils {
    static void keepLastPath(int, const QString &p) { printf("keepLastPath %s\n", qPrintable(p)); }
};
namespace NSEditorApi {
    struct CAscMenuEvent { int m_nType = 0; void *m_pData = nullptr; };
    struct CAscAddPlugin { void put_Path(const std::wstring &) {} };
}
#define ASC_MENU_EVENT_TYPE_DOCUMENTEDITORS_ADD_PLUGIN 1
struct AppMgr { void Apply(NSEditorApi::CAscMenuEvent *) { printf("plugin\n"); } };
struct AscAppManager { static AppMgr &getInstance() { static AppMgr m; return m; } };

class CMainWindow : public QMainWindow
{
public:
    void dragEnterEvent(QDragEnterEvent *event) override;
    void dropEvent(QDropEvent *event) override;
    void doOpenLocalFile(COpenOptions &opts) { printf("open url=%s\n", qPrintable(opts.url)); }
};

ENTER_SRC

DROP_SRC

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    CMainWindow w;
    const char *urls[] = {"file:///home/me/Q3%20REPORT.DOCX", "file:///home/me/a%23b.docx",
                          "file:///home/me/budget.xlsm", "https://example.com/a.docx"};
    for (const char *u : urls) {
        QMimeData md;
        md.setUrls({QUrl(QString::fromLatin1(u))});
        QDragEnterEvent de(QPoint(5, 5), Qt::CopyAction, &md, Qt::LeftButton, Qt::NoModifier);
        de.setAccepted(false);
        w.dragEnterEvent(&de);
        printf("case %s enter-accepted=%d\n", u, (int)de.isAccepted());
        if (de.isAccepted()) {
            QDropEvent dr(QPointF(5, 5), Qt::CopyAction, &md, Qt::LeftButton, Qt::NoModifier);
            w.dropEvent(&dr);
        }
        printf("end\n");
    }
    printf("done\n");
    return 0;
}
'''.replace('ENTER_SRC', ENTER).replace('DROP_SRC', DROP)

RUN_SH = r'''
cd /w
printf '#define _WIN32 1\n' > win.h
echo "--- ctor (_WIN32)"; g++ -E -P -U__linux__ -U__linux -Ulinux -include win.h -x c++ ctor.txt 2>/dev/null
echo "--- decl (_WIN32)"; g++ -E -P -U__linux__ -U__linux -Ulinux -include win.h -x c++ decl.txt 2>/dev/null
echo "--- run"
g++ -std=c++17 -fPIC main.cpp -o dd $(pkg-config --cflags --libs Qt5Widgets) >build.log 2>&1 || { cat build.log; exit 1; }
QT_QPA_PLATFORM=offscreen timeout 30 ./dd 2>/dev/null
exit 0
'''


def main():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, text in (('main.cpp', MAIN_SRC), ('run.sh', RUN_SH),
                           ('ctor.txt', CTOR), ('decl.txt', DECL)):
            data = text.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    out = subprocess.run(['docker', 'run', '--rm', '-i', IMAGE, 'sh', '-c',
                          'mkdir /w && cd /w && tar xf - && sh run.sh >/tmp/out 2>&1; cat /tmp/out'],
                         input=buf.getvalue(), capture_output=True)
    text = out.stdout.decode(errors='replace')
    if 'done' not in text or '--- run' not in text:
        sys.stderr.write(text + out.stderr.decode(errors='replace'))
        raise SystemExit('harness failed to build/run (not a verdict)')
    ctor = text.split('--- ctor (_WIN32)')[1].split('--- decl (_WIN32)')[0]
    decl = text.split('--- decl (_WIN32)')[1].split('--- run')[0]
    run = text.split('--- run')[1]
    cases = {}
    for m in re.finditer(r'case (\S+) enter-accepted=(\d)\n(.*?)end\n', run, re.S):
        cases[m.group(1)] = (m.group(2) == '1', m.group(3))
        print('  %s accepted=%s %s' % (m.group(1), m.group(2), ' | '.join(m.group(3).strip().splitlines())))

    fails = []

    def check(ok, what):
        print('  %s %s' % ('ok  ' if ok else 'FAIL', what))
        if not ok:
            fails.append(what)

    check('setAcceptDrops(true)' in ctor, 'Windows build: the main window accepts drops (setAcceptDrops)')
    check('dragEnterEvent' in decl and 'dropEvent' in decl, 'Windows build: dragEnterEvent/dropEvent are declared')
    win = cases.get('file:///home/me/Q3%20REPORT.DOCX', (False, ''))
    check(win[0] and 'open url=/home/me/Q3 REPORT.DOCX\n' in win[1]
          and 'keepLastPath /home/me\n' in win[1],
          'Q3 REPORT.DOCX (capitals) opens, its folder is remembered')
    hsh = cases.get('file:///home/me/a%23b.docx', (False, ''))
    check(hsh[0] and 'open url=/home/me/a#b.docx\n' in hsh[1], 'a#b.docx opens under its real name')
    xm = cases.get('file:///home/me/budget.xlsm', (False, ''))
    check(xm[0] and 'open url=/home/me/budget.xlsm\n' in xm[1], 'a macro-enabled workbook (.xlsm) is accepted')
    web = cases.get('https://example.com/a.docx', (True, 'x'))
    check(not web[0], 'a web link is not taken for a local file')

    label = 'BASELINE (%s)' % BASE_REF if BASELINE else 'fix'
    if fails:
        print('FAIL [%s]: %d check(s) failed' % (label, len(fails)))
        sys.exit(1)
    print('PASS [%s]: files dropped on the main window open, on Windows builds too' % label)


if __name__ == '__main__':
    main()
