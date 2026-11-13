#!/usr/bin/env python3
"""
RD-0043 (our corpus run, no upstream issue): a .doc sprm cut short at the end of
its grpprl was read past the buffer, and its operand copy could be 4 GB long.
Found on LibreOffice's sw/qa/core/data/ww6/pass/ofz21385-1.doc (ASan: heap
over-read in PropertyExceptions::ReadExceptions, PropertyExceptions.cpp:155, and
a memcpy of 4294967295 bytes in the SinglePropertyModifier constructor).

Cause: PropertyExceptions::ReadExceptions (MsBinaryFile/DocFile/
PropertyExceptions.cpp) read a variable sprm's length byte - and sprmPChgTabs'
itbdDelMax/itbdAddMax bytes - with bytes[...] and no size check, then gave
SinglePropertyModifier the sprm truncated to the bytes left. That constructor
(SinglePropertyModifier.cpp) took the operand length from the sprm again
(bytes[opCodeSize], bytes[2], or the TDefTable 2-byte length - 1) and memcpy'd
that many bytes; argumentsSize is unsigned, so a -1 became 4294967295.
Fix: those bytes are read with FormatUtils::BytesToUChar (0 past the end) and
the constructor copies at most the bytes present after the length byte(s).

What runs: the REAL SinglePropertyModifier.cpp and the REAL PropertyExceptions::
ReadExceptions (git show BASE_REF:... with BASELINE=1), with the REAL
SinglePropertyModifier.h / SPRMCodes.h, a stand-in FormatUtils and a stand-in
PropertyExceptions declaration, compiled with -fsanitize=address. Each case is a
Word 97 grpprl; the driver prints each sprm's operand size.
Cases: a variable sprm with no length byte (over-read before); one whose
length (10) runs past the grpprl with 3 bytes there, and a TDefTable whose
length (50) runs past it with 2 there (before: 10 / 49 operand bytes, the rest
uninitialised heap); an sprmPChgTabs with length 255 and nothing after (over-
read before; now the computed length is -1 and no sprm is made); and a
well-formed grpprl of a 2-byte variable sprm plus a 1-byte sprm (unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the two .cpp files at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0043 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '318e3ef22a^')
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


PRE = r'''
#include <cstdio>
#include <cstring>
#include <vector>
#include <algorithm>
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
#include "SinglePropertyModifier.h"
namespace DocFileFormat {
struct FormatUtils {
  static unsigned char BytesToUChar(const unsigned char* b, unsigned int s, unsigned int l) { return (!b || s >= l) ? 0 : b[s]; }
  static short BytesToInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; short v; memcpy(&v, b + s, 2); return v; }
  static unsigned short BytesToUInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; unsigned short v; memcpy(&v, b + s, 2); return v; } };
struct PropertyExceptions { std::vector<SinglePropertyModifier>* grpprl; PropertyExceptions() : grpprl(NULL) {}
  void ReadExceptions(unsigned char* bytes, int size, int nWordVersion); };
}
'''

MAIN = r'''
using namespace DocFileFormat;
int main(int argc, char** argv) {
  std::vector<unsigned char> v;
  switch (argv[1][0]) {
    case 'a': { unsigned char b[] = {0x50, 0xC6}; v.assign(b, b + 2); break; }                      // variable sprm, no length byte
    case 'b': { unsigned char b[] = {0x50, 0xC6, 10, 1, 2, 3}; v.assign(b, b + 6); break; }          // length 10, 3 bytes present
    case 'c': { unsigned char b[] = {0x08, 0xD6, 50, 0, 1, 2}; v.assign(b, b + 6); break; }          // sprmTDefTable, length 50
    case 'd': { unsigned char b[] = {0x15, 0xC6, 255}; v.assign(b, b + 3); break; }                  // sprmPChgTabs, length 255
    default:  { unsigned char b[] = {0x50, 0xC6, 2, 7, 7, 0x35, 0x08, 1}; v.assign(b, b + 8); }      // well-formed
  }
  unsigned char* bytes = new unsigned char[v.size()]; memcpy(bytes, &v[0], v.size());
  PropertyExceptions px; px.ReadExceptions(bytes, (int)v.size(), 0);
  printf("args=");
  for (size_t i = 0; i < px.grpprl->size(); i++) printf("%u,", px.grpprl->at(i).argumentsSize);
  printf("\n"); delete[] bytes; return 0;
}
'''

CASES = [('a', 'variable sprm with no length byte', 'args=0,'),
         ('b', 'operand length 10 with 3 bytes left', 'args=3,'),
         ('c', 'sprmTDefTable length 50 with 2 bytes left', 'args=2,'),
         ('d', 'sprmPChgTabs length 255 with nothing after (no sprm)', 'args='),
         ('n', 'well-formed grpprl (unchanged)', 'args=2,1,')]


def main():
    spm = read(D + 'SinglePropertyModifier.cpp')
    spm = '\n'.join(l for l in spm.splitlines() if not l.lstrip().startswith('#include'))
    pe = read(D + 'PropertyExceptions.cpp')
    code = PRE + spm + '\nnamespace DocFileFormat {\n' + func(pe, 'void PropertyExceptions::ReadExceptions') + '\n}\n' + MAIN
    work = tempfile.mkdtemp(prefix='rd0043-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(code)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', '-I', os.path.join(REPO, D), p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:allocator_may_return_null=1'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
            ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
