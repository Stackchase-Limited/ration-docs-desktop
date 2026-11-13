#!/usr/bin/env python3
"""
RD-0084 (our crafted-input audit, no upstream issue): a .ppt compressed
OLE/VBA storage record shorter than 4 bytes made x2t write past its buffer -
ASan heap-buffer-overflow WRITE of 320 bytes (memcpy in POLE::StreamIO::read)
from CRecordExObjStg::ReadFromStream / CPPTDocumentInfo::GetBinFromStg on a
crafted POI testPPT_oleWorkbook.ppt whose ExOleObjStg says RecLen 2.

Cause (MsBinaryFile/PptFile/Records/ExObjListContainer.cpp): RecLen bytes were
allocated, then for a compressed record (RecInstance 1) RecLen - 4 bytes were
read into them; RecLen < 4 wrapped, so POLE copied the rest of the stream into
the 0-3 byte buffer. Fix: such a record is skipped and no file name returned.

What runs: the REAL CRecordExObjStg::ReadFromStream, -fsanitize=address, with
stand-ins for the POLE stream (copies min(n, bytes left), like POLE, but stops
the test on a read over 1 GB - here RecLen - 4 wrapped to 2^64 - 2),
StreamUtils, NSZip::Decompress and CFileBinary. Cases: compressed record of
RecLen 2 followed by 300 bytes (no file), uncompressed RecLen 10 (10 bytes
written, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0084 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '22a2d5fd45^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig, frm=0):
    """sig ... its brace-matched body (the REAL code)."""
    a = src.find(sig, frm)
    if a < 0:
        sys.exit(repr(sig) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


def span(src, start, end, frm=0):
    """The statements from `start` up to (not including) `end` (the REAL code)."""
    a = src.find(start, frm)
    b = src.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        sys.exit(repr(start) + ' .. ' + repr(end) + ' not found - the extractor needs updating')
    return src[a:b]


def build_run(code, cases, tag):
    """Compile with ASan, run each (arg, label, expected stdout); print ok/FAIL; return #failures."""
    work = tempfile.mkdtemp(prefix=tag + '-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(code)
    exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True,
                           env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:alloc_dealloc_mismatch=0:allocator_may_return_null=1'))
        m = re.search(r'ERROR: AddressSanitizer: (out of memory|requested allocation size|[\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (r.stdout.strip() or r.stderr.strip()[-200:] or 'rc=%d' % r.returncode)))
    return fails


P = 'MsBinaryFile/PptFile/'

PPT_COMMON = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <algorithm>
typedef unsigned int _UINT32; typedef unsigned int UINT; typedef unsigned long ULONG; typedef unsigned char BYTE; typedef unsigned short WORD;
static volatile unsigned sink; static unsigned long long g_written = 0;
static void touch(const void* b, unsigned long long n) { for (unsigned long long i = 0; i < n; i++) sink += ((const unsigned char*)b)[i]; }
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos = 0;
    uint64 size() { return d.size(); } uint64 tell() { return pos; } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { if (n > (1ull << 30)) { printf("huge read of %llu bytes\n", n); exit(3); }
      uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos); if (k) memcpy(o, &d[pos], (size_t)k); pos += k; return k; } }; }
namespace StreamUtils { static _UINT32 ReadDWORD(POLE::Stream* s) { _UINT32 v = 0; s->read((unsigned char*)&v, 4); return v; }
  static void StreamSkip(long n, POLE::Stream* s) { s->seek(s->tell() + n); } }
namespace NSZip { static bool Decompress(const BYTE* src, const ULONG& n, BYTE* dst, ULONG& m) { ULONG k = n < m ? n : m; memcpy(dst, src, k); m = k; return true; } }
namespace NSFile { struct CFileBinary { bool CreateFileW(const std::wstring&) { return true; }
  void WriteFile(const BYTE* p, unsigned long long n) { if (n > (1ull << 30)) { printf("huge write of %llu bytes\n", n); exit(3); } touch(p, n); g_written += n; }
  void CloseFile() {} static bool Remove(const std::wstring&) { return true; } }; }
#define FILE_SEPARATOR_STR L"/"
struct SRecordHeader { BYTE RecVersion = 0; unsigned short RecInstance = 0; unsigned short RecType = 0; UINT RecLen = 0; };
"""


DRV = r"""
namespace PPT { struct CRecordExObjStg { SRecordHeader m_oHeader; std::wstring m_sFileName = L"obj.bin";
  void ReadFromStream(SRecordHeader& oHeader, POLE::Stream* pStream); };
@@FN@@ }
int main(int argc, char** argv) {
  std::string m = argv[1]; POLE::Stream s; s.d.assign(300, 0x41); SRecordHeader h;
  if (m == "short") { h.RecInstance = 1; h.RecLen = 2; } else { h.RecInstance = 0; h.RecLen = 10; }
  PPT::CRecordExObjStg o; o.ReadFromStream(h, &s);
  printf("name=%s written=%llu\n", o.m_sFileName.empty() ? "none" : "kept", g_written); return 0;
}
"""


def main():
    code = PPT_COMMON + DRV.replace('@@FN@@', func(read(P + 'Records/ExObjListContainer.cpp'), 'void CRecordExObjStg::ReadFromStream'))
    fails = build_run(code, [('short', 'compressed record of RecLen 2', 'name=none written=0'),
                             ('ok', 'uncompressed RecLen 10 (unchanged)', 'name=kept written=10')], 'rd0084')
    sys.exit(1 if fails else 0)



if __name__ == '__main__':
    main()
