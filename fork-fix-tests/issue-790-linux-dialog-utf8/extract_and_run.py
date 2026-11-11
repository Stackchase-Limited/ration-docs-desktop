#!/usr/bin/env python3
"""
#790 - Chinese file names at Save As on Linux.

The report (6.4.2, deepin 20.3) was that Chinese could not be typed into the Save As
name box. In 6.4 that box was Qt's own widget dialog from the bundled Qt, which has
no fcitx input-context plugin; 9.4 does not use that dialog on Linux (the GTK chooser,
or xdg-desktop-portal on Wayland), so that symptom is not tested here.

What IS still wrong in 9.4, and tested here: the Linux dialogs were handed the
document name, folder, title and filter names with QString::toLocal8Bit, while both
GTK and the portal take UTF-8, and the answers were read back with fromUtf8.
Under a locale that is not UTF-8 (zh_CN.GB18030, a Latin-1 locale):
  - xdg-desktop-portal: current_name is a D-Bus string. A GB18030 Chinese name, or
    Latin-1 "cafe\\xe9", is not UTF-8, and libdbus's check aborts the WHOLE app at
    Save As - every open document's unsaved work with it.
  - GTK chooser: the name reached GTK as bytes it cannot read (mojibake in the box,
    so a different name gets saved), a name Latin-1 cannot hold became "??", and a
    translated filter name came back garbled.

How: the real Xdg::openXdgPortal and Gtk::openGtkFileChooser are lifted by brace
matching, together with the real setCurrentName (which does the D-Bus append),
parseFilterString and Free. Only the parts that need a desktop are stubbed:
openDialog builds a real D-Bus message and calls the real setCurrentName into it,
exactly as callXdgPortal does, against real libdbus (Homebrew dbus); nativeFileDialog
checks with g_utf8_validate what GTK would get and hands it back the way GTK does
(its entry text and the chosen filter's own name). The locale's encoding is set with
QTextCodec::setCodecForLocale, which is what Qt derives from nl_langinfo(CODESET).

NOT claimed: no GTK widget, portal or session bus is run; the deepin IME symptom
is not reproduced (no deepin here). The abort itself was also seen with the Ubuntu
24.04 libdbus in the rd-linux-verify image.

  ./extract_and_run.py              -> passes
  BASELINE=1 ./extract_and_run.py   -> fails (the portal cases abort)
RD_REPO=<desktop-apps checkout>, BASE_REF=<ref> (default: the fix commit's parent).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '7f1090d9c^')
XDG = 'win-linux/src/platform_linux/xdgdesktopportal.cpp'
GTK = 'win-linux/src/platform_linux/gtkfilechooser.cpp'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def func(src, head):
    """The function whose definition starts with `head`, by brace matching."""
    i = src.find(head)
    while i != -1:     # skip forward declarations
        j = src.index(')', i)
        rest = src[j + 1:].lstrip()
        if rest.startswith('{') or rest.startswith('\n{'):
            break
        i = src.find(head, i + 1)
    if i == -1:
        sys.stderr.write('not found: %s\n' % head)
        sys.exit(2)
    j = src.index('{', i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == '{':
            depth += 1
        elif src[k] == '}':
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    sys.exit(2)


xdg = read(XDG)
gtk = read(GTK)
parts = {
    'macros': '\n'.join(l for l in xdg.splitlines() if l.startswith('#define __dbus')),
    'result': re.search(r'enum Result \{[^}]*\};', xdg).group(0),
    'filteritem': re.search(r'struct FilterItem \{[^}]*\};', xdg).group(0),
    'setCurrentName': func(xdg, 'void setCurrentName(DBusMessageIter &msg_iter, const char *name)'),
    'parseFilterString': func(xdg, 'void parseFilterString('),
    'Free': func(xdg, 'void Free(void* p)'),
    'openXdgPortal': func(xdg, 'QStringList Xdg::openXdgPortal('),
    'openGtkFileChooser': func(gtk, 'QStringList Gtk::openGtkFileChooser('),
    'inc': os.path.join(REPO, 'win-linux', 'src', 'platform_linux'),
}

harness = r'''
#include <QApplication>
#include <QWidget>
#include <QTextCodec>
#include <QStringList>
#include <dbus/dbus.h>
#include <glib.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "%(inc)s/xdgdesktopportal.h"
#include "%(inc)s/gtkfilechooser.h"

typedef unsigned long Window;
typedef unsigned int uint;
%(macros)s
%(result)s
%(filteritem)s

/* real */
%(setCurrentName)s
%(parseFilterString)s
%(Free)s

/* what each dialog was given */
static QByteArray g_name, g_path, g_title, g_flt, g_sel;

/* --- portal side: stubs for the parts that need a session bus --- */
static Result initDBus(void) { return SUCCESS; }
static void quitDBus(void) {}
static const char *getErrorText(void) { return ""; }
static void freePath(char *p) { free(p); }
static Result pathSetGetCount(const void *, uint *n) { *n = 0; return SUCCESS; }
static Result pathSetGetPath(const void *, uint, char **) { return ERROR; }
static void pathSetFreePath(const char *) {}
static void pathSetFree(const void *) {}
namespace XcbUtils { static void findWindowAsync(const char *, void *, int, void (*)(unsigned, void *)) {} }
static void onWindowFound(unsigned, void *) {}
struct CMessage { static void error(QWidget *, const QString &) {} };

/* As callXdgPortal does for a save: a real FileChooser.SaveFile message, with the
   real setCurrentName appending the name. libdbus checks the string here. */
static Result openDialog(Window, Xdg::Mode, const char *title, char **outPaths,
                         const FilterItem *, uint, FilterItem *, const char *path,
                         const char *name, bool) {
    g_title = title; g_path = path; g_name = name;
    DBusMessage *m = dbus_message_new_method_call("org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop", "org.freedesktop.portal.FileChooser", "SaveFile");
    DBusMessageIter iter, arr_iter;
    dbus_message_iter_init_append(m, &iter);
    __dbusOpen(&iter, DBUS_TYPE_ARRAY, "{sv}", &arr_iter);
    setCurrentName(arr_iter, name);
    __dbusClose(&iter, &arr_iter);
    dbus_message_unref(m);
    /* the portal answers with the path it was asked about */
    *outPaths = strdup((QByteArray(path) + "/" + QByteArray(name)).constData());
    return SUCCESS;
}

/* real */
%(openXdgPortal)s

/* --- GTK side: GTK takes UTF-8 and hands back its entry text and the filter's name --- */
static bool g_valid;
static void nativeFileDialog(const Window &, Gtk::Mode, char ***filenames, int *count,
                             const char *title, const char *file, const char *path,
                             const char *flt, char **sel_filter, bool) {
    g_title = title; g_name = file; g_path = path; g_flt = flt; g_sel = *sel_filter;
    g_valid = g_utf8_validate(title, -1, nullptr) && g_utf8_validate(file, -1, nullptr) &&
              g_utf8_validate(path, -1, nullptr) && g_utf8_validate(flt, -1, nullptr) &&
              g_utf8_validate(*sel_filter, -1, nullptr);
    *count = 1;
    *filenames = (char **)calloc(1, sizeof(char *));
    (*filenames)[0] = strdup((QByteArray(path) + "/" + QByteArray(file)).constData());
}

/* real */
%(openGtkFileChooser)s

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    const char *which = argv[1];
    QTextCodec::setCodecForLocale(QTextCodec::codecForName(argv[2]));
    const QString name = QString::fromUtf8(argv[3]);
    const QString folder = QString::fromUtf8(argv[4]);
    const QString filter = QString::fromUtf8("文档 (*.docx);;PDF (*.pdf)");
    QString sel = QString::fromUtf8("文档 (*.docx)");
    const QString want = folder + "/" + name;

    QStringList got;
    if (strcmp(which, "portal") == 0)
        got = Xdg::openXdgPortal(nullptr, Xdg::SAVE, "Save As", want, "", filter, &sel);
    else
        got = Gtk::openGtkFileChooser(nullptr, Gtk::SAVE, "Save As", want, "", filter, &sel);

    const bool same = got.size() == 1 && got.at(0) == want;
    const bool selok = sel == QString::fromUtf8("文档 (*.docx)");
    const bool valid = (strcmp(which, "portal") == 0) ? true : g_valid;
    printf("%%s\n", (same && selok && valid) ? "ok"
        : QString("FAILED: got '%%1', filter '%%2'%%3").arg(got.value(0), sel,
                    valid ? "" : ", GTK handed bytes that are not UTF-8").toUtf8().constData());
    return (same && selok && valid) ? 0 : 1;
}
''' % parts

cases = [
    # (dialog, locale encoding, name, folder)
    ('portal', 'GB18030',    '中文报告.docx', '/home/u/文档'),
    ('portal', 'ISO-8859-1', 'café.docx',               '/home/u'),
    ('portal', 'UTF-8',      '中文 \U0001F600 é.v2.docx', '/home/u'),
    ('gtk',    'GB18030',    '中文报告.docx', '/home/u/文档'),
    ('gtk',    'ISO-8859-1', '中文.docx',            '/home/u'),
    ('gtk',    'UTF-8',      '中文 \U0001F600 é.v2.docx', '/home/u'),
]

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w', encoding='utf-8').write(harness)
    Q = os.environ.get('QT5', '/opt/homebrew/opt/qt@5')
    B = os.environ.get('BREW', '/opt/homebrew')
    pc = subprocess.run(['pkg-config', '--cflags', '--libs', 'dbus-1', 'glib-2.0'],
                        capture_output=True, text=True,
                        env=dict(os.environ, PKG_CONFIG_PATH=B + '/lib/pkgconfig:' + B + '/share/pkgconfig'))
    if pc.returncode != 0:
        raise SystemExit('pkg-config dbus-1/glib-2.0 failed: ' + pc.stderr)
    inc = []
    for fw in ('QtWidgets', 'QtGui', 'QtCore'):
        inc += ['-I' + Q + '/lib/' + fw + '.framework/Headers', '-framework', fw]
    c = subprocess.run(['clang++', '-std=c++14', '-fPIC', '-w', '-o', exe, src,
                        '-F' + Q + '/lib', '-Wl,-rpath,' + Q + '/lib'] + inc + pc.stdout.split(),
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')

    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_LOGGING_RULES='*=false')
    failures = 0
    for which, enc, name, folder in cases:
        r = subprocess.run([exe, which, enc, name, folder], env=env, capture_output=True, text=True)
        if r.returncode < 0:
            line = 'FAILED: the process died (signal %d)' % -r.returncode
            m = re.search(r'assertion "([^"]+)" failed', r.stderr)
            if m:
                line += ' - libdbus: %s' % m.group(1)
        else:
            line = r.stdout.strip() or ('FAILED: exit %d' % r.returncode)
        ok = r.returncode == 0 and line == 'ok'
        failures += not ok
        print('  %-6s %-10s %-28s %s' % (which, enc, name, line))
    print('\n%s' % ('FAILED' if failures else
                    'ok - the Linux dialogs get and give back the name as UTF-8 under any locale'))
    sys.exit(1 if failures else 0)
