#!/usr/bin/env python3
"""
RD-0080 (our crafted-input audit, no upstream issue): a .doc font table cut
short inside a font's panose made x2t read past its buffer - ASan
heap-buffer-overflow in FontTableMapping::Apply (panose loop) on a crafted POI
47304.doc whose font table ends 3 bytes into a panose.

Cause (MsBinaryFile/DocFile/FontFamilyName.cpp, ConstructObject): the 10-byte
panose and the names were read with VirtualStreamReader::ReadBytes, which stops
at the end of the stream and allocates only what it read, but panoseSize stayed
10 (and the names were converted with the length searchTerminationZero found,
which can count one byte past the end of the stream as the terminating zero).
Fix: panoseSize and the name lengths are the bytes read.

What runs: the REAL FontFamilyName::ConstructObject and searchTerminationZero
with the REAL VirtualStreamReader methods over a stand-in stream,
-fsanitize=address; the driver then reads panoseSize panose bytes as
FontTableMapping does. Cases: Word 97 font ending 3 bytes into the panose
(panose 3), complete "Arial" (panose 10, name of 6 with its zero, unchanged),
Word 6 font ending right after its header (name falls back to "font",
unchanged). NOT claimed: this test does not show the one-byte name over-read at
the very end of a stream (ASan did not flag the 0-byte buffer here).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0080 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '62ac577a75^')
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


D = 'MsBinaryFile/DocFile/'

# touch() reads every byte a converter is told it may read (what GetWStringFromUTF16 /
# GetWStringFromBytes / BorderCode do), so ASan reports a read past a short buffer.
DOC_COMMON = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <memory>
#include <algorithm>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
#define ENCODING_WINDOWS_1250 1250
typedef unsigned int _UINT32; typedef int _INT32; typedef unsigned long ULONG; typedef unsigned char BYTE;
typedef unsigned short UTF16;
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos = 0;
    uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos);
      if (k) memcpy(o, &d[pos], (size_t)k); pos += k; return k; } }; }
static volatile unsigned sink;
static void touch(const unsigned char* b, long n) { for (long i = 0; i < n; i++) sink += b[i]; }
static int g_last = -1; // length of the last ANSI conversion
namespace NSFile { struct CUtf8Converter { static std::wstring GetWStringFromUTF16(const unsigned short* p, long n) {
  touch((const unsigned char*)p, n * 2); return std::wstring(n > 0 ? n : 0, L'x'); } }; }
static std::wstring convertUtf16ToWString(const UTF16* p, int n) { touch((const unsigned char*)p, n * 2); return std::wstring(n > 0 ? n : 0, L'x'); }
namespace DocFileFormat { struct FormatUtils {
  static bool BitmaskToBool(int v, int m) { return (v & m) == m; }
  static int BitmaskToInt(int v, int m) { int r = v & m; while (m && !(m & 1)) { m >>= 1; r >>= 1; } return r; }
  static bool GetWStringFromBytes(std::wstring& r, unsigned char* b, int n, int) { if (!b) return false; g_last = n; touch(b, n); r.assign(n > 0 ? n : 0, L'x'); return true; } }; }
class VirtualStreamReader { public:
  int nWordVersion; POLE::Stream* stream; POLE::uint64 position;
  VirtualStreamReader(POLE::Stream* s, ULONG p, int v) : nWordVersion(v), stream(s), position(p) {}
  unsigned short ReadUInt16(); short ReadInt16(); int ReadInt32(); unsigned int ReadUInt32(); unsigned char ReadByte();
  unsigned char* ReadBytes(unsigned int count, bool isResultNeeded);
  unsigned long GetPosition() const; unsigned long GetSize() const; int Seek(int offset, int origin);
  std::wstring ReadLengthPrefixedUnicodeString(); std::wstring ReadLengthPrefixedAnsiString(unsigned int max_size); };
@@READERS@@
using namespace DocFileFormat;
static POLE::Stream S(const std::string& hex) { POLE::Stream s; for (size_t i = 0; i + 1 < hex.size(); i += 2) s.d.push_back((unsigned char)strtol(hex.substr(i, 2).c_str(), 0, 16)); return s; }
"""


def readers(extra=()):
    vsr = read(D + 'VirtualStreamReader.cpp')
    sigs = ['unsigned short VirtualStreamReader::ReadUInt16', 'short VirtualStreamReader::ReadInt16',
            'int VirtualStreamReader::ReadInt32', 'unsigned int VirtualStreamReader::ReadUInt32',
            'unsigned char VirtualStreamReader::ReadByte', 'unsigned char* VirtualStreamReader::ReadBytes',
            'unsigned long VirtualStreamReader::GetPosition', 'unsigned long VirtualStreamReader::GetSize',
            'int VirtualStreamReader::Seek'] + list(extra)
    return '\n'.join(func(vsr, s) for s in sigs)


def doc_code(body, extra=()):
    return DOC_COMMON.replace('@@READERS@@', readers(extra)) + body

def main():
    code = '\nnamespace DocFileFormat { struct ByteStructure { virtual ~ByteStructure() {} };\nstruct FontSignature { _UINT32 UnicodeSubsetBitfield0, UnicodeSubsetBitfield1, UnicodeSubsetBitfield2, UnicodeSubsetBitfield3, CodePageBitfield0, CodePageBitfield1; };\nstruct FontFamilyName : ByteStructure { bool fTrueType = false; unsigned char ff = 0; short wWeight = 0; unsigned char chs = 0, prq = 0;\n  unsigned char* panose = NULL; unsigned int panoseSize = 0; FontSignature fs = {}; std::wstring xszFtn, xszAlt;\n  ByteStructure* ConstructObject(VirtualStreamReader* reader, int length); long searchTerminationZero(VirtualStreamReader* reader, long length); };\n@@FN@@\n@@FN2@@ }\nint main(int argc, char** argv) {\n  std::string m = argv[1]; POLE::Stream s; int v = 0;\n  if (m == "cut") s = S("16" "9001" "00" "00" "020b06");\n  if (m == "ok") s = S("16" "9001" "00" "00" "020b0604020202020204" + std::string(48, \'0\') + "4100720069006100" "6c000000" "00");\n  if (m == "w6") { s = S("16" "9001" "00" "00"); v = 1; }\n  VirtualStreamReader r(&s, 0, v);\n  FontFamilyName* f = static_cast<FontFamilyName*>(FontFamilyName().ConstructObject(&r, 0x40));\n  touch(f->panose, f->panoseSize);\n  printf("panose=%u name=%d\\n", f->panoseSize, (int)f->xszFtn.size()); return 0;\n}\n'
    code = code.replace('@@FN@@', func(read(D + 'FontFamilyName.cpp'), 'ByteStructure* FontFamilyName::ConstructObject'))
    code = code.replace('@@FN2@@', func(read(D + 'FontFamilyName.cpp'), 'long FontFamilyName::searchTerminationZero'))
    fails = build_run(doc_code(code, ()), [('cut', 'Word 97, stream ends 3 bytes into the panose', 'panose=3 name=4'), ('ok', 'complete Word 97 font "Arial" (unchanged)', 'panose=10 name=6'), ('w6', 'Word 6, stream ends after the font header (unchanged)', 'panose=0 name=4')], 'rd0080')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
