#!/usr/bin/env python3
"""
RD-0022 (our corpus run, no upstream issue): saving as ODT a document with a
content control (w:sdt date/text/rich text/check box) in a paragraph where no
font size is set crashed x2t (SIGSEGV at 0xfffffffffffffff8).

Found on LibreOffice's sw/qa/core/data/odt/pass/tdf112123.odt (1.6 KB): it opens
(odt -> docx) fine, but saving that docx back as ODT kills the release x2t in
Oox2Odf::DocxConverter::convert(OOX::Logic::CSdt*)
(OdfFile/Writer/Converter/DocxConverter.cpp, the "if (!width)" block).

Cause: the control's width is computed from the text length and the current
font size, read as current_font_size.back(); that stack is only filled when a
paragraph, run or style sets a size, so with none in scope back() read before
the start of an empty vector. Fix: an empty stack falls back to 12 pt (the
default MathConverter.cpp already uses for the same vector).

What runs: the REAL "if (!width) { ... }" block of DocxConverter::convert(CSdt*)
(git show BASE_REF:... with BASELINE=1) compiled with -fsanitize=address inside
stand-ins for the odf context / drawing context / optional<double>. Cases: no
font size on the stack (must not crash; control gets a size) and 10 pt on the
stack (metrics asked for 10 pt, as before). Passes when ASan reports nothing.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read DocxConverter.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0022 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'c8b4a69f59^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OdfFile/Writer/Converter/DocxConverter.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <string>
#include <utility>
#include <vector>
struct optd { bool has; double v; optd() : has(false), v(0) {} optd& operator=(double x) { has = true; v = x; return *this; }
    bool operator!() const { return !has; } };
struct Drawing { double w, h; void set_size(optd& a, optd& b, bool) { w = a.v; h = b.v; } };
struct OdtCtx { Drawing d; Drawing* drawing_context() { return &d; } };
struct OdfCtx { double asked; OdfCtx() : asked(-1) {}
    void calculate_font_metrix(const std::wstring&, double size, bool, bool, bool) { asked = size; }
    std::pair<double, double> font_metrix() { return std::make_pair(asked / 2, asked); } };
struct Conv {
    std::vector<double> current_font_size; OdfCtx oc; OdtCtx tc; OdtCtx* odt_context;
    OdfCtx* odf_context() { return &oc; }
    void run() { odt_context = &tc; std::wstring value = L"2017-09-01"; optd width, height;
@@FRAGMENT@@
        printf("asked=%g w=%g\n", oc.asked, tc.d.w); }
};
int main(int argc, char** argv) {
    Conv c; if (argv[1][0] == 's') c.current_font_size.push_back(10);
    c.run(); return 0;
}
'''

CASES = [('e', 'no font size in scope', 'asked=12 w=60'),
         ('s', '10 pt in scope (unchanged)', 'asked=10 w=50')]


def main():
    src = read(REL)
    a = src.find('void DocxConverter::convert(OOX::Logic::CSdt *oox_sdt)')
    a = src.find('if (!width)', a)
    if a < 0:
        sys.exit('sdt sizing block not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: break
        i += 1
    work = tempfile.mkdtemp(prefix='rd0022-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FRAGMENT@@', src[a:i + 1]))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + 'content control sized, %s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
            ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
