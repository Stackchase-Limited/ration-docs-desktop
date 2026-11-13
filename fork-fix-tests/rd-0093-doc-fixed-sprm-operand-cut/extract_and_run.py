#!/usr/bin/env python3
"""
RD-0093 (our crafted-input audit, no upstream issue): a .doc fixed-size sprm
cut short at the end of its grpprl made x2t read past its operand. Crafted POI
59322.doc whose CHPX ends with "70 68 00" (sprmCCv with 1 of its 4 operand
bytes; cb lowered by 3): ASan heap-buffer-overflow READ in
CharacterPropertiesMapping::convertSprms (CharacterPropertiesMapping.cpp:338).

Cause: since RD-0043 the SinglePropertyModifier constructor
(MsBinaryFile/DocFile/SinglePropertyModifier.cpp) keeps only the operand bytes
present, but the mappings read fixed-size operands whole without looking at
argumentsSize (sprmCCv's 3 colour bytes, DateAndTime(Arguments, 4) for
sprmCDttmRMark, sprmTMerge's 2 bytes, ...).
Fix: a fixed-size operand ([MS-DOC] 2.2.5.1 spra sizes; the Word 95 table for
old files) cut short is zero-padded to its size; complete ones are unchanged.
A sprm with no operand byte at all is still not kept, as before.

What runs: the REAL SinglePropertyModifier.cpp and the REAL
PropertyExceptions::ReadExceptions with the REAL SinglePropertyModifier.h /
SPRMCodes.h, and the REAL "case sprmCCv:" block of CharacterPropertiesMapping
(boost::wformat / the colour element are stand-ins that print the bytes),
-fsanitize=address, a stand-in FormatUtils.
Cases: grpprls ending in sprmCCv with 1 and 2 operand bytes (before: over-read;
now padded: 110000 / 112200), a complete sprmCCv and a bold + complete sprmCCv
(unchanged), sprmCCv with no operand byte (unchanged: kept
as an empty sprmPIstd 0x4600 by the copy constructor, which no mapping reads).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0093 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'df565af111^')
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

PRE = r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <sstream>
#include <vector>
#include <algorithm>
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
#include "SinglePropertyModifier.h"
namespace boost { struct wformat { std::wstring s; wformat(const wchar_t*) {}
  wformat& operator%(unsigned char b) { wchar_t t[4]; swprintf(t, 4, L"%02x", b); s += t; return *this; } };
  inline std::wostream& operator<<(std::wostream& o, const wformat& f) { return o << f.s; } }
namespace DocFileFormat {
struct FormatUtils {
  static unsigned char BytesToUChar(const unsigned char* b, unsigned int s, unsigned int l) { return (!b || s >= l) ? 0 : b[s]; }
  static short BytesToInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; short v; memcpy(&v, b + s, 2); return v; }
  static unsigned short BytesToUInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; unsigned short v; memcpy(&v, b + s, 2); return v; } };
struct PropertyExceptions { std::vector<SinglePropertyModifier>* grpprl; PropertyExceptions() : grpprl(NULL) {}
  void ReadExceptions(unsigned char* bytes, int size, int nWordVersion); };
struct ColorVal { void SetValue(const std::wstring& v) { printf("color=%ls ", v.c_str()); } };
}
'''

MAIN = r'''
using namespace DocFileFormat;
static void convert(std::vector<SinglePropertyModifier>& grpprl) {
  ColorVal cv; ColorVal* colorVal = &cv;
  for (std::vector<SinglePropertyModifier>::iterator iter = grpprl.begin(); iter != grpprl.end(); ++iter) {
    printf("%04x:%d ", (unsigned)iter->OpCode, iter->argumentsSize);
    switch (iter->OpCode) {
      @@CCV@@
      default: break; } }
}
int main(int argc, char** argv) {
  std::string m = argv[1]; std::vector<unsigned char> v;
  if (m == "cut1") { unsigned char b[] = {0x70, 0x68, 0x11}; v.assign(b, b + 3); }
  if (m == "cut2") { unsigned char b[] = {0x70, 0x68, 0x11, 0x22}; v.assign(b, b + 4); }
  if (m == "full") { unsigned char b[] = {0x70, 0x68, 0x11, 0x22, 0x33, 0x00}; v.assign(b, b + 6); }
  if (m == "bold") { unsigned char b[] = {0x35, 0x08, 0x01, 0x70, 0x68, 0x11, 0x22, 0x33, 0x00}; v.assign(b, b + 9); }
  if (m == "none") { unsigned char b[] = {0x35, 0x08, 0x01, 0x70, 0x68}; v.assign(b, b + 5); }
  unsigned char* bytes = new unsigned char[v.size()]; memcpy(bytes, &v[0], v.size());
  PropertyExceptions px; px.ReadExceptions(bytes, (int)v.size(), 0);
  convert(*px.grpprl); printf("\n"); delete[] bytes; return 0;
}
'''


def main():
    spm = read(D + 'SinglePropertyModifier.cpp')
    spm = '\n'.join(l for l in spm.splitlines() if not l.lstrip().startswith('#include'))
    pe = read(D + 'PropertyExceptions.cpp')
    ccv = span(read(D + 'CharacterPropertiesMapping.cpp'), 'case sprmCCv:', 'case sprmCOldHighlight:')
    code = PRE + spm + '\nnamespace DocFileFormat {\n' + func(pe, 'void PropertyExceptions::ReadExceptions') + '\n}\n' + MAIN.replace('@@CCV@@', ccv)
    work = tempfile.mkdtemp(prefix='rd0093-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(code)
    exe = p[:-4]
    inc = os.path.join(work, 'inc'); os.makedirs(inc)
    for h in ('SinglePropertyModifier.h', '../Common/Base/SPRMCodes.h'):
        open(os.path.join(inc, os.path.basename(h)), 'w').write(read(os.path.normpath(D + h)))
    open(os.path.join(inc, 'SinglePropertyModifier.h'), 'w').write(read(D + 'SinglePropertyModifier.h').replace('../Common/Base/SPRMCodes.h', 'SPRMCodes.h'))
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', '-I', inc, p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in [('cut1', 'sprmCCv with 1 of 4 operand bytes', '6870:4 color=110000'),
                            ('cut2', 'sprmCCv with 2 of 4 operand bytes', '6870:4 color=112200'),
                            ('full', 'complete sprmCCv (unchanged)', '6870:4 color=112233'),
                            ('bold', 'bold + complete sprmCCv (unchanged)', '0835:1 6870:4 color=112233'),
                            ('none', 'bold + sprmCCv with no operand byte (not kept, unchanged)', '0835:1 4600:0')]:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:allocator_may_return_null=1'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
