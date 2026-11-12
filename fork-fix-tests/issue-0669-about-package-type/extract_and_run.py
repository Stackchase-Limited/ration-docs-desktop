#!/usr/bin/env python3
"""
#669 - "About should include information about the packaging type".

Already in 9.4 for the packages that write converter/package.config (deb, rpm,
Windows exe and msi): CMainWindowImpl::refreshAboutVersion() sends it to the
start page as "pkg" and About shows "<version> (x64 deb)". What was wrong:
Flatpak, Snap and AppImage builds are normally made from the .deb and carry its
package.config, so About said "deb" for them (or nothing, without the file).

Now aboutPackageType() (cmainwindowimpl.cpp) asks the sandbox first on Linux:
/.flatpak-info -> "flatpak"; the executable under $SNAP -> "snap"; APPIMAGE set
and the executable under $APPDIR -> "AppImage"; else package.config as before.
Environment variables alone do not count (a deb-installed app started from a
terminal that runs as a Snap/AppImage inherits them).

This compiles the real aboutPackageType(), lifted out of cmainwindowimpl.cpp by
brace matching, against QtCore, with __linux__ forced on (it is Linux-only code)
and one test seam: the literal "/.flatpak-info" is pointed at a file in a temp
directory, since a test cannot create files in /. The harness binary sits in a
fake install tree (<root>/opt/app/harness + converter/package.config "deb") and is
run once per environment.

NOT claimed: real Flatpak/Snap/AppImage runtimes (their markers are the
documented ones: /.flatpak-info, $SNAP, $APPIMAGE/$APPDIR); the start page
rendering, which is unchanged ("pkg" was already shown).

BASELINE=1 reads cmainwindowimpl.cpp from BASE_REF (the parent of the fix): there
is no such function - package.config is read inline - so it fails.
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
REL = 'win-linux/src/prop/cmainwindowimpl.cpp'
BASE_REF = os.environ.get('BASE_REF', 'ec03992720^')
BASELINE = bool(os.environ.get('BASELINE'))

if BASELINE:
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()


def brace_match(s, at):
    i0 = s.index('{', at)
    depth = 0
    for i in range(i0, len(s)):
        if s[i] == '{':
            depth += 1
        elif s[i] == '}':
            depth -= 1
            if depth == 0:
                return s[at:i + 1]
    raise SystemExit('unbalanced braces')


print('#669 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
at = src.find('static QString aboutPackageType()')
if at == -1:
    print('  no aboutPackageType(): About reads package.config only - a Flatpak/Snap/AppImage built from the .deb says "deb"')
    print('\nFAILED')
    sys.exit(1)
func = brace_match(src, at)
if '"/.flatpak-info"' not in func:
    raise SystemExit('the Flatpak marker moved - update the test seam')
func = func.replace('"/.flatpak-info"', 'g_flatpakInfo')

HARNESS = r'''
#include <QCoreApplication>
#include <QSettings>
#include <QFileInfo>
#include <QString>
#include <stdio.h>
static QString g_flatpakInfo;
#ifndef __linux__
#define __linux__ 1
#endif
%s
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    g_flatpakInfo = QString::fromLocal8Bit(qgetenv("TEST_FLATPAK_INFO"));
    printf("%%s\n", aboutPackageType().toUtf8().constData());
    return 0;
}
''' % func

d = tempfile.mkdtemp(prefix='rd669_')
try:
    appdir = os.path.join(d, 'opt', 'app')
    os.makedirs(os.path.join(appdir, 'converter'))
    with open(os.path.join(appdir, 'converter', 'package.config'), 'w') as f:
        f.write('package = deb\n')
    srcf, exe = os.path.join(d, 'h.cpp'), os.path.join(appdir, 'harness')
    open(srcf, 'w').write(HARNESS)
    if platform.system() == 'Darwin':
        q = '/opt/homebrew/opt/qt@5'
        cmd = ['clang++', '-std=c++14', '-w', '-I' + q + '/lib/QtCore.framework/Headers', '-F' + q + '/lib', '-framework', 'QtCore']
    else:
        cmd = ['c++', '-std=c++14', '-w', '-fPIC'] + subprocess.run(
            ['pkg-config', '--cflags', '--libs', 'Qt5Core'], capture_output=True, text=True, check=True).stdout.split()
    c = subprocess.run(cmd + ['-o', exe, srcf], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    marker = os.path.join(d, 'flatpak-info')
    real_app = os.path.realpath(appdir)
    base = {k: v for k, v in os.environ.items() if k not in ('SNAP', 'APPDIR', 'APPIMAGE')}
    base['TEST_FLATPAK_INFO'] = marker
    cases = [
        ({}, False, 'deb', 'installed from the .deb'),
        ({}, True, 'flatpak', 'inside a Flatpak sandbox'),
        ({'SNAP': os.path.dirname(real_app)}, False, 'snap', 'executable under $SNAP'),
        ({'SNAP': '/snap/other-app/12'}, False, 'deb', '$SNAP of a parent snap (terminal)'),
        ({'APPDIR': os.path.dirname(os.path.dirname(real_app)), 'APPIMAGE': '/home/u/RationDocs.AppImage'}, False, 'AppImage', 'executable under $APPDIR'),
        ({'APPDIR': real_app, 'APPIMAGE': '/home/u/RationDocs.AppImage'}, False, 'AppImage', 'executable at the top of $APPDIR'),
        ({'APPDIR': os.path.dirname(os.path.dirname(real_app))}, False, 'deb', '$APPDIR without $APPIMAGE'),
        ({'APPDIR': '/tmp/.mount_other', 'APPIMAGE': '/home/u/Term.AppImage'}, False, 'deb', 'AppImage vars of a parent AppImage'),
    ]
    failures = 0
    for env, flatpak, want, what in cases:
        if flatpak:
            open(marker, 'w').close()
        elif os.path.exists(marker):
            os.remove(marker)
        e = dict(base); e.update(env)
        got = subprocess.run([exe], capture_output=True, text=True, env=e).stdout.strip()
        ok = got == want
        failures += not ok
        print('  %-40s -> About says %-9r %s' % (what, got, 'ok' if ok else 'FAILED (want %r)' % want))
    print('\n%s' % ('FAILED' if failures else 'ok - About names the Flatpak/Snap/AppImage the app runs in, else package.config'))
    sys.exit(1 if failures else 0)
finally:
    shutil.rmtree(d, ignore_errors=True)
