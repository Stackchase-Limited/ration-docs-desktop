#!/usr/bin/env python3
"""
RD-0094 (our crafted-input audit, no upstream issue): a .doc table sprm whose
variable-size operand is shorter than its [MS-DOC] structure made x2t read past
the operand. Crafted POI 58804.doc / 53446.doc / Bug33519.doc with the
sprmTTableBorders80 length byte 24 -> 2 (the other 22 bytes made into an
unknown sprm): ASan heap-buffer-overflow READ of size 4 at
TableRowPropertiesMapping.cpp:183; 58804.doc with sprmTCellWidth's length
5 -> 2 (Data stream): READ at TableCellPropertiesMapping.cpp:278.

Cause (MsBinaryFile/DocFile): the mappings read variable-size operands as
their fixed structure without looking at argumentsSize - TTableBorders80
memcpy'd 24 bytes; the CSSA padding sprms, sprmTCellWidth, sprmTVertAlign
indexed bytes 0-3; apppendCellShading copied a 2-byte SHD80 from the last
byte; SprmTDefTable read itcMac from an empty operand and four BorderCodes
from a cut TC80; RevisionData took sprmCPropRMark2's DTTM from bytes 3-6.
Fix: each checks the operand holds what it reads and skips the property (or
uses the default TC80) otherwise.

What runs (-fsanitize=address, operands in exact-size heap buffers): the REAL
"case sprmTTableBorders80:" block of TableRowPropertiesMapping::Apply, the
REAL "case sprmTCellWidth:" block of TableCellPropertiesMapping::Apply, the
REAL TableCellPropertiesMapping::apppendCellShading, the REAL SprmTDefTable
constructor, and the REAL "case sprmCPropRMark2:" block of RevisionData, with
stand-ins for BorderCode / ShadingDescriptor / DateAndTime (they read the
bytes they are given, as the real ones do), FormatUtils and the XML output.
Cases: each with a short operand (before: over-read; now the property is
skipped / default) and with a well-formed one (unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0094 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '1f2f77f8f6^')
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
#include <vector>
#include <memory>
typedef unsigned char BYTE;
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
static volatile unsigned sink;
static unsigned sum(const unsigned char* b, int n) { unsigned s = 0; for (int i = 0; i < n; i++) s += b[i]; sink += s; return s; }
namespace Global { enum CellWidthType { nil, auto_, pct, dxa }; enum TextFlow { lrTb }; enum VerticalMergeFlag { fvmClear };
  enum VerticalAlign { top }; }
namespace DocFileFormat {
enum { sprmTTableBorders80 = 0xD605, sprmTCellWidth = 0xD635, sprmCPropRMark2 = 0xCA89 };
struct FormatUtils {
  static short BytesToInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; short v; memcpy(&v, b + s, 2); return v; }
  static unsigned short BytesToUInt16(const unsigned char* b, unsigned int s, unsigned int l) { return (unsigned short)BytesToInt16(b, s, l); }
  static int BitmaskToInt(int v, int m) { int r = v & m; while (m && !(m & 1)) { m >>= 1; r >>= 1; } return r; }
  static bool BitmaskToBool(int v, int m) { return (v & m) != 0; } };
struct BorderCode { unsigned s; BorderCode() : s(0) {} BorderCode(unsigned char* b, int n) : s(sum(b, n)) {} };
struct ShadingDescriptor { unsigned s; ShadingDescriptor(unsigned char* b, int n) : s(sum(b, n)) {} };
struct DateAndTime { unsigned s; DateAndTime() : s(0) {} DateAndTime(unsigned char* b, int n) : s(sum(b, n)) {} };
struct SPM { unsigned short OpCode; unsigned char* Arguments; int argumentsSize; };
struct TC80 { TC80() : horzMerge(0), wWidth(0) {} unsigned char horzMerge; Global::TextFlow textFlow; Global::VerticalMergeFlag vertMerge;
  Global::VerticalAlign vertAlign; Global::CellWidthType ftsWidth; bool fFitText, fNoWrap, fHideMark; short wWidth;
  BorderCode *brcTop, *brcLeft, *brcBottom, *brcRight; };
class SprmTDefTable { public: SprmTDefTable(unsigned char* bytes, int size);
  unsigned char numberOfColumns; std::vector<short> rgdxaCenter; std::vector<TC80> rgTc80; };
@@TDEF@@
struct Cell { int _cellIndex; Global::CellWidthType _ftsWidth; short _width; int shd; Cell() : _cellIndex(0), _ftsWidth(Global::nil), _width(0), shd(-1) {}
  void appendShading(void*, const ShadingDescriptor& d) { shd = (int)d.s; } void* _tcPr;
  void apppendCellShading(unsigned char* sprmArg, int size, int cellIndex); };
@@SHD@@
}
using namespace DocFileFormat;
'''

MAIN = r'''
static unsigned char* mk(const char* hex, int& n) { n = (int)strlen(hex) / 2; unsigned char* b = new unsigned char[n];
  for (int i = 0; i < n; i++) { unsigned v; sscanf(hex + 2 * i, "%2x", &v); b[i] = (unsigned char)v; } return b; }
int main(int argc, char** argv) {
  std::string m = argv[1]; int n = 0;
  if (m == "brc2" || m == "brc24") {
    unsigned char* a = mk(m == "brc2" ? "0102" : "010000000200000003000000040000000500000006000000", n);
    SPM s = { sprmTTableBorders80, a, n }; SPM* iter = &s;
    std::shared_ptr<BorderCode> brcTop, brcLeft, brcBottom, brcRight, brcHorz, brcVert;
    switch (iter->OpCode) { @@ROW@@ default: break; }
    printf("borders=%u,%u,%u,%u,%u,%u\n", brcTop ? brcTop->s : 99, brcLeft ? brcLeft->s : 99, brcBottom ? brcBottom->s : 99,
           brcRight ? brcRight->s : 99, brcHorz ? brcHorz->s : 99, brcVert ? brcVert->s : 99); delete[] a;
  } else if (m == "width2" || m == "width5") {
    unsigned char* a = mk(m == "width2" ? "0001" : "0001033412", n);
    SPM s = { sprmTCellWidth, a, n }; SPM* iter = &s; Cell c; int& _cellIndex = c._cellIndex;
    Global::CellWidthType& _ftsWidth = c._ftsWidth; short& _width = c._width;
    switch (iter->OpCode) { @@CELL@@ default: break; }
    printf("fts=%d width=%d\n", (int)_ftsWidth, (int)_width); delete[] a;
  } else if (m == "shd3" || m == "shd4") {
    unsigned char* a = mk(m == "shd3" ? "010203" : "01020304", n); Cell c; c.apppendCellShading(a, n, 1); printf("shd=%d\n", c.shd); delete[] a;
  } else if (m == "tdef0" || m == "tdef_cut" || m == "tdef_ok") {
    // itcMac 1, rgdxaCenter 0 and 100, then a TC80 (20 bytes) cut to 6, or whole
    unsigned char* a = mk(m == "tdef0" ? "" : m == "tdef_cut" ? "0100006400" "000064000102" : "0100006400" "0000640001010101020202020303030304040404", n);
    SprmTDefTable t(a, n); printf("cols=%d tc=%d w=%d\n", t.numberOfColumns, (int)t.rgTc80.size(), t.rgTc80.empty() ? -1 : t.rgTc80[0].wWidth); delete[] a;
  } else {
    unsigned char* a = mk(m == "rmark3" ? "010200" : "01020001020304", n);
    SPM s = { sprmCPropRMark2, a, n }; SPM* iter = &s;
    struct { bool collect; short Isbt; DateAndTime Dttm; } r = { true, 0, DateAndTime() }; bool& collectRevisionData = r.collect;
    struct Self { short& Isbt; DateAndTime& Dttm; } self = { r.Isbt, r.Dttm }; Self* this_ = &self;
    switch (iter->OpCode) { @@RMARK@@ default: break; }
    printf("isbt=%d dttm=%u\n", r.Isbt, r.Dttm.s); delete[] a;
  }
  return 0;
}
'''


def main():
    row = span(read(D + 'TableRowPropertiesMapping.cpp'), 'case sprmTTableBorders80:', 'case sprmTCellPaddingDefault:')
    cellsrc = read(D + 'TableCellPropertiesMapping.cpp')
    cell = span(cellsrc, 'case sprmTCellWidth:', 'case sprmTVertAlign:')
    shd = func(cellsrc, 'void TableCellPropertiesMapping::apppendCellShading').replace('TableCellPropertiesMapping::', 'Cell::')
    tdef = func(read(D + 'SprmTDefTable.cpp'), 'SprmTDefTable::SprmTDefTable')
    rmark = span(read(D + 'RevisionData.cpp'), 'case sprmCPropRMark2:', 'case sprmCFRMark:').replace('this->', 'this_->')
    code = (PRE.replace('@@TDEF@@', tdef).replace('@@SHD@@', shd) +
            MAIN.replace('@@ROW@@', row).replace('@@CELL@@', cell).replace('@@RMARK@@', rmark))
    fails = build_run(code, [('brc2', 'sprmTTableBorders80 with 2 operand bytes (row)', 'borders=99,99,99,99,99,99'),
                             ('brc24', 'sprmTTableBorders80 with 24 bytes (unchanged)', 'borders=1,2,3,4,5,6'),
                             ('width2', 'sprmTCellWidth with 2 operand bytes (cell)', 'fts=0 width=0'),
                             ('width5', 'sprmTCellWidth with 5 bytes (unchanged)', 'fts=3 width=4660'),
                             ('shd3', 'cell 1 shading from a 3-byte sprmTDefTableShd80', 'shd=-1'),
                             ('shd4', 'cell 1 shading from 4 bytes (unchanged)', 'shd=7'),
                             ('tdef0', 'sprmTDefTable with an empty operand', 'cols=0 tc=0 w=-1'),
                             ('tdef_cut', 'sprmTDefTable whose TC80 is cut to 6 bytes', 'cols=1 tc=1 w=0'),
                             ('tdef_ok', 'sprmTDefTable with a whole TC80 (unchanged)', 'cols=1 tc=1 w=100'),
                             ('rmark3', 'sprmCPropRMark2 with 3 operand bytes', 'isbt=2 dttm=0'),
                             ('rmark7', 'sprmCPropRMark2 with 7 bytes (unchanged)', 'isbt=2 dttm=10')], 'rd0094')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
