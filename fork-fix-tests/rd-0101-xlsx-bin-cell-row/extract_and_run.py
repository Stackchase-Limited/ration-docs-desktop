#!/usr/bin/env python3
"""
RD-0101 (found by x2t corpus runs; no upstream issue): an Editor.bin written
by x2t's C++ binary writer - xlsx -> Editor.bin with m_bIsNoBase64=false, the
"XLSY;v2;" base64 form - came back from x2t one row out:
  - bin -> xlsx: <row r="1"><c r="A2"/><c r="B2"/></row><row r="2"><c r="A3"/>...
    (every cell reference one row below the row that holds it; bin -> csv and
    bin -> xlsb do not use the cell's row and were not affected)

Cause: BinaryWorksheetTableWriter::WriteCell (OOXML/Binary/Sheets/Reader/
BinaryWriterS.cpp) writes RefRowCol from CCell::getRowCol, whose row is
1-based for a cell read from xlsx and 0-based for one read from xlsb. sdkjs
ignores that row (cell/model/Serialize.js: setRowCol(nRowIndex, col)), but
BinaryWorksheetsTableReader::ReadCells/ReadCell (OOXML/Binary/Sheets/Writer/
BinaryReaderS.cpp) kept it as the 0-based m_oRow that CCell::toXML writes + 1.
Fix: ReadCells gives the cell the row of the row record it is read in (r - 1).

What runs:
  1. the REAL BinaryWorksheetsTableReader::ReadCells, extracted by brace
     matching, against stubs: READ1_DEF delivers one RefRowCol item to a stub
     ReadCell that stores (row, col) as the real one does (setRowCol); the row
     record carries r. The cell is then emitted through the toXML branch; the
     stub toXML writes letter + (m_oRow + 1) as CCell::toXML does for xlsx.
     Cases: the writer's 1-based row (cell from xlsx; seen end to end), a
     0-based row (cell from xlsb, per CCell::ReadAttributes - read from the code,
     not run: our xlsb -> base64 bin conversion crashes before it, see report) -
     both must give the row's own number.
  2. only if RD_X2T=<x2t binary> is set (NOT built by this test): a generated
     xlsx (rows 1, 2, 4) -> Editor.bin (m_bIsNoBase64=false) -> xlsx by that
     x2t; every <c r> must lie in its <row r> (RD_FONTS: font cache dir, copied
     first; DYLD/LD path from RD_X2T_LIBS). Not claimed without it.
NOT claimed: any desktop UI path. The desktop asks x2t for base64 bins only
via AscDesktopEditor.convertFile(.., 0x2002) and those are read by sdkjs,
which ignores the row; editor saves write sheet data as XLSB records, which
do not pass through ReadCells.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0101 commit
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'f5a02ff33e^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/Binary/Sheets/Writer/BinaryReaderS.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig):
    a = src.find(sig)
    if a < 0:
        sys.exit(repr(sig) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


HEAD = r"""
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
typedef unsigned char BYTE;
namespace XmlUtils { int GetInteger(const std::wstring& s) { return (int)wcstol(s.c_str(), NULL, 10); } }
template<class T> struct nullable {
  bool b = false; T v = T();
  bool IsInit() const { return b; }
  T get() const { return v; }
  T& operator*() { return v; }
  T* operator->() { return &v; }
  nullable& operator=(T x) { v = x; b = true; return *this; }
  void Init() { b = true; }
};
struct CUnsignedDecimalNumber { unsigned int n = 0; unsigned int GetValue() const { return n; } void SetValue(unsigned int x) { n = x; } };
namespace c_oSerConstants { enum { ReadOk = 0, ReadUnknown = 1 }; }
namespace c_oSerRowTypes { enum { Row = 0, Style = 1, Height = 2, CustomHeight = 3, Cells = 4, Cell = 5 }; }
namespace c_oSerCellTypes { enum { Ref = 0, RefRowCol = 5 }; }
namespace SimpleTypes { namespace Spreadsheet { enum ECellTypeType { celltypeError = 2, celltypeSharedString = 5, celltypeStr = 6 }; } }
struct StringBuilder { std::string s; };
static std::string g_out;
namespace OOX { enum { et_x_t = 1 }; namespace Spreadsheet {
  struct WritingElement { virtual ~WritingElement() {} virtual int getType() const { return 0; } };
  struct CText : WritingElement { std::wstring m_sText; int m_oSpace = 0; };
  struct CSi { std::vector<WritingElement*> m_arrItems; };
  struct CValue { std::wstring ToString() const { return m_sText; } std::wstring m_sText; int m_oSpace = 0; };
  struct CTypeV { SimpleTypes::Spreadsheet::ECellTypeType t; SimpleTypes::Spreadsheet::ECellTypeType GetValue() const { return t; } void SetValue(SimpleTypes::Spreadsheet::ECellTypeType x) { t = x; } };
  struct CCell {
    nullable<unsigned int> m_oRow; nullable<int> m_oCol;
    nullable<CTypeV> m_oType; nullable<CValue> m_oValue; nullable<int> m_oFormula;
    void setRowCol(int r, int c) { m_oRow = (unsigned int)r; m_oCol = c; }
    // as CCell::toXML for an xlsx target: letters of the 0-based column, m_oRow + 1
    void toXML(StringBuilder&) const { char b[32]; snprintf(b, sizeof b, "%c%u", 'A' + m_oCol.get(), m_oRow.get() + 1); g_out += b; }
    void toBin(void*) const {}
  };
  struct CRow { nullable<CUnsignedDecimalNumber> m_oR; };
  struct CSharedStrings { std::vector<CSi*> m_arrItems; };
} }
struct CSVWriterStub { void WriteCell(OOX::Spreadsheet::CCell*) {} };
struct SaveParams { CSVWriterStub* pCSVWriter = nullptr; };
// READ1_DEF: deliver one RefRowCol item to ReadCell (the stream framing is not under test)
#define READ1_DEF(stLen, res, fReadFunction, arg) { res = fReadFunction(c_oSerCellTypes::RefRowCol, 8, arg); }
static int g_binRow, g_binCol;   // what the bin's RefRowCol holds
struct BinaryWorksheetsTableReader {
  OOX::Spreadsheet::CSharedStrings* m_pSharedStrings = nullptr;
  SaveParams m_oSaveParams;
  StringBuilder* m_pCurStreamWriter = new StringBuilder;
  void* m_pCurStreamWriterBin = nullptr;
  // as the real ReadCell's RefRowCol branch: pCell->setRowCol(nRow, nCol)
  int ReadCell(BYTE type, long length, void* poResult) {
    static_cast<OOX::Spreadsheet::CCell*>(poResult)->setRowCol(g_binRow, g_binCol); return c_oSerConstants::ReadOk; }
  int ReadCells(BYTE type, long length, void* poResult);
};
@@FN@@
int main(int argc, char** argv) {
  // argv: <row r> <RefRowCol row> <RefRowCol col>
  OOX::Spreadsheet::CRow row; row.m_oR.Init(); row.m_oR->SetValue(atoi(argv[1]));
  g_binRow = atoi(argv[2]); g_binCol = atoi(argv[3]);
  BinaryWorksheetsTableReader r;
  r.ReadCells(c_oSerRowTypes::Cell, 8, &row);
  printf("%s\n", g_out.c_str());
  return 0;
}
"""

CASES = [
    ('1', '1', '0', 'A1', 'row 1, cell from xlsx (writer gives 1-based row 1)'),
    ('2', '2', '2', 'C2', 'row 2, cell from xlsx'),
    ('4', '4', '1', 'B4', 'row 4 after a gap, cell from xlsx'),
    ('3', '2', '0', 'A3', 'row 3, cell from xlsb (writer gives 0-based row 2)'),
]


def run_extracted():
    src = read(REL)
    fn = func(src, 'int BinaryWorksheetsTableReader::ReadCells(BYTE type, long length, void* poResult)')
    code = HEAD.replace('@@FN@@', fn)
    work = tempfile.mkdtemp(prefix='rd0101-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for rr, br, bc, want, label in CASES:
        r = subprocess.run([exe, rr, br, bc], capture_output=True, text=True)
        got = r.stdout.strip()
        ok = r.returncode == 0 and got == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s: <row r="%s"> RefRowCol(%s,%s) -> <c r="%s">%s' % (
            label, rr, br, bc, got, '' if ok else '  (want ' + want + ')'))
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


def make_xlsx(path):
    ns = 'http://schemas.openxmlformats.org/'
    sheet = ('<row r="1"><c r="A1"><v>11</v></c><c r="B1"><v>12</v></c></row>'
             '<row r="2"><c r="A2"><v>21</v></c><c r="C2"><v>23</v></c></row>'
             '<row r="4"><c r="B4"><v>42</v></c></row>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % ns)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (ns, ns))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (ns, ns))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (ns, ns))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % (ns, sheet))


def x2t(exe, src, dst, fmt, work, extra=''):
    td = tempfile.mkdtemp(dir=work)
    fonts = ''
    if os.environ.get('RD_FONTS'):
        fd = os.path.join(work, 'fonts')
        if not os.path.isdir(fd):
            shutil.copytree(os.environ['RD_FONTS'], fd)
        fonts = '<m_sFontDir>%s</m_sFontDir><m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath>' % (fd, fd)
    p = os.path.join(td, 'params.xml')
    open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>'
                       '<m_nFormatTo>%d</m_nFormatTo>%s<m_sTempDir>%s</m_sTempDir>%s</TaskQueueDataConvert>' % (src, dst, fmt, fonts, td, extra))
    env = dict(os.environ)
    if os.environ.get('RD_X2T_LIBS'):
        env['DYLD_FRAMEWORK_PATH'] = env['LD_LIBRARY_PATH'] = os.environ['RD_X2T_LIBS']
    return subprocess.run([exe, p], capture_output=True, env=env, timeout=120).returncode


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0101-x2t-')
    src = os.path.join(work, 'rows.xlsx'); make_xlsx(src)
    eb = os.path.join(work, 'eb'); os.mkdir(eb)
    rc = x2t(exe, src, os.path.join(eb, 'Editor.bin'), 0x2002, work, '<m_bIsNoBase64>false</m_bIsNoBase64>')
    back = os.path.join(work, 'back.xlsx')
    rc = rc or x2t(exe, os.path.join(eb, 'Editor.bin'), back, 0x0101, work)
    if rc or not os.path.exists(back):
        print('FAIL x2t xlsx -> base64 Editor.bin -> xlsx: rc=%d' % rc); return 1
    xml = zipfile.ZipFile(back).read('xl/worksheets/sheet1.xml').decode('utf-8')
    got = []
    for rnum, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', xml):
        got.append('%s:%s' % (rnum, ','.join(re.findall(r'<c r="([A-Z]+\d+)"', body))))
    got = ' '.join(got); want = '1:A1,B1 2:A2,C2 4:B4'
    ok = got == want
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> base64 Editor.bin -> xlsx, row:cells = %s%s' % (got, '' if ok else '  (want ' + want + ')'))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


def main():
    fails = run_extracted()
    if os.environ.get('RD_X2T'):
        fails += run_x2t(os.environ['RD_X2T'])
    else:
        print('skip x2t end-to-end (set RD_X2T to an x2t built from the tree under test)')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
