#!/usr/bin/env python3
"""
RD-0105 (found by corpus testing of xlsb -> Editor.bin round trips; no upstream issue):
DATA LOSS ON OPEN - the text of an .xlsb's inline-string cells (BrtCellSt) and str cells
(BrtFmlaString, the cached text of a string formula) opened in the editor as the number 0.
An xlsb whose csv export is "Name,Score | Ada,10" opened in the desktop as "0,0 | 0,10"
(checked in the real cell editor, headless: every such cell showed 0). Both Editor.bin
kinds: raw (the normal desktop open of an .xlsb) and base64 (convertFile).

Cause: the xlsb reader (CCell::fromBin / ReadValue, OOXML/XlsxFormat/Worksheets/SheetData.cpp)
keeps such a cell's text in m_oValue with type inlineStr / str. The Editor.bin cell writer
(BinaryWorksheetTableWriter::WriteCell, BinaryWriterS.cpp) writes m_oValue as a double, and
sdkjs (cell/model/Serialize.js ReadCell) takes a string cell only as a shared-string index and
ignores the inlineStr/str types: text -> 0. For xlsx the same cells are moved into the shared
strings while reading (CCell::AfterRead / CXlsx::PrepareWorksheet); an xlsb's sheet data is read
later (CXlsb::ReadSheetData, after PrepareWorkbook) and nothing moved them.
Fix: CXlsb::PrepareSheetStrings (OOXML/XlsbFormat/Xlsb.cpp) moves that text into the shared
strings; BinaryFileWriter::Open calls it after ReadSheetData for every target but mail-merge
JSON (whose writer reads the inline text itself), as do Pic.cpp / SmartArt.cpp for embedded
xlsb workbooks.

What runs:
  1. the REAL XLSB block after PrepareWorkbook in BinaryFileWriter::Open and the REAL
     CXlsb::PrepareSheetStrings (when the tree has it), extracted by brace matching, against
     stub cells/shared strings. A stub ReadSheetData yields the cells the xlsb reader makes
     (inlineStr / str / str+formula with text in m_oValue, a number, a bool, an error). Then
     what sdkjs ReadCell does with a cell is applied: shared-string cell -> its text, any
     other non-error cell -> the number in its value (XmlUtils::GetDouble; text -> 0).
  2. only if RD_X2T=<x2t built from the tree under test> is set: x2t makes an xlsb with
     inline strings from an xlsx, converts it to a raw and to a base64 Editor.bin, and each
     back to csv (the C++ bin reader shows the same 0s). RD_FONTS: font cache dir (copied
     first, x2t may rewrite AllFonts.js); RD_X2T_LIBS: DYLD/LD path. With BASELINE=1 the
     x2t part uses RD_X2T_BASE instead (an x2t built from BASE_REF), or is skipped.
NOT claimed: error cells (they still open empty from an xlsb: the writer gives an error code,
sdkjs expects a shared-string index - separate defect); the embedded-workbook paths in
Pic.cpp/SmartArt.cpp were not run; the cell editor is not driven by this test (it was, by
hand, with fork-fix-tests/rd-0031-copy-sheet-new-workbook/cell_rt.js "open").

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0105 commit
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'f15d357a24^')
BASELINE = bool(os.environ.get('BASELINE'))
WRITER = 'OOXML/Binary/Sheets/Reader/BinaryWriterS.cpp'
XLSB = 'OOXML/XlsbFormat/Xlsb.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start, frm=0):
    """the statement beginning at `start`, through its brace-matched body (the REAL code)."""
    a = src.find(start, frm)
    if a < 0:
        return None, -1
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1], i + 1
        i += 1


HEAD = r"""
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
typedef unsigned char BYTE;
namespace BinXlsxRW { namespace c_oFileTypes { enum c_oFileTypes { XLSX = 1, CSV = 2, JSON = 3, XLSB = 4 }; } }
namespace SimpleTypes { namespace Spreadsheet { enum ECellTypeType { celltypeBool = 0, celltypeDate = 1, celltypeError = 2,
  celltypeInlineStr = 3, celltypeNumber = 4, celltypeSharedString = 5, celltypeStr = 6 }; } }
