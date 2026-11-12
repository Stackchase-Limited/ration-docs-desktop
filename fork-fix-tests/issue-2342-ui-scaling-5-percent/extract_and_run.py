#!/usr/bin/env python3
"""
#2342 (part 1) - "Precision scaling": Settings > Interface scaling (Windows/Linux)
jumps 100% -> 125% -> 150%; the reporter wants 5% steps between 100% and 150%.

What 9.4 had: the start page offered 100, 125, 150, ..., 500 (panelsettings.js),
and win-linux turned the choice into the "force-scale" user setting with two
hard-coded tables (utils.cpp Scaling::scalingToFactor / factorToScaling) - any
other value became "0" (Auto) both ways. The library itself takes any factor
(applicationmanager_p.h reads force-scale with GetDouble, cefview.cpp passes it
to the browser as the device scale), and the same non-quarter factors already
reach it under Auto on a 110%-scaled Windows/GNOME desktop.

Now the list has 105, 110, ..., 145 too, and the two functions compute the factor
instead of looking it up: 5% steps from 100 to 150, 25% to 300, 50% to 500 (the
old values, written exactly as before: "1", "1.25", "2.5"...), anything else "0".
The default (Auto) and every existing choice are unchanged.

What this runs: the real Scaling namespace lifted from win-linux/src/utils.cpp and
compiled against QtCore, round-tripping every offered value and some invalid ones;
the real _scaling array lifted from panelsettings.js.

NOT claimed: how 105-145% looks. The Qt title/tab bar picks its stylesheet by
rounding up to the next quarter step (getWindowStylesheets, choose_scaling), so at
110% it is drawn at 125% while the editor is at 110% - as under Auto on a 110%
desktop today; raster icons in the editors are scaled from the nearest set. Needs a
Windows/Linux GUI check. The Firefox-style tab bar (part 2) is not done.

BASELINE=1 reads the sources from BASE_REF (the parent of the fix) and fails.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '02d1fc2f6c^')
BASELINE = bool(os.environ.get('BASELINE'))
UTILS = 'win-linux/src/utils.cpp'
PANEL = 'common/loginpage/src/panelsettings.js'
failures = []


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(src, anchor):
    at = src.index(anchor)
    depth = 0
    for i in range(src.index('{', at), len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]


def check(ok, what):
    print('  %-70s %s' % (what, 'ok' if ok else 'FAILED'))
    if not ok:
        failures.append(what)


HARNESS = r'''
#include <QString>
#include <string>
#include <stdio.h>
%(ns)s
int main(int argc, char ** argv) {
    for (int i = 1; i < argc; i++) {
        std::wstring f = Scaling::scalingToFactor(QString(argv[i]));
        printf("%%s %%s %%s\n", argv[i], QString::fromStdWString(f).toUtf8().constData(),
               Scaling::factorToScaling(f).toUtf8().constData());
    }
    printf("old default %%s\n", Scaling::factorToScaling(L"default").toUtf8().constData());
    return 0;
}
'''

print('#2342 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
panel = read(PANEL)
m = re.search(r'const _scaling = \[([^\]]*)\]', panel)
offered = [int(x) for x in m.group(1).split(',')]
print('start page offers:', offered)
want = list(range(100, 151, 5)) + [175, 200, 225, 250, 275, 300, 350, 400, 450, 500]
check(offered == want, 'the list has 5% steps up to 150% and the old values after')

ns = extract(read(UTILS), 'namespace Scaling {')
q = '/opt/homebrew/opt/qt@5'
with tempfile.TemporaryDirectory() as tmp:
    open(os.path.join(tmp, 'h.cpp'), 'w').write(HARNESS % {'ns': ns})
    if os.path.isdir(q):
        cmd = ['clang++', '-std=c++14', '-w', '-I' + q + '/lib/QtCore.framework/Headers', '-F' + q + '/lib', '-framework', 'QtCore',
               '-Wl,-rpath,' + q + '/lib']
    else:
        cmd = ['g++', '-std=c++14', '-w', '-fPIC'] + subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt5Core'],
                                                                      capture_output=True, text=True).stdout.split()
    c = subprocess.run(cmd + ['-o', os.path.join(tmp, 'h'), os.path.join(tmp, 'h.cpp')], capture_output=True, text=True)
    if c.returncode:
        sys.stderr.write(c.stderr)
        sys.exit('harness did not compile')
    args = [str(v) for v in want] + ['0', '99', '107', '155', '325', '600', 'abc']
    out = subprocess.run([os.path.join(tmp, 'h')] + args, capture_output=True, text=True).stdout
    print(out)
    res = {l.split()[0]: l.split()[1:] for l in out.splitlines() if not l.startswith('old')}
    old = {'100': '1', '125': '1.25', '150': '1.5', '175': '1.75', '200': '2', '225': '2.25', '250': '2.5',
           '275': '2.75', '300': '3', '350': '3.5', '400': '4', '450': '4.5', '500': '5'}
    check(all(res[k] == [v, k] for k, v in old.items()), 'old choices give the same force-scale strings as before')
    check(all(res[str(v)] == [str(v / 100).rstrip('0').rstrip('.') if v % 100 else str(v // 100), str(v)]
              for v in range(105, 150, 5) if v != 125), '105..145% give 1.05..1.45 and read back')
    check(all(res[k] == ['0', '0'] for k in ['0', '99', '107', '155', '325', '600', 'abc']), 'anything else is Auto (0)')
    check('old default 0' in out, '"default" (Auto) reads back as 0')

print('\n%s' % ('ok - interface scaling can be set in 5% steps between 100% and 150%' if not failures
                else 'FAILED - %d check(s): %s' % (len(failures), '; '.join(failures))))
sys.exit(0 if not failures else 1)
