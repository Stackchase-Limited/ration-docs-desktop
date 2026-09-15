#!/usr/bin/env python3
"""
#2429 - Save As PDF kept the .pptx name, and the write then replaced the original
presentation with a PDF. The user's file was destroyed.

BACK-FILLED. The fix was committed earlier citing a test directory of this name
that did not exist; see the verification status section of UPSTREAM_TRIAGE.md.

The save loop asked the selected filter for the extension:

    match = reFilter.match(_sel_filter);
    if ( match.hasMatch() ) { _ext = match.captured(1);
                              if (!fileName.endsWith(_ext)) fileName.append(_ext); }

reFilter is "\\(\\*(\\.\\w+)", so it only matches a filter that carries a pattern.
When the platform dialog hands back a filter WITHOUT one - just "PDF", say - nothing
matched, _ext stayed empty, and the name was left exactly as the user typed it:
test.pptx. The PDF was then written over the presentation.

The fix falls back to the filter held for that format, and chops a trailing
extension that the dialog itself offers so test.pptx becomes test.pdf rather than
test.pptx.pdf - while leaving a dotted name that is not an extension alone.

Extracted and linked against real QtCore, so QString, QFileInfo and
QRegularExpression are the real ones.

NOTE ON THE BASELINE: a back-filled test cannot baseline against HEAD, which already
has the fix. Default below is the commit before it landed.

  ./extract_and_run.py              -> passes
  BASELINE=1 ./extract_and_run.py   -> fails, at 32b676993^
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/components/cfiledialog.cpp'
BASE_REF = os.environ.get('BASE_REF', '32b676993^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()

# The naming decision, lifted verbatim: everything between the dialog returning a
# name and the "already exists" check.
start = source.find('if ( !fileName.isEmpty() ) {', source.find('fileName = _exec_dialog('))
end = source.find('QFileInfo info(fileName);', start)
if start == -1 or end == -1:
    sys.stderr.write('the save-name block was not found in %s\n' % REL)
    sys.exit(2)
block = source[source.index('\n', start) + 1:end].rstrip()

# The pattern the block matches with, also lifted rather than retyped.
pat = re.search(r'reFilter\.setPattern\("([^"]+)"\)', source)
if not pat:
    sys.stderr.write('reFilter pattern not found\n')
    sys.exit(2)
pattern = pat.group(1)

harness = r'''
#include <QString>
#include <QFileInfo>
#include <QRegularExpression>
#include <QMap>
#include <stdio.h>

/* The dialog's own filter table, as it is for a presentation Save As. */
static QString  g_filters;
static QMap<int,QString> m_mapFilters;
static QString  m_filters;
static int getKey(const QString &sel) {
    /* The real getKey maps a filter string to a format id; for the fallback all
       that matters is that a known filter resolves to an id we hold. */
    if (sel.contains("PDF", Qt::CaseInsensitive))  return 513;
    if (sel.contains("PPTX", Qt::CaseInsensitive)) return 129;
    return 0;
}

static QString decide(QString fileName, const QString &_sel_filter) {
    const QString _filters = g_filters;
    QString _ext;
    QRegularExpression reFilter("%(pattern)s", QRegularExpression::CaseInsensitiveOption);
    QRegularExpressionMatch match;
%(block)s
    return fileName;
}

static int failures = 0;
static void check(const char *name, const char *filter, const char *want, const char *why) {
    QString got = decide(QString(name), QString(filter));
    bool ok = (got == QString(want));
    printf("  %%-30s + %%-22s -> %%-22s %%s\n", name, filter,
           got.toUtf8().constData(), ok ? "ok" : "FAILED");
    if (!ok) { printf("      wanted %%s   (%%s)\n", want, why); failures++; }
}

int main(int, char **) {
    g_filters = "Presentation (*.pptx);;PDF (*.pdf);;ODP (*.odp)";
    m_filters = g_filters;
    m_mapFilters.insert(513, "PDF (*.pdf)");
    m_mapFilters.insert(129, "Presentation (*.pptx)");

    /* The destructive case: a platform dialog that returns a filter with no
       pattern in it. The name was left untouched and a PDF went over the pptx. */
    check("/tmp/talk.pptx", "PDF",            "/tmp/talk.pdf",
          "a filter with no (*.ext) must still name the file correctly");

    /* The ordinary case: the extension is replaced, not appended twice. */
    check("/tmp/talk.pptx", "PDF (*.pdf)",    "/tmp/talk.pdf",
          "saving a pptx as PDF must produce .pdf, not .pptx.pdf");

    /* A name already correct is left alone. */
    check("/tmp/talk.pdf",  "PDF (*.pdf)",    "/tmp/talk.pdf",
          "an already-correct name must not be changed");

    /* A dotted name whose suffix is not one of the dialog's formats keeps it. */
    check("/tmp/report.v2", "PDF (*.pdf)",    "/tmp/report.v2.pdf",
          "a dotted name that is not an extension must be kept");

    /* No extension at all. */
    check("/tmp/talk",      "PDF (*.pdf)",    "/tmp/talk.pdf",
          "a name with no extension gets one");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - the saved name always agrees with the format being written");
    return failures ? 1 : 0;
}
''' % {'block': block, 'pattern': pattern}

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    Q = '/opt/homebrew/opt/qt@5'
    c = subprocess.run(['clang++', '-std=c++14', '-fPIC', '-w', '-o', exe, src,
                        '-I' + Q + '/lib/QtCore.framework/Headers',
                        '-F' + Q + '/lib', '-framework', 'QtCore'],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
