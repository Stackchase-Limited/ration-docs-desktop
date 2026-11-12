#!/usr/bin/env python3
"""
RD-0027 (our corpus run, no upstream issue): a .doc whose FIB counts more
main-document characters (ccpText) than the file's text holds kept x2t
converting the same table over and over - LibreOffice's sw/qa/core/data/ww8/
pass/hang-8.doc (ccpText 6442, 195 characters of text) ran the release x2t for
over 120 s without finishing (once RD-0026 stops it crashing earlier).

Cause: MainDocumentMapping::Apply (MsBinaryFile/DocFile/MainDocumentMapping.cpp)
walks cp from 0 to ccpText. Past the end of WordDocument::Text the paragraph
lookup still finds a table PAPX, so each cp builds a Table that converts its rows
again and ends back at the end of the real text; the loop advances one character
per full table conversion. The header/footer mappings already stop at
Text->size(). Fix: the main-text loop's bound (countText, and countTextRel = its
last cp) is the smaller of ccpText and Text->size().

What runs: the REAL statements of MainDocumentMapping::Apply from
"int countText" up to the main "while (cp < countText" loop (git show
BASE_REF:... with BASELINE=1) inside a stand-in document (FIB ccpText, Text
vector), printing the two bounds. Cases: ccpText 6442 with 195 characters of
text (bounds 195/194), ccpText equal to the text (unchanged), and ccpText
smaller than the text - the usual case, main text followed by footnotes,
headers... (unchanged, ccpText wins).
NOT claimed: the speed of Table conversion itself.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read MainDocumentMapping.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0027 commit
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'bf8072c917^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/DocFile/MainDocumentMapping.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <cstdlib>
#include <vector>
struct RgLw97 { int ccpText; };
struct FIB_ { RgLw97 m_RgLw97; };
struct Doc { FIB_* FIB; std::vector<wchar_t>* Text; };
int main(int argc, char** argv) {
    FIB_ fib; fib.m_RgLw97.ccpText = atoi(argv[1]);
    std::vector<wchar_t> text(atoi(argv[2]), L'a');
    Doc d; d.FIB = &fib; d.Text = &text; Doc* m_document = &d;
@@FRAGMENT@@
    printf("countText=%d countTextRel=%d\n", countText, countTextRel);
    return 0;
}
'''

CASES = [('6442', '195', 'FIB counts past the text (hang-8.doc)', 'countText=195 countTextRel=194'),
         ('195', '195', 'FIB count equals the text (unchanged)', 'countText=195 countTextRel=194'),
         ('100', '195', 'main text followed by other stories (unchanged)', 'countText=100 countTextRel=99')]


def main():
    src = read(REL)
    a = src.find('int countText')
    b = src.find('while (cp < countText', a)
    if a < 0 or b < 0:
        sys.exit('main text bounds not found - the extractor needs updating')
    work = tempfile.mkdtemp(prefix='rd0027-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FRAGMENT@@', src[a:b]))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for ccp, n, name, want in CASES:
        r = subprocess.run([exe, ccp, n], capture_output=True, text=True)
        out = r.stdout.strip()
        ok = r.returncode == 0 and out == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree', out or 'rc=%d' % r.returncode))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