template<class T> struct nullable { T* p = NULL; bool IsInit() const { return p != NULL; } void Init() { if (!p) p = new T(); }
  T* operator->() const { return p; } };
namespace OOX { namespace Spreadsheet {
  struct CTypeV { SimpleTypes::Spreadsheet::ECellTypeType v; SimpleTypes::Spreadsheet::ECellTypeType GetValue() const { return v; }
    void SetValue(SimpleTypes::Spreadsheet::ECellTypeType t) { v = t; } };
  struct CText { std::wstring m_sText; std::wstring ToString() const { return m_sText; } };
  struct CSi { std::vector<CText*> m_arrItems; };
  struct CFormula {};
  struct CCell { nullable<CTypeV> m_oType; nullable<CText> m_oValue; nullable<CSi> m_oRichText; nullable<CFormula> m_oFormula; };
  struct CRow { std::vector<CCell*> m_arrItems; };
  struct CSheetData { std::vector<CRow*> m_arrItems; };
  struct CWorksheet { nullable<CSheetData> m_oSheetData; };
  struct CSharedStrings { std::vector<CSi*> m_arrItems; int m_nCount = 0;
    int AddSi(CSi* p) { m_arrItems.push_back(p); return m_nCount++; } };
  struct CXlsx { std::vector<CWorksheet*> m_arWorksheets; CSharedStrings* m_pSharedStrings = NULL;
    virtual ~CXlsx() {} void CreateSharedStrings() { m_pSharedStrings = new CSharedStrings(); } };
  struct CXlsb : CXlsx {
    void PrepareSi() {} void PrepareTableFormula() {}
    void ReadSheetData();
    void PrepareSheetStrings();
  };
} }
using namespace OOX::Spreadsheet;
static CCell* mk(SimpleTypes::Spreadsheet::ECellTypeType t, const wchar_t* v, bool hasType = true, bool f = false) {
  CCell* c = new CCell(); if (hasType) { c->m_oType.Init(); c->m_oType->SetValue(t); }
  c->m_oValue.Init(); c->m_oValue->m_sText = v; if (f) c->m_oFormula.Init(); return c; }
