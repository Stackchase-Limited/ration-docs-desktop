#!/usr/bin/env python3
"""
RD-0011 (our corpus run, no upstream issue): converting an ODS/FODS spreadsheet
(open in the editor, or save as XLSX) read past a global table for every cell
whose office:value-type is "scientific", "fraction" or "date-time"-like.

Found with an AddressSanitizer x2t on 54 LibreOffice spreadsheet test files
(sc/qa/unit/data, e.g. functions/statistical/fods/rank.fods): global-buffer-
overflow READ in cpdoccore::oox::odf_string_to_build_in
(OdfFile/Reader/Converter/xlsx_cell_format.cpp), called from
table_table_cell / table_covered_table_cell ::xlsx_convert (table_xlsx.cpp).

Cause: odf_string_to_build_in maps an office_value_type to a built-in number
format id through `int odf2buildin_map[8]`, but office_value_type::type has 11
values (Custom ... String, then Scientific, Fraction, DateTime). Types 8..10
read whatever global follows the table and used it as the cell's number format
id. Fix: indices outside the table give 0, the value every entry of the table
holds.

What runs: the REAL anonymous-namespace table and odf_string_to_build_in are
lifted out of xlsx_cell_format.cpp (git show BASE_REF:... with BASELINE=1) and
compiled with -fsanitize=address; the REAL office_value_type enum is read from
OdfFile/DataTypes/officevaluetype.h to know how many values it has, and the
function is called for each. Passes when ASan reports nothing and every type
maps to 0.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read xlsx_cell_format.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0011 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '001b1246fd^')
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
                return text[a:i + 1]
    sys.exit('unbalanced braces after %r' % start)


def main():
    src = read('OdfFile/Reader/Converter/xlsx_cell_format.cpp')
    ns = block(src, 'namespace {')
    fn = block(src, 'int odf_string_to_build_in(')
    enum = open(os.path.join(REPO, 'OdfFile', 'DataTypes', 'officevaluetype.h'), encoding='utf-8-sig').read()
    body = block(enum, 'enum type')
    n = len([x for x in re.sub(r'//[^\n]*', '', body[body.find('{') + 1:-1]).split(',') if x.strip()])
    if n < 8:
        sys.exit('office_value_type has %d values?' % n)
    drv = '#include <cstdio>\n' + ns + '\n' + fn + r'''
int main() {
    int bad = 0;
    for (int t = 0; t < %d; ++t) { int f = odf_string_to_build_in(t); printf("type %%d -> %%d\n", t, f); if (f) ++bad; }
    printf("NONZERO=%%d\n", bad);
    return 0;
}
''' % n
    work = tempfile.mkdtemp(prefix='rd0011-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', '-O0', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not a and 'NONZERO=0' in out
    print(('ok   ' if ok else 'FAIL ') + 'all %d office value types through odf_string_to_build_in (%s): %s' % (
        n, 'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else ('all map to 0' if ok else out.strip()[-200:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
