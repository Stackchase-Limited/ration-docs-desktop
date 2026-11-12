#!/usr/bin/env python3
"""RD-0019: a second launch sends its arguments as UTF-8 (main.cpp, _out_args.toUtf8()); the Linux
first instance decoded them with QString::fromLocal8Bit, so under a non-UTF-8 locale a path such as
/path/中文文档.docx arrived garbled and a blank document opened instead.

Takes the real decoding statement from win-linux/src/platform_linux/singleapplication.cpp (working tree,
or BASE_REF with BASELINE=1), compiles it against real Qt 5 with the locale codec set to ISO-8859-1
(what a POSIX/latin1 locale gives Qt), and feeds it the bytes the real sender produces.
  RD_REPO=<desktop-apps> (default ../../desktop-apps)  QT=<qt5 prefix> (default /opt/homebrew/opt/qt@5)
"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '687091511^')
QT = os.environ.get('QT', '/opt/homebrew/opt/qt@5')
REL = 'win-linux/src/platform_linux/singleapplication.cpp'
if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)], capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()
m = re.search(r'onMessageReceived\(\[=\]\(void \*buff, size_t size\) \{\s*(?://[^\n]*\n\s*)*(QString data = QString::\w+\(\(const char\*\)buff, size\);)', src)
if not m:
    print('FAIL: decoding statement not found in onMessageReceived - the extractor needs updating'); sys.exit(2)
stmt = m.group(1)
if not os.path.isdir(QT):
    print('CANNOT RUN: Qt 5 not found at %s' % QT); sys.exit(2)
prog = r'''
#include <QString>
#include <QTextCodec>
#include <cstdio>
int main() {
    QTextCodec::setCodecForLocale(QTextCodec::codecForName("ISO-8859-1"));
    QString sent = QString::fromUtf8("/home/u/\xe4\xb8\xad\xe6\x96\x87\xe6\x96\x87\xe6\xa1\xa3.docx\x01");
    QByteArray wire = sent.toUtf8();               // what main.cpp sends
    void *buff = wire.data(); size_t size = wire.size();
    %s
    std::printf("received: %%s\n", data.toUtf8().constData());
    return data == sent ? 0 : 1;
}
''' % stmt
with tempfile.TemporaryDirectory() as t:
    cpp = os.path.join(t, 'm.cpp'); open(cpp, 'w').write(prog)
    exe = os.path.join(t, 'm')
    cc = ['clang++', '-std=c++17', cpp, '-o', exe, '-F%s/lib' % QT, '-I%s/lib/QtCore.framework/Headers' % QT,
          '-framework', 'QtCore', '-Wl,-rpath,%s/lib' % QT]
    r = subprocess.run(cc, capture_output=True, text=True)
    if r.returncode:
        print('CANNOT RUN: compile failed\n' + r.stderr[-1500:]); sys.exit(2)
    r = subprocess.run([exe], capture_output=True, text=True)
    label = 'baseline %s' % BASE_REF if os.environ.get('BASELINE') else 'working tree'
    print('%s: %s  [%s]' % (label, r.stdout.strip(), stmt.split('=')[1].strip()))
    if r.returncode:
        print('FAIL RD-0019: a non-ASCII path from a second launch arrives garbled under a non-UTF-8 locale'); sys.exit(1)
    print('PASS RD-0019: the first instance receives the path exactly as sent')
