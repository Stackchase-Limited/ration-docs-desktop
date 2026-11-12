#!/usr/bin/env python3
"""
RD-0014 (our corpus run, no upstream issue): opening an Excel 2003 XML
spreadsheet (SpreadsheetML, often saved as .xls/.xml) with a horizontally merged
cell in its first row crashed x2t (SIGSEGV); with the merge further down, the
extra cells went into the previous row.

Found on LibreOffice's sc/qa/unit/data/xls/fdo55572-1.xls (a SpreadsheetML file):
the release x2t dies with SIGSEGV, the AddressSanitizer x2t with SEGV in
CCell::After2003Read (OOXML/XlsxFormat/Worksheets/SheetData.cpp).

Cause: for SpreadsheetML, CRow::CheckIndex (gap rows before an ss:Index jump),
CCell::After2003Read (the cells a ss:MergeAcross adds) and
CSheetData::StyleFromMapStyleMerges2003 all reach "the row being read" as
sheet->m_oSheetData->m_arrItems.back() - CheckIndex even says `// == this` - but
CSheetData::fromXML pushes a row into m_arrItems only after CRow::fromXML has
returned. So back() was the previous row: merge cells and styled gap cells were
added to the wrong row, CheckIndex moved the previous row behind the gap rows,
and in the first row of a sheet back() of the empty vector was dereferenced.
Fix: CRow::fromXML makes the row back() of the sheet data while it is read
(pushed after ReadAttributes, popped again before every return), so all three
work on the row they were written for.

What runs: the REAL CRow::fromXML and CRow::CheckIndex are lifted out of
SheetData.cpp by brace matching (git show BASE_REF:... with BASELINE=1) and
compiled with -fsanitize=address against small stand-ins for the XML reader,
CXlsxFlat/CWorksheet/CSheetData and CCell. The CCell stand-in's fromXML does
what After2003Read does for ss:MergeAcross="1" (appends one cell to
sheet->m_oSheetData->m_arrItems.back()). CSheetData::fromXML's loop (read the row,
then push it) is mirrored by the driver. Two rows are read, each with one
merged cell. Passes when ASan reports nothing, both rows end up in order and
each row holds its own two cells.

NOT claimed: CCell::After2003Read itself is not compiled (it needs the styles,
hyperlink and merge-cell machinery); the stand-in reproduces only its
"append to back()" step. The fixed x2t opens fdo55572-1.xls.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read SheetData.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0014 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '973bbc4b78^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
    sys.exit('unbalanced braces after %r' % start)


DRIVER = r'''
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
namespace XmlUtils {
    /* a row is: <Row> then the names of its children; the reader walks them */
    struct CXmlLiteReader { std::vector<const char*> kids; size_t pos = 0; bool empty = false;
        bool IsEmptyNode() { return empty; } int GetDepth() { return 1; }
        bool ReadNextSiblingNode(int) { if (pos < kids.size()) { ++pos; return true; } return false; }
        const char* GetNameChar() { return kids[pos - 1]; } };
    inline const char* GetNameNoNS(const char* s) { const char* c = strchr(s, ':'); return c ? c + 1 : s; }
}
namespace OOX { namespace Spreadsheet {
    template<class T> struct nullable { T* p = nullptr; bool IsInit() const { return p != nullptr; } void Init() { if (!p) p = new T(); }
        T* operator->() const { return p; } T* GetPointer() const { return p; } nullable& operator=(const T& v) { Init(); *p = v; return *this; } };
    struct CUInt { unsigned int v = 0; CUInt() {} CUInt(int x) : v(x) {} unsigned int GetValue() const { return v; } void SetValue(unsigned int x) { v = x; } };
    struct Document { virtual ~Document() {} };
    struct CRow; struct CSheetData; struct CWorksheet; struct CXlsx;
    struct CSheetData { std::vector<CRow*> m_arrItems; std::map<int, std::map<int, unsigned int>> m_mapStyleMerges2003;
        void StyleFromMapStyleMerges2003(std::map<int, unsigned int>&) {} };
    struct CWorksheet { nullable<CSheetData> m_oSheetData; };
    struct CXlsx : Document { int m_nLastReadRow = -1, m_nLastReadCol = -1; };
    struct CXlsxFlat : Document { std::vector<CWorksheet*> m_arWorksheets; int m_nLastReadRow = -1, m_nLastReadCol = -1; };
    struct CCell { Document* m_pMainDocument; int col = 0, row = 0; CCell(Document* d) : m_pMainDocument(d) {}
        void fromXML(XmlUtils::CXmlLiteReader&); };
    struct CRow { Document* m_pMainDocument; nullable<CUInt> m_oR; std::vector<CCell*> m_arrItems;
        CRow(Document* d) : m_pMainDocument(d) {}
        void ReadAttributes(XmlUtils::CXmlLiteReader&) {}
        bool compressCell(CCell*) { return false; }
        void CheckIndex(); void fromXML(XmlUtils::CXmlLiteReader& oReader); };
    /* CCell::After2003Read for ss:MergeAcross="1": the merged-over cell is appended to the row being read */
    void CCell::fromXML(XmlUtils::CXmlLiteReader&) {
        CXlsxFlat* xlsx_flat = dynamic_cast<CXlsxFlat*>(m_pMainDocument);
        CWorksheet* sheet = xlsx_flat->m_arWorksheets.back();
        xlsx_flat->m_nLastReadCol++;
        row = xlsx_flat->m_nLastReadRow; col = xlsx_flat->m_nLastReadCol;
        CCell* pCell = new CCell(m_pMainDocument);
        xlsx_flat->m_nLastReadCol++;
        pCell->row = xlsx_flat->m_nLastReadRow; pCell->col = xlsx_flat->m_nLastReadCol;
        sheet->m_oSheetData->m_arrItems.back()->m_arrItems.push_back(pCell);
    }
@@CHECKINDEX@@
@@FROMXML@@
}}
using namespace OOX::Spreadsheet;
int main() {
    CXlsxFlat doc; CWorksheet ws; ws.m_oSheetData.Init(); doc.m_arWorksheets.push_back(&ws);
    for (int r = 0; r < 2; ++r) {            /* CSheetData::fromXML: read the row, then add it */
        XmlUtils::CXmlLiteReader rd; rd.kids.push_back("ss:Cell");
        CRow* pRow = new CRow(&doc);
        pRow->fromXML(rd);
        ws.m_oSheetData->m_arrItems.push_back(pRow);
    }
    for (CRow* r : ws.m_oSheetData->m_arrItems) {
        printf("ROW %u:", r->m_oR.IsInit() ? r->m_oR->GetValue() : 999);
        for (CCell* c : r->m_arrItems) printf(" (%d,%d)", c->row, c->col);
        printf("\n");
    }
    return 0;
}
'''


def main():
    src = read('OOXML/XlsxFormat/Worksheets/SheetData.cpp')
    chk = block(src, 'void CRow::CheckIndex()')
    frm = block(src, 'void CRow::fromXML(XmlUtils::CXmlLiteReader& oReader)')
    work = tempfile.mkdtemp(prefix='rd0014-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CHECKINDEX@@', chk).replace('@@FROMXML@@', frm))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    want = 'ROW 0: (0,1) (0,0)\nROW 1: (1,1) (1,0)'
    ok = r.returncode == 0 and not a and want in out
    print(('ok   ' if ok else 'FAIL ') + 'two SpreadsheetML rows with a merged cell each (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else ('each row holds its own cells' if ok else out.strip().replace('\n', ' | ')[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
