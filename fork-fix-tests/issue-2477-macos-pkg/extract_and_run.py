#!/usr/bin/env python3
"""
#2477 - "Distribution in a pkg format": a macOS installer package for deployment
through MDM. The macOS build produced only a disk image (fastlane: gym with
skip_package_pkg, then appdmg), which management tools cannot install
unattended. desktop-apps macos/make_pkg.sh now builds a product archive
(Ration-Docs-<version>-<arch>.pkg) from the same bundle the DMG carries.

What the package must get right, and what this test checks on a package built by
the REAL script from a minimal arm64 application bundle (compiled here with cc):
- installs into /Applications and is NOT relocatable (pkgbuild's default lets
  Installer put the update wherever another copy with the same bundle id is, e.g.
  ~/Downloads, leaving /Applications on the old version);
- package identifier <CFBundleIdentifier>.pkg and version from the bundle;
- hostArchitectures is what the executable holds (productbuild --synthesize writes
  "x86_64,arm64" for any payload, so an arm64-only app would install on an Intel
  Mac and not start) and the bundle's LSMinimumSystemVersion is enforced;
- the payload keeps symlinks (the help images are deduplicated into symlinks) and
  the executable bit.
BASELINE=1 takes macos/make_pkg.sh from BASE_REF, where it does not exist -> FAILS.

  ./extract_and_run.py             RD_REPO (default ../../desktop-apps), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL

macOS only (pkgbuild, productbuild, pkgutil, cc). NOT claimed: installing the
package (needs root and writes /Applications), signing (--sign needs a Developer
ID Installer certificate) and notarization; MDM acceptance. No publishing.
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '2ca197455^')
BASELINE = bool(os.environ.get('BASELINE'))
SCRIPT = 'macos/make_pkg.sh'

if sys.platform != 'darwin':
    raise SystemExit('macOS only')

tmp = tempfile.mkdtemp(prefix='rd2477-')
failures = 0


def check(what, ok, detail=''):
    global failures
    failures += not ok
    print('  %-58s %s' % (what, 'ok' if ok else 'FAILED ' + detail))


try:
    script = os.path.join(tmp, 'make_pkg.sh')
    if BASELINE:
        r = subprocess.run(['git', '-C', APPS, 'show', '%s:%s' % (BASE_REF, SCRIPT)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print('#2477: %s does not exist at %s' % (SCRIPT, BASE_REF))
            print('FAIL')
            sys.exit(1)
        open(script, 'w').write(r.stdout)
    else:
        shutil.copy(os.path.join(APPS, SCRIPT), script)

    app = os.path.join(tmp, 'in', 'Ration Docs.app')
    os.makedirs(os.path.join(app, 'Contents', 'MacOS'))
    os.makedirs(os.path.join(app, 'Contents', 'Resources', 'help'))
    open(os.path.join(tmp, 'm.c'), 'w').write('int main(void){return 0;}\n')
    subprocess.run(['cc', '-arch', 'arm64', os.path.join(tmp, 'm.c'), '-o',
                    os.path.join(app, 'Contents', 'MacOS', 'Ration Docs')], check=True)
    open(os.path.join(app, 'Contents', 'Resources', 'help', 'a.png'), 'w').write('x')
    os.symlink('a.png', os.path.join(app, 'Contents', 'Resources', 'help', 'b.png'))
    with open(os.path.join(app, 'Contents', 'Info.plist'), 'wb') as f:
        plistlib.dump({'CFBundleIdentifier': 'works.ration.test2477',
                       'CFBundleShortVersionString': '2026.9.1',
                       'CFBundleExecutable': 'Ration Docs',
                       'CFBundlePackageType': 'APPL',
                       'LSMinimumSystemVersion': '11.0'}, f)

    out = os.path.join(tmp, 'out')
    r = subprocess.run(['sh', script, '--app', app, '--out', out], capture_output=True, text=True)
    print('#2477 make_pkg.sh on an arm64 bundle (exit %d):' % r.returncode)
    pkg = os.path.join(out, 'Ration-Docs-2026.9.1-arm64.pkg')
    check('Ration-Docs-<version>-<arch>.pkg written', r.returncode == 0 and os.path.isfile(pkg),
          r.stderr.strip())
    if os.path.isfile(pkg):
        x = os.path.join(tmp, 'x')
        subprocess.run(['pkgutil', '--expand-full', pkg, x], check=True, capture_output=True)
        dist = open(os.path.join(x, 'Distribution')).read()
        comp = [d for d in os.listdir(x) if d.endswith('.pkg')]
        check('product archive with one component package', len(comp) == 1, str(comp))
        info = open(os.path.join(x, comp[0], 'PackageInfo')).read() if comp else ''
        head = re.search(r'<pkg-info[^>]*>', info)
        head = head.group(0) if head else ''
        check('installs into /Applications', 'install-location="/Applications"' in head, head)
        check('not relocatable', 'relocatable="false"' in head and '<relocate>' not in info, head)
        check('identifier <bundle id>.pkg, version from the bundle',
              'identifier="works.ration.test2477.pkg"' in head and 'version="2026.9.1"' in head, head)
        m = re.search(r'hostArchitectures="([^"]*)"', dist)
        check('hostArchitectures is arm64 only', bool(m) and m.group(1) == 'arm64',
              m.group(1) if m else 'absent')
        check('minimum macOS 11.0 enforced', '<os-version min="11.0"/>' in dist)
        payload = os.path.join(x, comp[0], 'Payload', 'Ration Docs.app', 'Contents') if comp else ''
        link = os.path.join(payload, 'Resources', 'help', 'b.png')
        check('symlinks kept in the payload', os.path.islink(link) and os.readlink(link) == 'a.png')
        exe = os.path.join(payload, 'MacOS', 'Ration Docs')
        check('executable kept executable', os.path.isfile(exe) and os.access(exe, os.X_OK))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
