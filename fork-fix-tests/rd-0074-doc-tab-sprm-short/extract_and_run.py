#!/usr/bin/env python3
"""
RD-0074 (our ASan corpus run, no upstream issue): a .doc tab-stop sprm
(sprmPChgTabs / sprmPChgTabsPapx / sprmOldPChgTabs) whose operand is shorter
than its tab counts made x2t read past the operand (heap-buffer-overflow READ
in ParagraphPropertiesMapping::Apply, from NumberingMapping::LevelMapping) -
POI's clusterfuzz-testcase-POIHWPFFuzzer-5696094627495936.doc.

Cause (MsBinaryFile/DocFile/ParagraphPropertiesMapping.cpp): the TBD byte of
each added tab was read as Arguments[pos + itbdAddMax * 2 + i] without a bound
(the positions were already read through bounds-checked BytesToInt16), and
itbdDelMax as Arguments[0] even for an empty operand.
Fix: stop at the end of the operand; an empty operand has no deleted tabs.

What runs: the REAL case body (the block after "case sprmPChgTabs:") lifted
out of ParagraphPropertiesMapping.cpp with stand-ins for the XML writer
classes, TabDescriptor and the sprm, compiled with -fsanitize=address, on the
operand of the POI file shape (5 bytes: 0 deleted, 2 added tabs, positions,
no TBD bytes) and on a complete operand. Passes when ASan reports nothing and
the complete operand still gives its 2 tabs.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0074 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'a733a82513^')
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
namespace XMLTools {
  struct XMLAttribute { XMLAttribute(const std::wstring&, const std::wstring&) {} };
  struct XMLElement { int n = 0; XMLElement(const std::wstring&) {} void AppendAttribute(const XMLAttribute&) {} void AppendChild(const XMLElement&) { n++; } }; }
struct Global { static const wchar_t TabStop[7][8]; static const wchar_t TabLeader[8][11]; };
const wchar_t Global::TabStop[7][8] = {}; const wchar_t Global::TabLeader[8][11] = {};
struct TabDescriptor { unsigned char jc, tlc; TabDescriptor(unsigned char b) : jc(b & 7), tlc(b >> 3) {} };
enum OperationCode { sprmOldPChgTabs = 15, sprmPChgTabsPapx = 0xC60D, sprmPChgTabs = 0xC615 };
struct SinglePropertyModifier { OperationCode OpCode; unsigned char* Arguments; unsigned int argumentsSize; };
int main(int argc, char** argv) {
  bool full = argv[1][0] == 'f';
  unsigned int n = full ? 8 : 5;                     /* itbdDelMax, itbdAddMax, 2 x 2-byte positions, 2 TBDs */
  unsigned char* a = new unsigned char[n];
  a[0] = 0; a[1] = 2; a[2] = 0x10; a[3] = 0; a[4] = 0x20; if (full) { a[5] = 0; a[6] = 1; a[7] = 2; }
  SinglePropertyModifier m = { sprmPChgTabsPapx, a, n }; SinglePropertyModifier* iter = &m;
  XMLTools::XMLElement pPr(L"w:pPr"); XMLTools::XMLElement* _pPr = &pPr;
  {
@@CASE@@
  }
  printf("tabs=%d\n", pPr.n ? 1 : 0); delete[] a; return 0;
}
"""


def main():
    src = read(D + 'ParagraphPropertiesMapping.cpp')
    a = src.find('case sprmPChgTabs:')
    if a < 0:
        sys.exit('case sprmPChgTabs not found - the extractor needs updating')
    body = func(src, '{', a)
    fails = build_run(DRIVER.replace('@@CASE@@', body),
                      [('s', 'tab sprm of 5 bytes for 2 added tabs (no TBD bytes)', 'tabs=1'),
                       ('f', 'complete tab sprm (unchanged)', 'tabs=1')], 'rd0074')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
