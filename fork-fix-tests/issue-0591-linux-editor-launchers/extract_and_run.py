#!/usr/bin/env python3
"""
#591 - "Make separate apps for spreadsheets, presentations and docs". The product
is one application with tabs; splitting it is a product decision and not done.
What is done is the conventional small part, as an OPTION: on Linux the package
had a single menu entry (ration-docs.desktop; per-editor "New ..." only as
Desktop Actions in its right-click menu), while the Windows installer already
creates a Start menu shortcut per editor (inno common.iss, --new:word/cell/slide/
form). desktop-apps package/Makefile now takes EDITOR_LAUNCHERS=1, which adds
ration-docs-{word,cell,slide,form}.desktop (from common/linux/
desktopeditors-editor.desktop.m4: same binary with --new:<editor>, no MimeType so
file associations stay with the main entry) and a 256x256 hicolor icon each
(common/linux/icons/editors/, the Windows per-editor icons). Default 0: the
package is what it was.

How it is tested: the REAL package/ directory (Makefile, m4 templates, icons) is
copied and GNU make + m4 run in RD_IMAGE (rd-linux-verify:24.04; make and m4 are
apt-installed, so the first run needs network). LINUX_DEPS is printed with and
without the option, the four launchers and icons are built with the real rules,
and each .desktop is checked with desktop-file-validate.
BASELINE=1 takes package/ from BASE_REF: EDITOR_LAUNCHERS=1 adds nothing -> FAILS.

  ./extract_and_run.py             RD_REPO (default ../../desktop-apps), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL

NOT claimed: a full `make deb`/`make rpm` with the option (needs the 1.9 GB
payload; both pick up everything under build/main/usr/share, see package.install.m4
and rpm common.spec %files), how a given desktop shows or groups the entries, and
whether the product wants them on (that is why it is an option). No publishing.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '4d3ee8ad5^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
EDITORS = ['word', 'cell', 'slide', 'form']

RUN = r'''
set -e
export DEBIAN_FRONTEND=noninteractive
command -v m4 >/dev/null && command -v make >/dev/null || \
  { apt-get update -qq >/dev/null && apt-get install -y -qq make m4 >/dev/null; }
cd /t/package
printf 'p:\n\t@echo $(LINUX_DEPS)\n' > /t/p.mk
echo "DEFAULT|$(make -s -f Makefile -f /t/p.mk p 2>/dev/null)"
DEPS=$(make -s -f Makefile -f /t/p.mk p EDITOR_LAUNCHERS=1 2>/dev/null)
echo "OPTION|$DEPS"
T=$(echo $DEPS | tr ' ' '\n' | grep -E 'ration-docs-[a-z]+\.(desktop|png)$' || true)
[ -z "$T" ] || make -s EDITOR_LAUNCHERS=1 $T >/dev/null 2>&1
for e in word cell slide form; do
  f=build/main/usr/share/applications/ration-docs-$e.desktop
  i=build/main/usr/share/icons/hicolor/256x256/apps/ration-docs-$e.png
  if [ -f $f ]; then
    v=$(desktop-file-validate $f 2>&1 | tr '\n' ' ')
    echo "FILE|$e|$(grep '^Name=' $f)|$(grep '^Exec=' $f)|$(grep '^Icon=' $f)|$(grep -c '^MimeType=' $f || true)|${v:-valid}"
  else
    echo "FILE|$e|missing||||"
  fi
  [ -f $i ] && echo "ICON|$e|$(head -c 24 $i | od -An -tx1 | tr -d ' \n')" || echo "ICON|$e|missing"
done
'''

tmp = tempfile.mkdtemp(prefix='rd0591-')
failures = 0


def check(what, ok, detail=''):
    global failures
    failures += not ok
    print('  %-60s %s' % (what, 'ok' if ok else 'FAILED ' + detail))


try:
    if BASELINE:
        a = subprocess.run(['git', '-C', APPS, 'archive', BASE_REF, 'package'], capture_output=True, check=True)
        subprocess.run(['tar', '-x', '-C', tmp], input=a.stdout, check=True)
    else:
        shutil.copytree(os.path.join(APPS, 'package'), os.path.join(tmp, 'package'), symlinks=True,
                        ignore=shutil.ignore_patterns('build', 'tar', 'deb*/build', 'rpm*/build'))
    open(os.path.join(tmp, 'run.sh'), 'w').write(RUN)
    r = subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % tmp, IMAGE, 'bash', '/t/run.sh'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit('harness failed in %s' % IMAGE)
    out = {}
    files, icons = {}, {}
    for line in r.stdout.splitlines():
        parts = line.split('|')
        if parts[0] in ('DEFAULT', 'OPTION'):
            out[parts[0]] = parts[1].split()
        elif parts[0] == 'FILE':
            files[parts[1]] = parts[2:]
        elif parts[0] == 'ICON':
            icons[parts[1]] = parts[2]

    print('#591 per-editor launchers (EDITOR_LAUNCHERS):')
    extra = [d for d in out.get('DEFAULT', []) if 'ration-docs-' in d]
    check('default build: no per-editor entries (package unchanged)', not extra, str(extra))
    want = ['build/main/usr/share/applications/ration-docs-%s.desktop' % e for e in EDITORS] + \
           ['build/main/usr/share/icons/hicolor/256x256/apps/ration-docs-%s.png' % e for e in EDITORS]
    missing = [w for w in want if w not in out.get('OPTION', [])]
    check('EDITOR_LAUNCHERS=1: 4 launchers + 4 icons in the package', not missing, '%d missing' % len(missing))
    names = set()
    for e in EDITORS:
        name, exe, icon, mime, valid = (files.get(e, []) + [''] * 5)[:5]
        names.add(name)
        ok = (exe == 'Exec=/usr/bin/ration-docs --new:%s' % e and icon == 'Icon=ration-docs-%s' % e
              and mime == '0' and valid == 'valid')
        check('%-5s %s' % (e, name or 'missing'), ok, '%s %s mime=%s %s' % (exe, icon, mime, valid))
        # PNG signature + IHDR width/height 256x256
        check('%-5s icon is a 256x256 PNG' % e,
              icons.get(e, '').startswith('89504e470d0a1a0a') and icons.get(e, '').endswith('0000010000000100'),
              icons.get(e, 'missing'))
    check('four distinct names', len(names) == 4 and '' not in names, str(names))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('FAIL' if failures else 'PASS')
sys.exit(1 if failures else 0)