// the cells CCell::fromBin makes from an xlsb (SheetData.cpp): BrtCellSt, BrtFmlaString, BrtCellReal, BrtCellBool, BrtCellError
void CXlsb::ReadSheetData() {
  CWorksheet* ws = new CWorksheet(); ws->m_oSheetData.Init(); m_arWorksheets.push_back(ws);
  CRow* r = new CRow(); ws->m_oSheetData->m_arrItems.push_back(r);
  r->m_arrItems.push_back(mk(SimpleTypes::Spreadsheet::celltypeInlineStr, L"Name"));
  r->m_arrItems.push_back(mk(SimpleTypes::Spreadsheet::celltypeStr, L"plain str"));
  r->m_arrItems.push_back(mk(SimpleTypes::Spreadsheet::celltypeStr, L"Adax", true, true));
  r->m_arrItems.push_back(mk(SimpleTypes::Spreadsheet::celltypeNumber, L"10", false));
  r->m_arrItems.push_back(mk(SimpleTypes::Spreadsheet::celltypeBool, L"1"));
}
@@PREP@@
static void run(BYTE fileType, BYTE saveFileType) {
  CXlsx* pXlsx = new CXlsb();
  @@XLSB@@
  // what sdkjs ReadCell makes of each cell (Type: only bool/error/number/sharedString are known;
  // Value: shared string -> text index, otherwise the double WriteCell wrote, XmlUtils::GetDouble)
  std::string out;
  for (CCell* c : pXlsx->m_arWorksheets[0]->m_oSheetData->m_arrItems[0]->m_arrItems) {
    std::wstring s;
    if (c->m_oType.IsInit() && c->m_oType->GetValue() == SimpleTypes::Spreadsheet::celltypeSharedString) {
      int i = atoi(std::string(c->m_oValue->m_sText.begin(), c->m_oValue->m_sText.end()).c_str());
      s = (pXlsx->m_pSharedStrings && i >= 0 && i < (int)pXlsx->m_pSharedStrings->m_arrItems.size()) ? pXlsx->m_pSharedStrings->m_arrItems[i]->m_arrItems[0]->m_sText : L"?";
    } else {
      char buf[64]; snprintf(buf, sizeof buf, "%g", wcstod(c->m_oValue->m_sText.c_str(), NULL)); s = std::wstring(buf, buf + strlen(buf));
    }
    out += (out.empty() ? "" : ",") + std::string(s.begin(), s.end());
  }
  printf("%s\n", out.c_str());
}
int main(int argc, char** argv) {
  run(BinXlsxRW::c_oFileTypes::XLSB, argv[1][0] == 'j' ? BinXlsxRW::c_oFileTypes::JSON : BinXlsxRW::c_oFileTypes::XLSB);
  return 0;
}
"""


def run_extracted():
    w = read(WRITER)
    a = w.find('pXlsx->PrepareWorkbook();')
    xb, _ = block(w, 'if (fileType == BinXlsxRW::c_oFileTypes::XLSB)', a) if a >= 0 else (None, -1)
    if not xb or 'ReadSheetData' not in xb:
        sys.exit('XLSB block of BinaryFileWriter::Open not found - the extractor needs updating')
    x = read(XLSB)
    prep, _ = block(x, 'void OOX::Spreadsheet::CXlsb::PrepareSheetStrings()')
    if prep:
        prep = prep.replace('OOX::Spreadsheet::CXlsb::', 'CXlsb::')
    else:
        print('note: CXlsb::PrepareSheetStrings is not in this tree')
        prep = 'void CXlsb::PrepareSheetStrings() {}'
    code = HEAD.replace('@@PREP@@', prep).replace('@@XLSB@@', xb)
    work = tempfile.mkdtemp(prefix='rd0105-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', '-include', 'cstring', '-include', 'cwchar', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for tgt, want, label in (('bin', 'Name,plain str,Adax,10,1', 'xlsb -> Editor.bin: inlineStr, str, str formula result, number, bool as the editor reads them'),
                             ('json', 'json-unchanged', 'xlsb -> mail-merge JSON: cells left as read (its writer handles inline text)')):
        r = subprocess.run([exe, tgt], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        got = r.stdout.strip()
        if tgt == 'json':
            got = 'json-unchanged' if got == '0,0,0,10,1' else got
        ok = r.returncode == 0 and got == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s: %s%s' % (label, got, '' if ok else '  (want %r)' % want))
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'
SHEET = ('<row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c><c r="B1" t="inlineStr"><is><t>Score</t></is></c></row>'
         '<row r="2"><c r="A2" t="inlineStr"><is><t>Ada</t></is></c><c r="B2"><v>10</v></c></row>')


def make_xlsx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % (NS, SHEET))


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


def text(path, rc):
    if rc or not os.path.exists(path):
        return 'rc=%d' % rc
    return open(path, encoding='utf-8-sig').read().strip().replace('\r', '').replace('\n', ' | ')


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0105-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    xlsb = os.path.join(work, 'in.xlsb')
    fails = 0
    rc = x2t(exe, src, xlsb, 0x0108, work)
    if rc:
        print('FAIL x2t xlsx -> xlsb (setup): rc=%d' % rc)
        return 1
    want = 'Name,Score | Ada,10'
    for kind, extra in (('raw (desktop open)', ''), ('base64', '<m_bIsNoBase64>false</m_bIsNoBase64>')):
        eb = tempfile.mkdtemp(dir=work)
        rc = x2t(exe, xlsb, os.path.join(eb, 'Editor.bin'), 0x2002, work, extra)
        csv = os.path.join(eb, 'back.csv')
        rc = rc or x2t(exe, os.path.join(eb, 'Editor.bin'), csv, 0x0104, work)
        got = text(csv, rc); ok = got == want; fails += not ok
        print(('ok   ' if ok else 'FAIL ') + 'x2t inline-string xlsb -> %s Editor.bin -> csv: %s%s' % (kind, got, '' if ok else '  (want ' + want + ')'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


def main():
    fails = run_extracted()
    exe = os.environ.get('RD_X2T_BASE') if BASELINE else os.environ.get('RD_X2T')
    if exe:
        fails += run_x2t(exe)
    else:
        print('skip x2t end-to-end (set RD_X2T, and RD_X2T_BASE for BASELINE=1)')
    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', fails))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
