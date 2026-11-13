#!/usr/bin/env python3
"""
RD-0110 (found by corpus determinism checks; no upstream issue): a formula with a structured
table reference (Table1[Col], Table1[#All], ...) written to .xlsb - defined names, data
validation, cell formulas - got 2 uninitialised bytes in its PtgList (colLast): POI's
ExcelTables.xlsx / DataValidationEvaluations.xlsx -> xlsb gave a different workbook.bin each run
('aaaa' under -ftrivial-auto-var-init=pattern). For a one-column reference colLast is also what
PtgList::toArea uses for the area's last column.

Cause: StringPtgParser makes a stack PtgList whose constructor (Biff_structures/PtgList.cpp)
initialises nothing, and SyntaxPtg::extract_PtgList (SyntaxPtg.cpp) never sets colLast on the
"[#All]/[#Data]/..." path (colFirst = 65535) or on the single "[Column]" path. Fix: the
constructor zero-initialises every field; those two paths set colLast (65535, as colFirst; and
the column, as the other single-column paths do).

What runs: the REAL PtgList constructor (PtgList.cpp), extracted by brace matching, on a stub
class with PtgList's fields (PtgList.h order), placement-new'd into 0xAA memory; checked: all
fields 0. The SyntaxPtg change (boost.regex, workbook tables) is not extracted: only if RD_X2T is
set (RD_X2T_BASE with BASELINE=1) an xlsx with a table and names =Table1[B], =Table1[#All] is
converted to xlsb three times; checked: the PtgList bytes are identical between runs, colLast ==
colFirst for [B] and colLast == 0xFFFF for [#All]. RD_FONTS / RD_X2T_LIBS as in rd-0105.
NOT claimed: Excel's own value of colLast for [#All] (not specified beyond "ignored"); other ptgs.

  RD_REPO=<core checkout> (default ../../core); BASELINE=1 reads BASE_REF and must FAIL.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '36f9fa5ab0^')
BASELINE = bool(os.environ.get('BASELINE'))
D = 'MsBinaryFile/XlsFile/Format/Logic/Biff_structures/'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start):
    a = src.find(start)
    if a < 0:
        sys.exit(repr(start) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


DRIVER = r"""
#include <cstdio>
#include <cstring>
#include <new>
typedef unsigned short _UINT16; typedef unsigned int _UINT32; typedef unsigned char BYTE;
namespace XLS {
struct OperandPtg { unsigned short id; OperandPtg(unsigned short i) : id(i) {} };
struct PtgList : OperandPtg {   // the fields of PtgList.h, in its order
  PtgList(const unsigned short full_ptg_id);
  _UINT16 ixti; BYTE columns; BYTE rowType; bool squareBracketSpace; bool commaSpace; BYTE type_; bool invalid; bool nonresident;
  _UINT32 listIndex; _UINT16 colFirst; _UINT16 colLast;
};
@@CTOR@@
}
int main() {
  alignas(XLS::PtgList) unsigned char mem[sizeof(XLS::PtgList)]; memset(mem, 0xAA, sizeof mem);
  XLS::PtgList* p = new (mem) XLS::PtgList(0x1918);
  printf("ixti=%x columns=%x rowType=%x sbs=%d cs=%d type=%x invalid=%d nonres=%d listIndex=%x colFirst=%x colLast=%x\n",
    p->ixti, p->columns, p->rowType, (int)*(unsigned char*)&p->squareBracketSpace, (int)*(unsigned char*)&p->commaSpace, p->type_,
    (int)*(unsigned char*)&p->invalid, (int)*(unsigned char*)&p->nonresident, p->listIndex, p->colFirst, p->colLast);
  return 0;
}
"""


def run_extracted():
    ctor = block(read(D + 'PtgList.cpp'), 'PtgList::PtgList(const unsigned short full_ptg_id)')
    hdr = read(D + 'PtgList.h')
    order = [f for f in ('ixti;', 'columns;', 'rowType;', 'squareBracketSpace;', 'commaSpace;', 'type_;', 'invalid;', 'nonresident;',
                         'listIndex;', 'colFirst;', 'colLast;')]
    pos = [hdr.find(f) for f in order]
    if -1 in pos or pos != sorted(pos):
        sys.exit('PtgList.h fields changed - update the stub class')
    work = tempfile.mkdtemp(prefix='rd0110-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CTOR@@', ctor))
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    got = subprocess.run([p[:-4]], capture_output=True, text=True).stdout.strip()
    want = 'ixti=0 columns=0 rowType=0 sbs=0 cs=0 type=0 invalid=0 nonres=0 listIndex=0 colFirst=0 colLast=0'
    ok = got == want
    print(('ok   ' if ok else 'FAIL ') + 'PtgList(0x1918) over 0xAA memory: %s' % got)
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


NS = 'http://schemas.openxmlformats.org/'


def make_xlsx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
                   '<definedNames><definedName name="ColB">Table1[B]</definedName><definedName name="AllT">Table1[#All]</definedName></definedNames></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/worksheets/_rels/sheet1.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/table" Target="../tables/table1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/tables/table1.xml', '<?xml version="1.0" encoding="UTF-8"?><table xmlns="%sspreadsheetml/2006/main" id="1" name="Table1" displayName="Table1" ref="A1:B3"><autoFilter ref="A1:B3"/><tableColumns count="2"><tableColumn id="1" name="A"/><tableColumn id="2" name="B"/></tableColumns></table>' % NS)
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheetData>'
                   '<row r="1"><c r="A1" t="inlineStr"><is><t>A</t></is></c><c r="B1" t="inlineStr"><is><t>B</t></is></c></row>'
                   '<row r="2"><c r="A2"><v>1</v></c><c r="B2"><v>2</v></c></row><row r="3"><c r="A3"><v>3</v></c><c r="B3"><v>4</v></c></row>'
                   '</sheetData><tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>' % (NS, NS))


def x2t(exe, src, dst, fmt, work):
    td = tempfile.mkdtemp(dir=work)
    fonts = ''
    if os.environ.get('RD_FONTS'):
        fd = os.path.join(work, 'fonts')
        if not os.path.isdir(fd):
            shutil.copytree(os.environ['RD_FONTS'], fd)
        fonts = '<m_sFontDir>%s</m_sFontDir><m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath>' % (fd, fd)
    p = os.path.join(td, 'params.xml')
    open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>'
                       '<m_nFormatTo>%d</m_nFormatTo>%s<m_sTempDir>%s</m_sTempDir></TaskQueueDataConvert>' % (src, dst, fmt, fonts, td))
    env = dict(os.environ)
    if os.environ.get('RD_X2T_LIBS'):
        env['DYLD_FRAMEWORK_PATH'] = env['LD_LIBRARY_PATH'] = os.environ['RD_X2T_LIBS']
    return subprocess.run([exe, p], capture_output=True, env=env, timeout=120).returncode


def ptglists(wb):
    # every PtgList (0x18 0x19 + 12 bytes) in the workbook part: ixti(2) flags(2) listIndex(4) colFirst(2) colLast(2)
    out = []; i = wb.find(b'\x18\x19')
    while i >= 0:
        b = wb[i + 2:i + 14]
        if len(b) == 12:
            out.append((int.from_bytes(b[2:4], 'little') & 3, int.from_bytes(b[8:10], 'little'), int.from_bytes(b[10:12], 'little')))
        i = wb.find(b'\x18\x19', i + 1)
    return out


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0110-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    runs = []
    for k in range(3):
        o = os.path.join(work, '%d.xlsb' % k)
        rc = x2t(exe, src, o, 0x0108, work)
        if rc:
            print('FAIL x2t xlsx -> xlsb: rc=%d' % rc)
            return 1
        runs.append(ptglists(zipfile.ZipFile(o).read('xl/workbook.bin')))
    lists = runs[0]
    good = all((c == 1 and l == f) or (c == 0 and l == 0xFFFF) or c == 2 for c, f, l in lists)
    ok = len(lists) >= 2 and runs[0] == runs[1] == runs[2] and good
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> xlsb x3: PtgList (columns, colFirst, colLast) %s%s'
          % (', '.join('(%d,%#x,%#x)' % t for t in lists), '' if runs[0] == runs[1] == runs[2] else '; runs DIFFER'))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


def main():
    fails = run_extracted()
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    exe = os.environ.get('RD_X2T_BASE') if BASELINE else os.environ.get('RD_X2T')
    if exe:
        fails += run_x2t(exe)
    else:
        print('skip x2t end-to-end (set RD_X2T, and RD_X2T_BASE for BASELINE=1)')
    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', fails))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
