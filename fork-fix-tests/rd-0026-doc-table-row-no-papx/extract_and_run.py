#!/usr/bin/env python3
"""
RD-0026 (our corpus run, no upstream issue): a .doc table whose row end has no
paragraph properties crashed x2t (SIGSEGV at address 0x8).

Found on LibreOffice's sw/qa/core/data/ww8/pass/hang-8.doc: the release x2t dies
in DocFileFormat::TablePropertyExceptions::TablePropertyExceptions(
ParagraphPropertyExceptions*, POLE::Stream*, int), called from Table::Convert
(TableMapping.cpp) with documentMapping->findValidPapx(fcRowEnd).

Cause: findValidPapx returns NULL when no PAPX starts at or before the row-end
fc (and a PAPX of a Word 2/1.0-era file has grpprl == NULL, see
PropertyExceptions' constructor), but the TAPX constructor walked
papx->grpprl unconditionally. It is built that way in three places
(TableMapping.cpp Table::Convert, DocumentMapping.cpp twice). Fix: the
constructor returns with no table properties when papx or its grpprl is NULL.

What runs: the REAL constructor TablePropertyExceptions(ParagraphPropertyExceptions*,
POLE::Stream*, int) (brace-matched; git show BASE_REF:... with BASELINE=1),
compiled with -fsanitize=address against stand-in PropertyExceptions /
SinglePropertyModifier / VirtualStreamReader types. Cases: papx NULL, papx with
grpprl NULL (must not crash, no properties), and a papx with one TAP sprm and one
PAP sprm (the TAP one is kept, as before).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read TablePropertyExceptions.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0026 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '9e403b506b^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/DocFile/TablePropertyExceptions.cpp'


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
#include <vector>
#define FALSE false
#define TRUE true
#define RELEASEARRAYOBJECTS(p) delete[] (p)
namespace POLE { struct Stream {}; }
namespace DocFileFormat {
enum { sprmTDefTableShd = 1, sprmTDefTableShd2nd, sprmTDefTableShd3rd, sprmPTableProps, sprmTOther, sprmPOther };
enum SprmType { PAP, TAP };
struct SinglePropertyModifier { int OpCode; SprmType Type; unsigned char* Arguments; unsigned int argumentsSize; };
struct FormatUtils { static unsigned int BytesToUInt32(unsigned char*, int, int) { return 0; }
                     static unsigned short BytesToUInt16(unsigned char*, int, int) { return 0; } };
struct VirtualStreamReader { VirtualStreamReader(POLE::Stream*, int, int) {} void Seek(int, int) {} unsigned long GetPosition() const { return 0; }
                             unsigned char* ReadBytes(int, bool) { return NULL; } };
struct PropertyExceptions { std::vector<SinglePropertyModifier>* grpprl;
    PropertyExceptions() : grpprl(new std::vector<SinglePropertyModifier>()) {}
    PropertyExceptions(unsigned char*, int, int) : grpprl(new std::vector<SinglePropertyModifier>()) {}
    ~PropertyExceptions() { delete grpprl; } };
struct ParagraphPropertyExceptions : PropertyExceptions {};
struct TablePropertyExceptions : PropertyExceptions { bool m_bSkipShading97;
    TablePropertyExceptions (ParagraphPropertyExceptions* papx, POLE::Stream* dataStream, int nWordVersion); };
@@CTOR@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
    POLE::Stream s; ParagraphPropertyExceptions papx; ParagraphPropertyExceptions* p = &papx; char c = argv[1][0];
    if (c == 'n') p = NULL;
    else if (c == 'g') { delete papx.grpprl; papx.grpprl = NULL; }
    else { SinglePropertyModifier a = { sprmTOther, TAP, 0, 0 }, b = { sprmPOther, PAP, 0, 0 };
           papx.grpprl->push_back(a); papx.grpprl->push_back(b); }
    TablePropertyExceptions t(p, &s, 0);
    printf("tap=%zu\n", t.grpprl->size());
    return 0;
}
'''

CASES = [('n', 'row end without a PAPX (NULL)', 'tap=0'),
         ('g', 'PAPX whose grpprl was never parsed (NULL)', 'tap=0'),
         ('v', 'PAPX with one TAP and one PAP sprm (unchanged)', 'tap=1')]


def main():
    src = read(REL)
    ctor = func(src, 'TablePropertyExceptions::TablePropertyExceptions (ParagraphPropertyExceptions* papx')
    work = tempfile.mkdtemp(prefix='rd0026-')
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
