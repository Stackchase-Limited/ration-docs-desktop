#!/usr/bin/env python3
"""
RD-0045 (found while checking the RD-0040..0049 fixes against normal files, no
upstream issue): Apache POI's test-data/document/Bug50955.doc converted with an
(empty) header in 5 of 8 runs of the unchanged x2t and without one in the
others. ASan: heap-buffer-overflow in HeaderAndFooterTable::HeaderAndFooterTable
(MsBinaryFile/DocFile/HeaderAndFooterTable.cpp:105/111).

Cause: the PlcfHdd is read into table[tableSize] and each story runs from
table[pos] to table[pos + 1]. With pos starting at 6 (Word 97 / complex files),
"count = (tableSize - pos - 1) / 6" is unsigned arithmetic, so a
PlcfHdd of fewer than 7 CPs gives a huge count; the loop then read table[6] and
table[7] past the array, and whatever the heap held there decided whether a
header range was made. The "pos >= tableSize" check came only after the read.
Fix: an entry is read only while table[pos + 1] exists.

What runs: the REAL HeaderAndFooterTable(FileInformationBlock*, POLE::Stream*)
constructor (brace-matched; git show BASE_REF:... with BASELINE=1), compiled with
-fsanitize=address, with stand-in FIB / VirtualStreamReader (ints from an
array) / CharacterRange. Cases: a 6-CP PlcfHdd (Word 97: no story fits, nothing
must be read past it), and a 13-CP one with one odd header and one odd footer
(unchanged: 6 entries per kind in total, 2 of them ranges).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read HeaderAndFooterTable.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0045 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '1fb37219ba^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/DocFile/HeaderAndFooterTable.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig):
    a = src.find(sig)
    if a < 0:
        sys.exit(sig + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


DRIVER = r'''
#include <cstdio>
#include <cstdlib>
#include <vector>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
namespace POLE { struct Stream { std::vector<int> v; }; }
namespace DocFileFormat {
struct FibWord97 { unsigned int fcPlcfHdd, lcbPlcfHdd; }; struct RgLw97 { int ccpText, ccpFtn, ccpHdr; }; struct FibBase { bool fComplex; };
struct FileInformationBlock { FibWord97 m_FibWord97; RgLw97 m_RgLw97; FibBase m_FibBase; int m_nWordVersion; };
struct VirtualStreamReader { POLE::Stream* s; size_t i; VirtualStreamReader(POLE::Stream* st, unsigned int, int) : s(st), i(0) {}
  unsigned long GetSize() const { return 1000; } int ReadInt32() { return i < s->v.size() ? s->v[i++] : (i++, 0); } };
struct CharacterRange { int cp, ccp; CharacterRange(int a, int b) : cp(a), ccp(b) {} };
struct HeaderAndFooterTable { size_t m_nCurrentIndex; std::vector<CharacterRange*> m_arCommonHeadersFooters, m_arFirstHeaders, m_arEvenHeaders,
  m_arOddHeaders, m_arFirstFooters, m_arEvenFooters, m_arOddFooters; HeaderAndFooterTable(FileInformationBlock* fib, POLE::Stream* pTableStream); };
@@CTOR@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
  POLE::Stream s; FileInformationBlock fib = {}; fib.m_nWordVersion = 0; fib.m_RgLw97.ccpHdr = 40;
  if (argv[1][0] == 's') { for (int i = 0; i < 6; i++) s.v.push_back(0); }
  else { int cps[] = {0,0,0,0,0,0, 0,0,10,10,20,20, 20}; s.v.assign(cps, cps + 13); }   // even hdr, odd hdr [0,10), even ftr, odd ftr [10,20), first hdr, first ftr
  fib.m_FibWord97.lcbPlcfHdd = (unsigned int)s.v.size() * 4;
  HeaderAndFooterTable t(&fib, &s);
  std::vector<CharacterRange*>* all[] = { &t.m_arEvenHeaders, &t.m_arOddHeaders, &t.m_arEvenFooters, &t.m_arOddFooters, &t.m_arFirstHeaders, &t.m_arFirstFooters };
  int n = 0, ranges = 0; for (int k = 0; k < 6; k++) for (size_t j = 0; j < all[k]->size(); j++) { n++; if (all[k]->at(j)) ranges++; }
  printf("entries=%d ranges=%d\n", n, ranges); return 0;
}
'''

CASES = [('s', 'PlcfHdd of 6 CPs (Word 97)', 'entries=0 ranges=0'),
         ('n', 'PlcfHdd of 13 CPs, odd header and footer (unchanged)', 'entries=6 ranges=2')]


def main():
    ctor = func(read(REL), 'HeaderAndFooterTable::HeaderAndFooterTable (FileInformationBlock* fib')
    work = tempfile.mkdtemp(prefix='rd0045-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CTOR@@', ctor))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
            ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
