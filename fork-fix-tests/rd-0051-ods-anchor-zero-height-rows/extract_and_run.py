#!/usr/bin/env python3
"""
RD-0051 (found in passing while testing #2187, UPSTREAM_TRIAGE.md "Latent
problems"): a form control (or any cell-anchored drawing) converted from ODS to
XLSX could come back at a nonsense row - `<xdr:row>18446744071562068031</xdr:row>`
for a Button that was at the top of an ODS made from our own XLSX.

Cause, two parts in core/OdfFile/Reader:
  - Format/table_xlsx.cpp, table_table_row::xlsx_convert: a row without a
    style:row-height (no row style, or one without a height) was registered
    in the table metrics with height 0, where XLSX gives it the default row
    height.
  - Converter/xlsx_table_metrics.cpp, regions::search(double) and
    search(int, double): a position past the last region steps over it by
    `diff / last_r.length`. For a zero-length last region (rows of height 0,
    or hidden rows) that is a division by zero; the infinity converted to int
    (saturating on arm64, INT_MIN on x86) plus the last cell overflowed into
    the row printed above (size_t of a negative int).
Fix: such rows count with the default height (row default style's height,
else the formula sheetFormatPr uses), and a zero-length last region is not
divided by - the remainder is the offset within the cell after it.

What runs: the REAL `class regions` is lifted out of xlsx_table_metrics.cpp by
brace matching (git show BASE_REF:... with BASELINE=1) and compiled with a tiny
driver: zero-height rows followed by a lookup below them, by both search
overloads. Passes when every cell index is 0..100 and every offset finite.

Optional end-to-end (RD_X2T=<x2t built from the tree under test>): the #2187
Button fixture goes xlsx -> ods -> xlsx and controlPr/anchor rows must be
< 1048576. On the pre-fix converter this prints the 1844... row; the
row-height half of the fix is only covered by this part.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read xlsx_table_metrics.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0051 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'de64a4e454^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1] + ';'
    sys.exit('unbalanced braces after %r' % start)


def unit():
    src = read('OdfFile/Reader/Converter/xlsx_table_metrics.cpp')
    drv = '#include <vector>\n#include <utility>\n#include <cstdio>\n#include <cmath>\n'
    drv += block(src, 'struct region') + '\n' + block(src, 'class regions') + r'''
int main() {
    // one empty row of height 0 (what an unstyled row was), then hidden rows
    regions a; a.add(1, 0.0);
    regions b; b.add(2, 15.0); b.add(5, 0.0);
    std::pair<int, double> r[4] = { a.search(9.0), a.search(0, 45.0), b.search(40.0), b.search(2, 10.0) };
    for (int i = 0; i < 4; ++i) printf("R%d %d %f\n", i, r[i].first, r[i].second);
    return 0;
}
'''
    work = tempfile.mkdtemp(prefix='rd0051-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-O0', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    r = subprocess.run([exe], capture_output=True, text=True)
    res = re.findall(r'R(\d) (-?\d+) (\S+)', r.stdout)
    ok = len(res) == 4 and all(0 <= int(c) <= 100 and re.match(r'^-?[\d.]+$', o) for _, c, o in res)
    print(('ok   ' if ok else 'FAIL ') + 'table metrics past zero-height rows (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ', '.join('cell %s off %s' % (c, o) for _, c, o in res) or r.stdout + r.stderr))
    return ok


def e2e():
    x2t = os.environ.get('RD_X2T')
    if not x2t:
        print('skip end-to-end ODS round trip (set RD_X2T)')
        return True
    sys.path.insert(0, os.path.join(HERE, '..', 'issue-2187-shape-macro'))
    import run as R  # the #2187 fixture builder and x2t driver
    import zipfile
    R.X2T = x2t
    if os.environ.get('X2T_FRAMEWORKS'):
        R.FRAMEWORKS = os.environ['X2T_FRAMEWORKS']
    d = tempfile.mkdtemp(prefix='rd0051-e2e-')
    R.build_button_fixture(os.path.join(d, 'in.xlsx'), R.MACRO)
    rc1 = R.convert(os.path.join(d, 'in.xlsx'), os.path.join(d, 'mid.ods'), R.FORMAT_ODS, d)
    rc2 = R.convert(os.path.join(d, 'mid.ods'), os.path.join(d, 'out.xlsx'), R.FORMAT_XLSX, d)
    rows = []
    if rc1 == 0 and rc2 == 0:
        body = zipfile.ZipFile(os.path.join(d, 'out.xlsx')).read('xl/worksheets/sheet1.xml').decode('utf-8', 'replace')
        anchor = re.search(r'<anchor\b.*?</anchor>', body, re.S)
        rows = [int(v) for v in re.findall(r'<xdr:row>(\d+)</xdr:row>', anchor.group(0))] if anchor else []
    ok = len(rows) == 2 and all(v < 1048576 for v in rows)
    print(('ok   ' if ok else 'FAIL ') + 'ODS round trip Button anchor rows (%s): %s' % (x2t, rows or 'rc=%d/%d' % (rc1, rc2)))
    return ok


if __name__ == '__main__':
    a = unit()
    b = e2e()
    sys.exit(0 if a and b else 1)
