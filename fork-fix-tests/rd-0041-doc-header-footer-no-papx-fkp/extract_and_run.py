#!/usr/bin/env python3
"""
RD-0041 (our corpus run, no upstream issue): a .doc with no paragraph FKPs
crashed x2t when it converted a header, footer or text box (SIGSEGV in
FooterMapping::Apply, FooterMapping.cpp:62) - LibreOffice's
sw/qa/core/data/ww8/pass/ofz57592-1.doc.

Cause: HeaderMapping::Apply, FooterMapping::Apply and TextboxMapping::Apply
(MsBinaryFile/DocFile/) started with
    _lastValidPapx = (*(m_document->AllPapxFkps->begin()))->grppapx[0];
which dereferences begin() of an empty vector (no PAPX bin table entries) and
reads grppapx[0] of an FKP holding no PAPX. MainDocumentMapping::Apply already
guards the same lookup. Fix: the first FKP's first PAPX is taken only when both
exist; otherwise the story starts from NULL, as the main text does.

What runs: the REAL statement(s) that set _lastValidPapx in each of the three
Apply functions (extracted from the first "_lastValidPapx" to the end of its
statement, plus the guarding if-block in the fixed code; git show BASE_REF:...
with BASELINE=1), compiled with -fsanitize=address inside a stand-in document.
Cases per file: no FKPs (must give NULL, no crash), one FKP with no PAPX (NULL),
and one FKP with two PAPXs (the first, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the three files at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0041 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '53d1c57de2^')
BASELINE = bool(os.environ.get('BASELINE'))
FILES = ['MsBinaryFile/DocFile/HeaderMapping.cpp', 'MsBinaryFile/DocFile/FooterMapping.cpp',
         'MsBinaryFile/DocFile/TextboxMapping.cpp']


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def fragment(src, rel):
    a = src.find('_lastValidPapx')
    if a < 0:
        sys.exit('_lastValidPapx not found in %s - the extractor needs updating' % rel)
    end = src.find(';', a) + 1
    if 'NULL' in src[a:end]:
        # fixed shape: "_lastValidPapx = NULL;" followed by the guarded if-block
        i = src.find('{', end); depth = 0
        while True:
            if src[i] == '{': depth += 1
            elif src[i] == '}':
                depth -= 1
                if depth == 0: break
            i += 1
        end = i + 1
    return src[a:end]


DRIVER = r'''
#include <cstdio>
#include <vector>
struct ParagraphPropertyExceptions { int id; };
struct FormattedDiskPagePAPX { unsigned int grppapxSize; ParagraphPropertyExceptions** grppapx; };
struct Doc { std::vector<FormattedDiskPagePAPX*>* AllPapxFkps; };
int main(int argc, char** argv) {
    std::vector<FormattedDiskPagePAPX*> fkps;
    ParagraphPropertyExceptions a = {1}, b = {2};
    FormattedDiskPagePAPX fkp;
    if (argv[1][0] == 'e') { fkp.grppapxSize = 0; fkp.grppapx = new ParagraphPropertyExceptions*[0]; fkps.push_back(&fkp); }
    else if (argv[1][0] == 'v') { fkp.grppapxSize = 2; fkp.grppapx = new ParagraphPropertyExceptions*[2]; fkp.grppapx[0] = &a; fkp.grppapx[1] = &b; fkps.push_back(&fkp); }
    Doc d; d.AllPapxFkps = &fkps; Doc* m_document = &d;
    ParagraphPropertyExceptions* _lastValidPapx = (ParagraphPropertyExceptions*)&b;
@@FRAGMENT@@
    printf("papx=%d\n", _lastValidPapx ? _lastValidPapx->id : 0);
    return 0;
}
'''

CASES = [('n', 'no paragraph FKPs', 'papx=0'),
         ('e', 'first FKP holds no PAPX', 'papx=0'),
         ('v', 'first FKP holds two PAPXs (unchanged)', 'papx=1')]


def main():
    work = tempfile.mkdtemp(prefix='rd0041-')
    fails = 0
    for rel in FILES:
        frag = fragment(read(rel), rel)
        p = os.path.join(work, os.path.basename(rel) + '.cpp')
        open(p, 'w').write(DRIVER.replace('@@FRAGMENT@@', frag))
        exe = p[:-4]
        r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit('build failed:\n' + r.stderr[-3000:])
        for arg, name, want in CASES:
            r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
            m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
            ok = r.returncode == 0 and not m and r.stdout.strip() == want
            fails += not ok
            print(('ok   ' if ok else 'FAIL ') + '%s, %s (%s): %s' % (
                os.path.basename(rel), name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
                ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
