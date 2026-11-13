#!/usr/bin/env python3
"""
RD-0073 (our ASan corpus run, no upstream issue): a .doc string-table entry
(STTBF: bookmark names, authors, ...) running past the end of its stream made
x2t convert memory past the buffer and die with SIGBUS (ASan: BUS in
NSFile::CUtf8Converter::GetWStringFromUTF16 from WideString::ConstructObject /
StringTable<WideString>::parse) - LibreOffice sw/qa/core/data/ww8/pass/
ofz18534-1.doc.

Cause (MsBinaryFile/DocFile/WideString.cpp): ConstructObject read the entry
with VirtualStreamReader::ReadBytes(length), which stops at the end of the
stream and allocates only what it read, then converted `length` bytes.
Fix: convert only the bytes actually read.

What runs: the REAL WideString::ConstructObject and the REAL
VirtualStreamReader::ReadBytes/GetPosition, compiled with -fsanitize=address;
FormatUtils::GetWStringFromBytes is a stand-in that reads every byte it is
told to. Passes when ASan reports nothing and the string has the bytes the
stream held (Word 97 entry of 40 bytes with 6 left -> 6; complete entry
unchanged; same in Word 6 mode).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0073 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '9a120ed6d4^')
BASELINE = bool(os.environ.get('BASELINE'))
D = 'MsBinaryFile/DocFile/'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig, frm=0):
    a = src.find(sig, frm)
    if a < 0:
        sys.exit(sig + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


# Stand-ins: a POLE stream over a byte vector; the REAL VirtualStreamReader methods are pasted in.
# touch() reads every byte a parser is told it may read - what PropertyExceptions::ReadExceptions /
# GetWStringFromUTF16 do - so ASan reports a size larger than the buffer.
COMMON = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
typedef unsigned int _UINT32; typedef unsigned long ULONG;
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos = 0;
    uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos);
      if (k) memcpy(o, &d[pos], (size_t)k); pos += k; return k; } }; }
static volatile unsigned sink;
static void touch(const unsigned char* b, long n) { for (long i = 0; i < n; i++) sink += b[i]; }
namespace DocFileFormat { struct FormatUtils {
  static unsigned char BytesToUChar(const unsigned char* b, unsigned int s, unsigned int l) { return (!b || s >= l) ? 0 : b[s]; }
  static short BytesToInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; short v; memcpy(&v, b + s, 2); return v; }
  static unsigned short BytesToUInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; unsigned short v; memcpy(&v, b + s, 2); return v; }
  static _UINT32 BytesToUInt32(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 3 >= l) return 0; _UINT32 v; memcpy(&v, b + s, 4); return v; }
  static std::wstring IntToWideString(int v) { return std::to_wstring(v); }
  static std::wstring MapValueToWideString(int v, const wchar_t*, int, int) { return std::to_wstring(v); }
  static bool GetWStringFromBytes(std::wstring& r, const unsigned char* b, int n, int) { touch(b, n); r.assign(n > 0 ? n : 0, L'x'); return true; } }; }
class VirtualStreamReader { public:
  int nWordVersion; POLE::Stream* stream; POLE::uint64 position;
  VirtualStreamReader(POLE::Stream* s, ULONG p, int v) : nWordVersion(v), stream(s), position(p) {}
  unsigned char* ReadBytes(unsigned int count, bool isResultNeeded);
  unsigned long GetPosition() const; short ReadInt16(); unsigned char ReadByte(); int Seek(int offset, int origin); };
@@READERS@@
using namespace DocFileFormat;
"""


def readers():
    vsr = read(D + 'VirtualStreamReader.cpp')
    return '\n'.join(func(vsr, s) for s in ['unsigned char* VirtualStreamReader::ReadBytes',
                                             'unsigned long VirtualStreamReader::GetPosition',
                                             'short VirtualStreamReader::ReadInt16',
                                             'unsigned char VirtualStreamReader::ReadByte',
                                             'int VirtualStreamReader::Seek'])


def build_run(code, cases, tag):
    work = tempfile.mkdtemp(prefix=tag + '-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(COMMON.replace('@@READERS@@', readers()) + code)
    exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    return fails

DRIVER = r"""
#define ENCODING_WINDOWS_1250 1250
#define ENCODING_UTF16 1200
namespace DocFileFormat {
struct ByteStructure { virtual ~ByteStructure() {} };
struct WideString : public ByteStructure, public std::wstring { ByteStructure* ConstructObject(VirtualStreamReader* reader, int length); };
@@CTOR@@
}
int main(int argc, char** argv) {
  POLE::Stream s; s.d.assign(6, 0x41);
  VirtualStreamReader r(&s, 0, argv[1][0] == '6' ? 1 : 0);
  int length = atoi(argv[1] + 1);
  WideString* w = static_cast<WideString*>(WideString().ConstructObject(&r, length));
  printf("chars=%d\n", (int)w->size()); return 0;
}
"""


def main():
    ctor = func(read(D + 'WideString.cpp'), 'ByteStructure* WideString::ConstructObject')
    fails = build_run(DRIVER.replace('@@CTOR@@', ctor),
                      [('940', 'Word 97 entry of 40 bytes, 6 in the stream', 'chars=6'),
                       ('96', 'Word 97 complete 6-byte entry (unchanged)', 'chars=6'),
                       ('640', 'Word 6 entry of 40 bytes, 6 in the stream', 'chars=6')], 'rd0073')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
