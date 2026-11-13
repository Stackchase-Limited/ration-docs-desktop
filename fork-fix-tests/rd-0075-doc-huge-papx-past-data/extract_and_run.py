#!/usr/bin/env python3
"""
RD-0075 (our ASan corpus run, no upstream issue): a .doc paragraph whose huge
PAPX (sprmPHugePapx) or table row whose sprmPTableProps points at a grpprl
running past the end of the Data stream made x2t read past its buffer
(heap-buffer-overflow READ in PropertyExceptions::ReadExceptions, from
ParagraphPropertyExceptions / TablePropertyExceptions) - LibreOffice
sw/qa/core/data/ww8/pass/ofz38011-1.doc and ofz18414-1.doc.

Cause (MsBinaryFile/DocFile/ParagraphPropertyExceptions.cpp and
TablePropertyExceptions.cpp): the grpprl was read with
VirtualStreamReader::ReadBytes(size), which stops at the end of the stream and
allocates only what it read, and parsed with the size from the file; the
2-byte size was also decoded as if both bytes had been read.
Fix: decode and parse only the bytes actually read.

What runs: the REAL statements of both branches (ParagraphPropertyExceptions:
the `if( (iter->OpCode == sprmPHugePapx ) ...` block; TablePropertyExceptions:
the `else if (oSpmIter->OpCode == sprmPTableProps)` block) with the REAL
VirtualStreamReader readers, compiled with -fsanitize=address;
PropertyExceptions is a stand-in that reads every byte it is given, as
ReadExceptions may. Data stream: grpprl size 300 at the offset, 5 bytes after
it; and a complete 5-byte grpprl. Passes when ASan reports nothing and 5
bytes are parsed in every case.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0075 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '07ae492180^')
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
#define TRUE 1
enum OperationCode { sprmPHugePapx = 0x6645, sprmPTableProps = 0x646B, sprmTDefTableShd = 1, sprmTDefTableShd2nd = 2, sprmTDefTableShd3rd = 3 };
enum SprmType { PAP = 1, TAP = 5 };
struct SinglePropertyModifier { OperationCode OpCode; SprmType Type; unsigned char* Arguments; unsigned int argumentsSize; };
static int parsed = -1;
struct PropertyExceptions { std::vector<SinglePropertyModifier>* grpprl;
  PropertyExceptions(unsigned char* b, int size, int) : grpprl(new std::vector<SinglePropertyModifier>()) { touch(b, size); parsed = size; }
  ~PropertyExceptions() { delete grpprl; } };
int main(int argc, char** argv) {
  bool full = argv[1][1] == 'f';
  POLE::Stream data; data.d.assign(8, 0); unsigned short sz = full ? 5 : 300;
  data.d.push_back(sz & 0xFF); data.d.push_back(sz >> 8); for (int i = 0; i < 5; i++) data.d.push_back(0x22);
  POLE::Stream* dataStream = &data; int nWordVersion = 0;
  unsigned char fc[4] = {8, 0, 0, 0};
  std::vector<SinglePropertyModifier>* grpprl = new std::vector<SinglePropertyModifier>();
  if (argv[1][0] == 'p') {
    grpprl->push_back(SinglePropertyModifier{ sprmPHugePapx, PAP, fc, 4 });
    unsigned char padbyte = 0; VirtualStreamReader *reader = NULL;
    for ( std::vector<SinglePropertyModifier>::iterator iter = grpprl->begin(); iter != grpprl->end(); iter++ )
    {
@@PAPX@@
    }
  } else {
    SinglePropertyModifier m{ sprmPTableProps, PAP, fc, 4 }; std::vector<SinglePropertyModifier>::iterator oSpmIter; std::vector<SinglePropertyModifier> one(1, m);
    oSpmIter = one.begin(); VirtualStreamReader oBinReader(dataStream, 0, nWordVersion); int m_bSkipShading97 = 0;
    if (false) {}
@@TAPX@@
  }
  printf("parsed=%d\n", parsed); return 0;
}
"""


def main():
    px = read(D + 'ParagraphPropertyExceptions.cpp')
    papx = func(px, 'if( (iter->OpCode == sprmPHugePapx )')
    tx = read(D + 'TablePropertyExceptions.cpp')
    a = tx.find('else if (oSpmIter->OpCode == sprmPTableProps)')
    if a < 0:
        sys.exit('sprmPTableProps branch not found - the extractor needs updating')
    tapx = func(tx, 'else if (oSpmIter->OpCode == sprmPTableProps)')
    fails = build_run(DRIVER.replace('@@PAPX@@', papx).replace('@@TAPX@@', tapx),
                      [('ps', 'huge PAPX grpprl of 300 bytes, 5 left in the Data stream', 'parsed=5'),
                       ('pf', 'huge PAPX complete 5-byte grpprl (unchanged)', 'parsed=5'),
                       ('ts', 'table properties grpprl of 300 bytes, 5 left in the Data stream', 'parsed=5'),
                       ('tf', 'table properties complete 5-byte grpprl (unchanged)', 'parsed=5')], 'rd0075')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
