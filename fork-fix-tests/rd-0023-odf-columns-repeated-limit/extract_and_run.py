#!/usr/bin/env python3
"""
RD-0023 (our corpus run, no upstream issue): an ODF table whose column or cell
has table:number-columns-repeated="-1" (or any huge count) made x2t allocate
without bound - a 2.8 KB file took the release x2t past 1.5 GB in about 4 s,
and it ran on until the machine was out of memory.

Found on LibreOffice's sw/qa/core/data/odt/fail/tdf102018.odt (a sheet with
<table:table-column table:number-columns-repeated="-1"/>); a generated ODT text
table or ODS sheet with that column does the same (odt -> docx and ods -> xlsx).

Cause: the attribute is read into an unsigned int, so "-1" is 4294967295, and
the converters loop over the count before checking anything:
docx_table_state::start_column / xlsx_table_state::start_column push one
string per column, table_table_column::docx_convert one width per column, the
cell converters one cell per repeat. Fix: table_table_column_attlist and
table_table_cell_attlist (OdfFile/Reader/Format/table.cpp) clamp the count to
16384, the most columns a sheet can have; smaller counts are unchanged.

What runs: the REAL bodies of table_table_cell_attlist::add_attributes and
table_table_column_attlist::add_attributes (brace-matched; git show BASE_REF:...
with BASELINE=1) with CP_APPLY_ATTR replaced by a stand-in that parses the
attribute the way boost::lexical_cast<unsigned int> does ("-1" -> 4294967295)
and leaves other attributes alone. Cases per attlist: "-1", "4294967295" and
"99999" give 16384; "1024", "16384" and an absent attribute (1) are unchanged.
NOT claimed: number-rows-repeated (other code paths with their own limits).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read table.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0023 commit
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'ae54ea08c1^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OdfFile/Reader/Format/table.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def body(src, sig):
    a = src.find(sig)
    if a < 0:
        sys.exit(sig + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0; s = i
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[s:i + 1]
        i += 1


DRIVER = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
static const char* g_rep;   /* value of table:number-columns-repeated, or NULL */
static void apply(const wchar_t* name, unsigned int& v, unsigned int def) {
    v = def;
    if (g_rep && wcscmp(name, L"table:number-columns-repeated") == 0)
        v = (unsigned int)strtoll(g_rep, NULL, 10);   /* lexical_cast<unsigned>("-1") == 4294967295 */
}
template <class A, class B> static void apply(const wchar_t*, A&, B) {}
template <class A> static void apply(const wchar_t*, A&) {}
#define CP_APPLY_ATTR(...) apply(__VA_ARGS__)
struct Common { void add_attributes(int) {} };
struct Vis { enum { Visible }; Vis(int) {} };
typedef Vis table_visibility;
struct Cell { unsigned int table_number_columns_repeated_; int table_style_name_, table_content_validation_name_, table_formula_;
    bool table_protect_; Common common_value_and_type_attlist_;
    void add_attributes(int Attributes) @@CELL@@ };
struct Col { unsigned int table_number_columns_repeated_; int table_style_name_, table_visibility_, table_default_cell_style_name_;
    void add_attributes(int Attributes) @@COL@@ };
int main(int argc, char** argv) {
    g_rep = strcmp(argv[1], "none") ? argv[1] : NULL;
    Cell c; c.add_attributes(0); Col k; k.add_attributes(0);
    printf("cell=%u column=%u\n", c.table_number_columns_repeated_, k.table_number_columns_repeated_);
    return 0;
}
'''

CASES = [('-1', 16384), ('4294967295', 16384), ('99999', 16384), ('1024', 1024), ('16384', 16384), ('none', 1)]


def main():
    src = read(REL)
    cell = body(src, 'void table_table_cell_attlist::add_attributes(')
    col = body(src, 'void table_table_column_attlist::add_attributes(')
    work = tempfile.mkdtemp(prefix='rd0023-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CELL@@', cell).replace('@@COL@@', col))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True)
        out = r.stdout.strip()
        ok = r.returncode == 0 and out == 'cell=%d column=%d' % (want, want)
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + 'number-columns-repeated=%s -> %d (%s): %s' % (
            arg, want, 'baseline ' + BASE_REF if BASELINE else 'working tree', out or 'rc=%d' % r.returncode))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
