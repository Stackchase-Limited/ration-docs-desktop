#!/usr/bin/env python3
"""
RD-0085 (our crafted-input audit, no upstream issue): a .ppt picture record
shorter than its blip header made x2t allocate, read and write ~4 GB - on a
crafted POI 41246-2.ppt whose first JPEG blip says RecLen 5, x2t passed 1.5 GB
RSS (killed by the harness).

Cause (MsBinaryFile/PptFile/Records/Drawing/ArtBlip.cpp,
CRecordOfficeArtBlip::ReadFromStream): for JPEG/PNG/DIB/TIFF blips it
allocated and wrote oHeader.RecLen - lOffset bytes (lOffset = the 17/33-byte
UID header); RecLen is unsigned, so a shorter record wrapped to ~4 GB.
Fix: a record shorter than its header produces no picture file.

What runs: the REAL tail of ReadFromStream, from "if (oMetaFile.m_bIsValid)"
to the end of the function, -fsanitize=address, with stand-ins for the
metafile buffer, CFileBinary, CBgraFrame and the POLE stream (which stops the
test on a read or write over 1 GB). Cases: JPEG blip of RecLen 5 with a
17-byte header (no picture), RecLen 40 (23 bytes written, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0085 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '99ffd2a161^')
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
#define RECORD_TYPE_ESCHER_BLIP_PICT 0xF01C
#define RECORD_TYPE_ESCHER_BLIP_JPEG 0xF01D
#define RECORD_TYPE_ESCHER_BLIP_PNG 0xF01E
#define RECORD_TYPE_ESCHER_BLIP_DIB 0xF01F
struct CMetaFileBuffer { bool m_bIsValid = false; std::wstring m_sExtension; void ToFile(NSFile::CFileBinary*) {} unsigned ToBuffer(unsigned char*& d) { d = NULL; return 0; } };
struct CBgraFrame { bool OpenFile(const std::wstring&) { return false; } void SaveFile(const std::wstring&, int) {} };
struct Decryptor { void Decrypt(char*, long, int) {} };
struct CommonInfo { std::wstring tempPath = L"/tmp"; };
struct Blip { CommonInfo* m_pCommonInfo; std::wstring m_fileName;
  void tail(SRecordHeader& oHeader, POLE::Stream* pStream, int lOffset) {
    CMetaFileBuffer oMetaFile; std::wstring sExt = L".jpg"; int nImagesCount = 0; Decryptor* pDecryptor = NULL;
@@SNIP@@
  } };
int main(int argc, char** argv) {
  std::string m = argv[1]; POLE::Stream s; s.d.assign(100, 0x42); SRecordHeader h; h.RecType = RECORD_TYPE_ESCHER_BLIP_JPEG; h.RecInstance = 0x46A;
  h.RecLen = m == "short" ? 5 : 40;
  CommonInfo ci; Blip b; b.m_pCommonInfo = &ci; b.tail(h, &s, 17);
  printf("picture=%s written=%llu\n", b.m_fileName.empty() ? "none" : "file", g_written); return 0;
}
"""


def main():
    src = read(P + 'Records/Drawing/ArtBlip.cpp')
    snip = span(src, 'if (oMetaFile.m_bIsValid)', 'CRecordBitmapBlip::CRecordBitmapBlip()').rstrip()
    if not snip.endswith('}'):
        sys.exit('end of ReadFromStream not found - the extractor needs updating')
    code = PPT_COMMON + DRV.replace('@@SNIP@@', snip[:-1])
    fails = build_run(code, [('short', 'JPEG blip RecLen 5, 17-byte header', 'picture=none written=0'),
                             ('ok', 'JPEG blip RecLen 40 (unchanged)', 'picture=file written=23')], 'rd0085')
    sys.exit(1 if fails else 0)



if __name__ == '__main__':
    main()
