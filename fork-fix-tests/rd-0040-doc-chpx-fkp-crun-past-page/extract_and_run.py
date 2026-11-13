#!/usr/bin/env python3
"""
RD-0040 (our corpus run, no upstream issue): a .doc character FKP claiming more
runs than its 512-byte page can hold crashed x2t (SIGSEGV at address 0 in
DocumentMapping::writeRun, chpx->Convert(rPr)).

Found on LibreOffice's sw/qa/core/data/ww8/pass/forcepoint50-grfanchor-1.doc and
Apache POI's clusterfuzz-testcase-minimized-POIHWPFFuzzer-5195207308541952.doc /
-6610789829836800.doc.

Cause: FormattedDiskPageCHPX's constructor (MsBinaryFile/DocFile/
FormattedDiskPageCHPX.cpp) reads crun from byte 511; the crun word offsets (rgb)
follow the crun+1 FCs, so for crun > 101 they lie past the page and the loop
broke off, leaving the remaining grpchpx[] entries NULL. WordDocument::
GetCharacterPropertyExceptions returns them as runs, and writeRun converts each.
Fix: an entry whose offset lies outside the page gets an empty CHPX, like an
entry with offset 0.

What runs: the REAL constructor FormattedDiskPageCHPX(POLE::Stream*, int, int)
(brace-matched; git show BASE_REF:... with BASELINE=1), compiled with
-fsanitize=address, over a generated 512-byte page in a stand-in POLE::Stream,
with stand-in FormatUtils / CharacterPropertyExceptions (which records the size
it was given). Cases: crun = 150 (every grpchpx slot must be set), and crun = 3
with one 2-byte CHPX and two offset-0 entries (unchanged: sizes 2, empty, empty).
NOT claimed: anything about how such a run is then formatted.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read FormattedDiskPageCHPX.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0040 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'be84a20320^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/DocFile/FormattedDiskPageCHPX.cpp'


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
#include <cstring>
#include <cstdlib>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
namespace POLE { struct Stream { unsigned char page[512];
    void seek(unsigned long long) {} unsigned long long read(unsigned char* d, unsigned long long n) { memcpy(d, page, (size_t)n); return n; } }; }
namespace DocFileFormat {
enum FKPType { Character, Paragraph };
struct FormatUtils { static int BytesToInt32(const unsigned char* b, unsigned int start, unsigned int length) {
    if (b == NULL || start + 3 >= length) return 0; int v; memcpy(&v, b + start, 4); return v; } };
struct CharacterPropertyExceptions { int size;
    CharacterPropertyExceptions() : size(-1) {}
    CharacterPropertyExceptions(unsigned char*, int cb, int) : size(cb) {} };
struct FormattedDiskPage { FKPType Type; POLE::Stream* WordStream; unsigned char crun; int* rgfc; unsigned int rgfcSize;
    FormattedDiskPage() : WordStream(NULL), crun(0), rgfc(NULL), rgfcSize(0) {} };
struct FormattedDiskPageCHPX : FormattedDiskPage { unsigned char* rgb; unsigned int grpchpxSize; CharacterPropertyExceptions** grpchpx;
    FormattedDiskPageCHPX(POLE::Stream* wordStream, int offset, int nWordVersion); };
@@CTOR@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
    POLE::Stream s; memset(s.page, 0, 512);
    if (argv[1][0] == 'b') s.page[511] = 150;                 // crun past what the page can index
    else { s.page[511] = 3; s.page[16] = 100; s.page[200] = 2; s.page[201] = 0x11; s.page[202] = 0x22; }  // rgb[0] -> CHPX of 2 bytes at 200
    FormattedDiskPageCHPX fkp(&s, 0, 0);
    int nulls = 0; char sizes[64] = "";
    for (unsigned int i = 0; i < fkp.grpchpxSize; i++) {
        if (!fkp.grpchpx[i]) nulls++;
        else if (i < 3) sprintf(sizes + strlen(sizes), "%d,", fkp.grpchpx[i]->size); }
    printf("crun=%u null=%d first=%s\n", fkp.grpchpxSize, nulls, sizes);
    return 0;
}
'''

CASES = [('b', 'crun 150: offsets past the page', 'crun=150 null=0 first=-1,-1,-1,'),
         ('n', 'crun 3, one CHPX and two empty (unchanged)', 'crun=3 null=0 first=2,-1,-1,')]


def main():
    src = read(REL)
    ctor = func(src, 'FormattedDiskPageCHPX::FormattedDiskPageCHPX(POLE::Stream* wordStream')
    ctor = ctor.replace('FormattedDiskPage(), ', '')  # stand-in base has a default constructor
    work = tempfile.mkdtemp(prefix='rd0040-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CTOR@@', ctor))
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
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
            ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
