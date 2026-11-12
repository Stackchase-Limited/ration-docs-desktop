#!/usr/bin/env python3
"""
#2404 - "a ZIP for a portable version (USB stick)?". The Windows portable ZIP
already exists (desktop-apps package/make_zip.ps1, run by build_tools
package_desktop.py make_zip), and a ZIP knows it is one because it has no
converter/package.config - the file the installers write. What was wrong in that
mechanism: AppOptions::packageType (desktop-apps win-linux/src/utils.cpp) read
"./converter/package.config", relative to the CURRENT directory, not the
executable's. An installed copy started with another working directory (a
document opened from Explorer, a shortcut whose "Start in" is elsewhere) found
nothing and took itself for the portable ZIP: the file association prompt was
suppressed (association.cpp) and the updater ran its portable path
(cupdatemanager.cpp); and a ZIP started from a folder that happened to hold a
converter/package.config took that file's package kind.
Fix: read it beside the executable (NSFile::GetProcessDirectory()). make_zip.ps1
now also documents what the ZIP is and what "portable" does and does not mean.

How it is tested: the REAL packageType() is extracted by brace matching and
compiled with the real Qt QSettings (INI reader) in the rd-linux-verify:24.04
image (RD_IMAGE), with NSFile::GetProcessDirectory standing in as the directory of
/proc/self/exe. The binary is placed in an "app" directory and run from several
working directories: installed copy (package=exe) run from elsewhere / from its
own directory; the ZIP (no package.config) run from its own directory / from a
directory holding someone else's converter/package.config (package=msi).
BASELINE=1 reads utils.cpp from BASE_REF: the installed copy started from
elsewhere says Portable -> FAILS.

  ./extract_and_run.py             RD_REPO (default ../../desktop-apps), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL

NOT claimed: building the ZIP (Windows, 7z; no Windows build machine here) and
anything Windows-specific about association/updates beyond the package kind they
are given; the Windows compile of utils.cpp (Linux compiled). No publishing.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', 'f379f0bf7^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', APPS, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(APPS, rel), encoding='utf-8').read()


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


src = read('win-linux/src/utils.cpp')
at = src.find('auto packageType() -> AppPackageType {')
if at == -1:
    raise SystemExit('AppOptions::packageType not found')
fn = brace_match(src, at)

HARNESS = r'''
#include <QSettings>
#include <QString>
#include <string>
#include <stdio.h>
#include <unistd.h>
#include <limits.h>
namespace NSFile {
    static std::wstring GetProcessDirectory() {
        char buf[PATH_MAX] = {0}; ssize_t n = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
        std::string p(buf, n > 0 ? n : 0); p = p.substr(0, p.rfind('/'));
        return std::wstring(p.begin(), p.end());
    }
}
namespace AppOptions {
    enum class AppPackageType { Unknown, ISS, MSI, Snap, Flatpack, Portable };
    %s
}
int main() {
    using T = AppOptions::AppPackageType;
    T t = AppOptions::packageType();
    puts(t == T::ISS ? "exe installer" : t == T::MSI ? "msi installer" : t == T::Portable ? "portable ZIP" : "other");
    return 0;
}
''' % fn

RUN = r'''
set -e
Q=$(dirname $(find /usr/include -maxdepth 3 -type d -name QtCore -path '*qt5*' | head -1))
L=$(dirname $(find /usr/lib -name 'libQt5Core.so*' | head -1))
g++ -std=c++17 -fPIC -w -I$Q -I$Q/QtCore /t/main.cpp -o /t/pt -L$L -lQt5Core
mkdir -p /w/installed/converter /w/zip /w/elsewhere /w/other/converter
cp /t/pt /w/installed/RationDocs; cp /t/pt /w/zip/RationDocs
printf '[General]\npackage=exe\n' > /w/installed/converter/package.config
printf '[General]\npackage=msi\n' > /w/other/converter/package.config
echo "installed (exe), started from elsewhere|$(cd /w/elsewhere && /w/installed/RationDocs)"
echo "installed (exe), started from its folder|$(cd /w/installed && ./RationDocs)"
echo "ZIP, started from its folder|$(cd /w/zip && ./RationDocs)"
echo "ZIP, started where another package.config is|$(cd /w/other && /w/zip/RationDocs)"
'''

WANT = {
    'installed (exe), started from elsewhere': 'exe installer',
    'installed (exe), started from its folder': 'exe installer',
    'ZIP, started from its folder': 'portable ZIP',
    'ZIP, started where another package.config is': 'portable ZIP',
}

tmp = tempfile.mkdtemp(prefix='rd2404-')
failures = 0
try:
    open(os.path.join(tmp, 'main.cpp'), 'w').write(HARNESS)
    open(os.path.join(tmp, 'run.sh'), 'w').write(RUN)
    r = subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % tmp, IMAGE, 'sh', '/t/run.sh'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit('harness failed to build/run in %s' % IMAGE)
    print('#2404 package kind the app reads:')
    seen = 0
    for line in r.stdout.strip().splitlines():
        what, got = line.split('|')
        want = WANT[what]
        ok = got == want
        seen += 1
        failures += not ok
        print('  %-46s -> %-14s %s' % (what, got, 'ok' if ok else 'FAILED, want ' + want))
    failures += seen != len(WANT)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
