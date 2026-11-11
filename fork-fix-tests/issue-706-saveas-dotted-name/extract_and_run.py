#!/usr/bin/env python3
"""
#706 - Save As offered foo(05.09.21).docx as foo(05.09.docx.

What was wrong, in win-linux/src/components/cfiledialog.cpp (modalSaveAs):

  1. The dialog was handed the name without its extension, "foo(05.09.21)". A dialog
     that keeps the name's extension in step with the selected filter - Qt's own,
     and KDE's through xdg-desktop-portal (the default on a Plasma Wayland session
     since #2168) - takes whatever follows the LAST dot as the extension and
     replaces it: foo(05.09.docx; report.v2 became report.docx.
  2. The crop searched the whole path for the last dot, so a name with no extension
     in a dotted folder (/home/u/v1.2/README) cropped the path to /home/u/v1.
  3. After the dialog, a typed extension of another offered format was rewritten
     without a word (talk.pdf with PPTX chosen -> talk.pptx), and a.docx.pdf with
     DOCX chosen became a.docx.docx.

How this test works: the real modalSaveAs code is lifted from the source and built
against real QtCore/QtWidgets (Homebrew qt@5):
  - the setup from `QString _filters, _sel_filter, _ext;` up to `auto _exec_dialog`
    computes the names; which variable is handed to Xdg::openXdgPortal is read from
    the lambda's own source, so the baseline hands the portal what it really did;
  - that name is then put into a real non-native QFileDialog (offscreen), which is
    the same "replace the text after the last dot" logic KDE's dialog uses, and the
    text the user would see in the name box is checked;
  - the save loop's naming block, from `if ( !fileName.isEmpty() ) {` to
    `if ( info.exists() ) {`, runs with CMessage::showMessage stubbed to record the
    question and give a scripted answer.

What is NOT claimed: KDE's KFileWidget is not run (it is not available here); its
updateLocationEditExtension truncates at the last dot the same way, by reading of
its source. No real GTK/portal/Windows dialog is run. Names with CJK, emoji and
combining marks are checked to pass through unchanged, not displayed.

  ./extract_and_run.py              -> passes
  BASELINE=1 ./extract_and_run.py   -> fails
RD_REPO=<desktop-apps checkout>, BASE_REF=<ref> (default: the fix commit's parent).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps'))
REL = 'win-linux/src/components/cfiledialog.cpp'
BASE_REF = os.environ.get('BASE_REF', 'a877e2fc4^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()


def die(msg):
    sys.stderr.write(msg + '\n')
    sys.exit(2)


fn = source.find('bool CFileDialogWrapper::modalSaveAs(')
if fn == -1:
    die('modalSaveAs not found')

# 1. the name set-up, up to the dialog lambda
s1 = source.find('QString _filters, _sel_filter, _ext;', fn)
e1 = source.find('auto _exec_dialog', s1)
if s1 == -1 or e1 == -1:
    die('modalSaveAs set-up not found')
setup = source[s1:e1].rstrip()

# which name the portal is given, read from the lambda's own call
lam_end = source.find('fileName = _exec_dialog(', e1)
m = re.search(r'Xdg::openXdgPortal\(\s*p\s*,\s*Xdg::Mode::SAVE\s*,\s*title\s*,\s*(\w+)\s*,',
              source[e1:lam_end])
if not m:
    die('openXdgPortal call not found in the dialog lambda')
portal_arg = m.group(1)
portal_name = {'n': '_croped_name'}.get(portal_arg, portal_arg)

# 2. the naming decision after the dialog returns
s2 = source.find('if ( !fileName.isEmpty() ) {', source.find('fileName = _exec_dialog(', fn))
e2 = source.find('if ( info.exists() ) {', s2)
if s2 == -1 or e2 == -1:
    die('save-name block not found')
block = source[source.index('\n', s2) + 1:e2].rstrip()

# 3. getFilter, real, as a free function
g = source.find('QString CFileDialogWrapper::getFilter(const QString& extension) const')
gb = source.index('{', g)
depth, i = 0, gb
while True:
    if source[i] == '{':
        depth += 1
    elif source[i] == '}':
        depth -= 1
        if depth == 0:
            break
    i += 1
getfilter = 'static QString getFilter(const QString& extension)' + source[gb:i + 1]

harness = r'''
#include <QApplication>
#include <QFileDialog>
#include <QLineEdit>
#include <QString>
#include <QFileInfo>
#include <QRegularExpression>
#include <QMap>
#include <stdio.h>

#define AVS_OFFICESTUDIO_FILE_UNKNOWN 0x0000   /* core/Common/OfficeFileFormats.h */
static QString tr(const char *s) { return QString::fromUtf8(s); }
%(getfilter)s

static QMap<int,QString> m_mapFilters;
static QString m_filters;
static int getKey(const QString &sel) {
    for (auto it = m_mapFilters.cbegin(); it != m_mapFilters.cend(); ++it)
        if (it.value() == sel) return it.key();
    return 0;
}

/* --- the real set-up, minus the dialog --- */
struct Offer { QString cropped, portal; };
static Offer offer(QString fileName, int selected) {
%(setup)s
    return Offer{_croped_name, %(portal_name)s};
}

/* --- what a filter-following dialog shows for a name (Qt's, as KDE's) --- */
static QString shown(const QString &name, const QString &filters, const QString &sel) {
    QFileDialog d(nullptr, "Save As", "/tmp", filters);
    d.setOption(QFileDialog::DontUseNativeDialog);
    d.setAcceptMode(QFileDialog::AcceptSave);
    d.selectFile(QFileInfo(name).fileName());
    d.selectNameFilter(sel);
    return d.findChild<QLineEdit*>("fileNameEdit")->text();
}

/* --- the real naming decision after the dialog --- */
enum { MODAL_RESULT_CANCEL = 0, MODAL_RESULT_YES, MODAL_RESULT_NO };
enum class MsgType { MSG_WARN }; enum class MsgBtns { mbYesNo };
static int g_answer; static int g_asked; static QString g_question;
struct CMessage { static int showMessage(void *, const QString &q, MsgType, MsgBtns) {
    g_asked++; g_question = q; return g_answer; } };
struct Self { void *parent() { return nullptr; } } self;
#define parent() self.parent()

struct Result { QString name; bool back; int asked; };
static Result decide(QString fileName, const QString &_sel_filter, const QString &_named_offer, int answer) {
    const QString _filters = m_filters;
    QString _ext;
    QRegularExpression reFilter("\\(\\*(\\.\\w+)", QRegularExpression::CaseInsensitiveOption);
    QRegularExpressionMatch match;
    g_answer = answer; g_asked = 0;
    /* The block may `continue` (back to the dialog) or `break` (stop). The loop's
       increment runs on continue and on falling through, not on break. */
    int state = 0;      /* 3 fell through, 1 continue, 0 break */
    for (int once = 0; once < 1; state = (state ? state : 1), ++once) {
        if ( !fileName.isEmpty() ) {
%(block)s
        }
        state = 3;
    }
    return Result{fileName, state == 1, g_asked};
}
#undef parent

static int failures = 0;
static void expect(bool ok, const QString &what, const QString &got, const char *why) {
    printf("  %%-58s %%s\n", (what + " -> " + got).toUtf8().constData(), ok ? "ok" : "FAILED");
    if (!ok) { printf("      %%s\n", why); failures++; }
}

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    const QString DOCX = "DOCX Document (*.docx)", PDF = "PDF File (*.pdf)", PPTX = "PPTX File (*.pptx)";
    m_mapFilters.insert(AVS_OFFICESTUDIO_FILE_UNKNOWN, "All files (*.*)");
    m_mapFilters.insert(65, DOCX);
    m_mapFilters.insert(513, PDF);
    m_mapFilters.insert(129, PPTX);
    m_filters = DOCX + ";;" + PDF;

    printf("name offered to the portal, as a filter-following dialog shows it:\n");
    const char *names[] = { "foo(05.09.21).docx", "report.v2.docx", "a.docx.pdf.docx",
                            "中文报告.v2.docx", "notes \U0001F600.1.docx",
                            "été.final.docx", "Document1.docx" };
    for (const char *n : names) {
        const QString full = QString("/home/u/") + QString::fromUtf8(n);
        const Offer o = offer(full, 65);
        const QString box = shown(o.portal, m_filters, DOCX);
        const QString own = QFileInfo(full).fileName();
        expect(box == own || box + ".docx" == own, "offer " + own, box,
               "the dialog must show the document's own name, not one cut at an inner dot");
    }

    printf("cropping touches only the file name:\n");
    {
        const QString saved = m_filters; m_filters.clear();   // the download dialog has none
        const Offer o = offer("/home/u/v1.2/README", -1);
        m_filters = saved;
        expect(o.cropped == "/home/u/v1.2/README", "offer /home/u/v1.2/README", o.cropped,
               "a dot in a folder name must not crop the path");
    }

    printf("name decided after the dialog:\n");
    auto check = [](const char *typed, const QString &sel, const char *offered, int answer,
                    const char *want, bool wantBack, int wantAsked, const char *why) {
        Result r = decide(QString::fromUtf8(typed), sel, QString::fromUtf8(offered), answer);
        const bool ok = (r.back ? QString("<back to dialog>") : r.name) ==
                        (wantBack ? QString("<back to dialog>") : QString::fromUtf8(want))
                        && r.asked == wantAsked;
        QString got = (r.back ? QString("<back to dialog>") : r.name) + QString(" asked=%%1").arg(r.asked);
        expect(ok, QString::fromUtf8(typed) + " [" + sel.section(' ', 0, 0) + "]", got, why);
    };
    // typed a different format's extension: ask, and honour the answer
    check("/t/talk.pdf", DOCX, "/t/talk.docx", MODAL_RESULT_YES, "/t/talk.docx", false, 1,
          "a typed .pdf with DOCX chosen must be asked about, then saved as talk.docx");
    check("/t/talk.pdf", DOCX, "/t/talk.docx", MODAL_RESULT_NO, "", true, 1,
          "answering No must go back to the dialog, not save");
    check("/t/talk.pdf", DOCX, "/t/talk.docx", MODAL_RESULT_CANCEL, "", false, 1,
          "closing the question must cancel the save");
    // no doubled extension
    check("/t/a.docx.pdf", DOCX, "/t/x.docx", MODAL_RESULT_YES, "/t/a.docx", false, 1,
          "a.docx.pdf saved as DOCX must become a.docx, not a.docx.docx");
    // the offered name with only the format changed: corrected, no question (#2429)
    check("/t/talk.docx", PDF, "/t/talk.docx", MODAL_RESULT_CANCEL, "/t/talk.pdf", false, 0,
          "the offered name with the format switched is corrected without asking");
    // things that must pass straight through
    check("/t/report.v2", DOCX, "/t/x.docx", MODAL_RESULT_CANCEL, "/t/report.v2.docx", false, 0,
          "a dotted name that is not an extension is kept and extended");
    check("/t/foo(05.09.21)", DOCX, "/t/x.docx", MODAL_RESULT_CANCEL, "/t/foo(05.09.21).docx", false, 0,
          "the #706 name with no extension just gains .docx");
    check("/t/中文\U0001F600é.docx", DOCX, "/t/x.docx", MODAL_RESULT_CANCEL,
          "/t/中文\U0001F600é.docx", false, 0,
          "CJK, emoji and combining marks pass through untouched");
    check("/t/Talk.DOCX", DOCX, "/t/x.docx", MODAL_RESULT_CANCEL, "/t/Talk.DOCX", false, 0,
          "an upper-case extension of the chosen format is accepted as is");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - the dialog offers the real name and the saved name is the one the user chose or agreed to");
    return failures ? 1 : 0;
}
''' % {'block': block, 'setup': setup, 'portal_name': portal_name, 'getfilter': getfilter}

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w', encoding='utf-8').write(harness)
    Q = os.environ.get('QT5', '/opt/homebrew/opt/qt@5')
    inc = []
    for fw in ('QtWidgets', 'QtGui', 'QtCore'):
        inc += ['-I' + Q + '/lib/' + fw + '.framework/Headers', '-framework', fw]
    c = subprocess.run(['clang++', '-std=c++14', '-fPIC', '-w', '-o', exe, src,
                        '-F' + Q + '/lib', '-Wl,-rpath,' + Q + '/lib'] + inc,
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_LOGGING_RULES='*=false')
    r = subprocess.run([exe], env=env, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.exit(r.returncode)
