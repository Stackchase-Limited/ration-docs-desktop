#!/usr/bin/env python3
"""
RD-0047 (our corpus run, no upstream issue): a .doc whose PAPX/CHPX bin table
length runs past the table stream made x2t read wild memory or allocate
gigabytes. Apache POI's clusterfuzz-testcase-minimized-POIHWPFFuzzer-
5440721166139392.doc died with SIGBUS (ASan: heap-buffer-overflow in
FormattedDiskPagePAPX::GetAllPAPXFKPs, FormattedDiskPagePAPX.cpp:245);
LibreOffice's sw/qa/core/data/ww6/pass/crash-4.doc allocated 2 GB there.

Cause: GetAllPAPXFKPs and GetAllCHPXFKPs (MsBinaryFile/DocFile/
FormattedDiskPage{PAPX,CHPX}.cpp) allocate lcbPlcfBte + 1 bytes and loop up to
lcbPlcfBte, straight from the FIB. 0xFFFFFFFF + 1 wraps to an empty buffer that
the loop reads for 4 GB; other huge values are allocated, and an FKP is built
for every 2 or 4 bytes of zeros past the stream.
Fix: the length is limited to what the table stream holds after fcPlcfBte.

What runs: the REAL static GetAllPAPXFKPs and GetAllCHPXFKPs (brace-matched;
git show BASE_REF:... with BASELINE=1), compiled with -fsanitize=address, with
a stand-in FIB, an in-memory POLE::Stream of 64 bytes and stand-in FKP
constructors that only count. Cases (Word 97 and Word 6 layout each):
lcbPlcfBte = 0xFFFFFFFF; lcbPlcfBte = 1,000,000 with 64 bytes in the stream (at
most as many FKPs as the 64 bytes describe); and a 12-byte table that fits
(1 FKP, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the two .cpp files at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0047 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'b371f1324f^')
BASELINE = bool(os.environ.get('BASELINE'))
D = 'MsBinaryFile/DocFile/'


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
#include <cstring>
#include <vector>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos; uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos); if (k) memcpy(o, &d[pos], (size_t)k); return k; } }; }
namespace DocFileFormat {
struct FormatUtils {
  static int BytesToInt32(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 3 >= l) return 0; int v; memcpy(&v, b + s, 4); return v; }
  static short BytesToInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; short v; memcpy(&v, b + s, 2); return v; } };
struct FibWord97 { unsigned int fcPlcfBtePapx, lcbPlcfBtePapx, fcPlcfBteChpx, lcbPlcfBteChpx; }; struct FibBase { bool fComplex; };
struct FileInformationBlock { FibWord97 m_FibWord97; FibBase m_FibBase; int m_nWordVersion; };
static long g_fkps = 0;
struct FormattedDiskPagePAPX { FormattedDiskPagePAPX(POLE::Stream*, int, POLE::Stream*, int, bool) { if (++g_fkps > 100000) { printf("fkps>100000\n"); exit(0); } }
  static std::vector<FormattedDiskPagePAPX*>* GetAllPAPXFKPs(FileInformationBlock* fib, POLE::Stream* wordStream, POLE::Stream* tableStream, POLE::Stream* dataStream); };
struct FormattedDiskPageCHPX { FormattedDiskPageCHPX(POLE::Stream*, int, int) { if (++g_fkps > 100000) { printf("fkps>100000\n"); exit(0); } }
  static std::vector<FormattedDiskPageCHPX*>* GetAllCHPXFKPs(FileInformationBlock* fib, POLE::Stream* wordStream, POLE::Stream* tableStream); };
@@PAPX@@
@@CHPX@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
  char kind = argv[1][0], ver = argv[1][1], len = argv[1][2];
  POLE::Stream t; t.pos = 0; t.d.assign(64, 0);
  FileInformationBlock fib = {}; fib.m_nWordVersion = ver == '6' ? 1 : 0; fib.m_FibBase.fComplex = false;
  unsigned int lcb = len == 'm' ? 0xFFFFFFFFu : len == 'b' ? 1000000u : (ver == '6' ? 14u : 12u);
  if (len == 'n') { int cps[] = {0, 100}; memcpy(&t.d[0], cps, 8); }
  fib.m_FibWord97.lcbPlcfBtePapx = fib.m_FibWord97.lcbPlcfBteChpx = lcb;
  size_t n = kind == 'p' ? FormattedDiskPagePAPX::GetAllPAPXFKPs(&fib, &t, &t, &t)->size() : FormattedDiskPageCHPX::GetAllCHPXFKPs(&fib, &t, &t)->size();
  printf("fkps=%zu\n", n); return 0;
}
'''


def main():
    papx = func(read(D + 'FormattedDiskPagePAPX.cpp'), 'std::vector<FormattedDiskPagePAPX*>* FormattedDiskPagePAPX::GetAllPAPXFKPs')
    chpx = func(read(D + 'FormattedDiskPageCHPX.cpp'), 'std::vector<FormattedDiskPageCHPX*>* FormattedDiskPageCHPX::GetAllCHPXFKPs')
    work = tempfile.mkdtemp(prefix='rd0047-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@PAPX@@', papx).replace('@@CHPX@@', chpx))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for kind in 'pc':
        for ver, vname in (('9', 'Word 97'), ('6', 'Word 6')):
            # 64 bytes of table stream hold at most 32 FKP numbers (2 bytes each in Word 6, 4 in Word 97)
            for ln, lname, check in (('m', 'lcb 0xFFFFFFFF', lambda n: n <= 32),
                                     ('b', 'lcb 1,000,000 with 64 bytes in the stream', lambda n: n <= 32),
                                     ('n', 'table that fits (unchanged)', lambda n: n == 1)):
                r = subprocess.run([exe, kind + ver + ln], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:allocator_may_return_null=1'))
                m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
                out = r.stdout.strip()
                mm = re.match(r'fkps=(\d+)$', out)
                ok = r.returncode == 0 and not m and mm is not None and check(int(mm.group(1)))
                fails += not ok
                print(('ok   ' if ok else 'FAIL ') + '%s %s, %s (%s): %s' % (
                    'PAPX' if kind == 'p' else 'CHPX', vname, lname, 'baseline ' + BASE_REF if BASELINE else 'working tree',
                    ('ASan ' + m.group(1)) if m else (out or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
