#!/usr/bin/env python3
"""
RD-0102 (found by corpus/fuzz testing of the spreadsheet converters; no upstream
issue): x2t crashed (SIGSEGV / SIGBUS) writing CSV or mail-merge JSON when a
cell's style index has no cellXfs entry:
  - an xlsx whose styles.xml is missing (named by its relationship, absent from
    the zip) while cells carry s="1" (cellXfs never read);
  - an xlsx whose cells say s="7" / s="300" with a 2-entry cellXfs.
Both crashed xlsx -> csv, xlsx -> json, and Editor.bin -> csv for the Editor.bin
x2t itself writes for such a file. The last one is the desktop's Save As CSV of
a document that was not edited: the save converts the open-time Editor.bin
(desktop-sdk fileconverter.h) and, with no changes to replay, x2t goes straight
to the CSV writer. A document edited first is rewritten by sdkjs with its own
consistent xf table and did not crash.
Beside it, t="s" in a workbook without a sharedStrings part read through a null
m_pSharedStrings (same crash, same paths).

Cause (OOXML/Binary/Sheets/Writer/CSVWriter.cpp, CSVWriter::Impl::WriteCell):
m_oXlsx.m_pStyles->m_oCellXfs->m_arrItems[*pCell->m_oStyle] with only m_pStyles
checked, and m_oXlsx.m_pSharedStrings->m_arrItems with no check at all.
Fix: the xf is looked up only when cellXfs exists and holds the index, the
shared string only when the part exists; otherwise the cell is written as an
unstyled value (what a cell without s gets).

What runs:
  1. the REAL CSVWriter::Impl::WriteCell, extracted by brace matching, against
     stub CXlsx/CStyles/CCell types shaped like core's (nullable<T>::operator->
     yields NULL when unset, as core's does; m_arrItems aborts on an index past
     its end instead of reading past the vector). GetDefaultFormatCode and
     ConvertValueCellToString are stubs: the latter returns value|format_code so
     the format the cell resolved to is visible. Run under ASan.
  2. only if RD_X2T=<x2t binary> is set (NOT built by this test): generated
     xlsx files (no styles.xml; s past cellXfs; t="s" without sharedStrings)
     converted by that x2t to csv, json, and to Editor.bin then csv (RD_FONTS:
     a font cache dir, copied first since x2t may rewrite AllFonts.js; DYLD/LD
     path from RD_X2T_LIBS). Not claimed without it.
NOT claimed: the desktop GUI was not driven; the unedited-save path was run with
docbuilder (same x2t call: open-time Editor.bin, empty changes) during the fix.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0102 commit
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'bbf0cb118d^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/Binary/Sheets/Writer/CSVWriter.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig):
    """sig ... its brace-matched body (the REAL code)."""
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
#include <map>
#include <string>
#include <vector>
#include <boost/optional.hpp>
#define _T(x) L##x
template<class T> struct nullable {       // core's nullable<T>: a pointer, NULL when unset
  T* p = NULL;
  bool IsInit() const { return p != NULL; }
  T* operator->() const { return p; }
  T& operator*() const { return *p; }
  void set(const T& v) { delete p; p = new T(v); }
};
struct nullable_uint { bool b = false; unsigned int v = 0; bool IsInit() const { return b; } unsigned int operator*() const { return v; } };
template<class T> struct Items {          // std::vector<T*>, but an index past the end is reported, not read
  std::vector<T*> v;
  size_t size() const { return v.size(); }
  T* operator[](size_t i) const {
    if (i >= v.size()) { fprintf(stderr, "READ PAST m_arrItems: index %zu of %zu\n", i, v.size()); abort(); }
    return v[i]; }
};
namespace SimpleTypes { namespace Spreadsheet { enum { celltypeBool = 0, celltypeDate = 1, celltypeError = 2, celltypeInlineStr = 3,
  celltypeNumber = 4, celltypeSharedString = 5, celltypeStr = 6, celltypeTime = 10, celltypeDateTime = 12 }; }
  struct COnOff { bool b; bool ToBool() const { return b; } };
  struct CNum { unsigned int n; unsigned int GetValue() const { return n; } };
  struct CType { int t; int GetValue() const { return t; } }; }
namespace XmlUtils { int GetInteger(const std::wstring& s) { return (int)wcstol(s.c_str(), NULL, 10); } }
namespace NSStringUtils { struct CStringBuilder { std::wstring s; void WriteString(const std::wstring& x) { s += x; }
  const wchar_t* GetBuffer() { return s.c_str(); } size_t GetCurSize() { return s.size(); } }; }
namespace NSStringExt { void Replace(std::wstring& s, const std::wstring& a, const std::wstring& b) {
  size_t i = 0; while ((i = s.find(a, i)) != std::wstring::npos) { s.replace(i, a.size(), b); i += b.size(); } } }
namespace NSFile { struct CFileBinary {}; }
namespace OOX { namespace Spreadsheet {
  struct CText { std::wstring s; std::wstring ToString() const { return s; } };
  struct CSi { std::wstring s; std::wstring ToString() const { return s; } };
  struct CFormula { std::wstring m_sText; };
  struct CXfs { nullable<SimpleTypes::COnOff> m_oApplyNumberFormat; nullable<SimpleTypes::CNum> m_oNumFmtId; };
  struct CCellXfs { Items<CXfs> m_arrItems; };
  struct CNumFmt { nullable<std::wstring> m_oFormatCode; };
  struct CNumFmts { std::map<unsigned int, size_t> m_mapNumFmtIndex; Items<CNumFmt> m_arrItems; };
  struct CStyles { nullable<CCellXfs> m_oCellXfs; nullable<CNumFmts> m_oNumFmts; };
  struct CSharedStrings { Items<CSi> m_arrItems; };
  struct CXlsx { CStyles* m_pStyles = NULL; CSharedStrings* m_pSharedStrings = NULL; };
  struct CCell {
    nullable_uint m_oStyle; nullable<SimpleTypes::CType> m_oType; nullable<CText> m_oValue;
    nullable<CFormula> m_oFormula; nullable<CSi> m_oRichText;
    bool isInitRef() const { return false; } bool getRowCol(int&, int&) const { return false; } };
} }
static std::wstring g_sQuote = _T("\""), g_sDoubleQuote = _T("\"\"");
static std::wstring g_out;
void WriteFile(NSFile::CFileBinary*, wchar_t**, int&, const std::wstring& s, unsigned int&, bool = false) { g_out += s; }
void escapeJson(const std::wstring& s, NSStringUtils::CStringBuilder& b) { b.WriteString(s); }
struct CSVWriter { struct Impl {
  OOX::Spreadsheet::CXlsx& m_oXlsx;
  Impl(OOX::Spreadsheet::CXlsx& x) : m_oXlsx(x) {}
  NSFile::CFileBinary m_oFile; wchar_t* m_pWriteBuffer = NULL; int m_nCurrentIndex = 0; unsigned int m_nCodePage = 0;
  std::wstring m_sDelimiter = L","; std::wstring m_sEscape = L"\",\n";
  bool m_bJSON = false, m_bShowFormulas = false, m_bIsWriteCell = false, m_bStartCell = true;
  int m_nColCurrent = 1, m_nColDimension = 0;
  void GetDefaultFormatCode(int, std::wstring&, boost::optional<int>&) {}
  std::wstring ConvertValueCellToString(const std::wstring& v, boost::optional<int>, std::wstring code) { return v + L"|" + code; }
  void WriteCell(OOX::Spreadsheet::CCell *pCell);
}; };
@@FN@@
static std::string narrow(const std::wstring& w) { std::string r; for (wchar_t c : w) r += (c < 128 ? (char)c : '?'); return r; }
using namespace OOX::Spreadsheet;
int main(int argc, char** argv) {
  // argv[1]: styles = none | noxfs | xfs2 ; argv[2]: sst = none | one ; argv[3]: s index or -1 ; argv[4]: t (n|s) ; argv[5]: value
  CXlsx x; std::string st = argv[1];
  if (st != "none") { x.m_pStyles = new CStyles;
    if (st == "xfs2") { x.m_pStyles->m_oCellXfs.set(CCellXfs());
      CXfs* a = new CXfs; a->m_oNumFmtId.set(SimpleTypes::CNum{0});
      CXfs* b = new CXfs; b->m_oNumFmtId.set(SimpleTypes::CNum{164}); b->m_oApplyNumberFormat.set(SimpleTypes::COnOff{true});
      x.m_pStyles->m_oCellXfs->m_arrItems.v = {a, b};
      x.m_pStyles->m_oNumFmts.set(CNumFmts()); CNumFmt* f = new CNumFmt; f->m_oFormatCode.set(L"0.00");
      x.m_pStyles->m_oNumFmts->m_arrItems.v = {f}; x.m_pStyles->m_oNumFmts->m_mapNumFmtIndex[164] = 0; } }
  if (std::string(argv[2]) == "one") { x.m_pSharedStrings = new CSharedStrings; CSi* s = new CSi; s->s = L"text"; x.m_pSharedStrings->m_arrItems.v = {s}; }
  CCell c; int s = atoi(argv[3]); if (s >= 0) { c.m_oStyle.b = true; c.m_oStyle.v = (unsigned)s; }
  c.m_oType.set(SimpleTypes::CType{argv[4][0] == 's' ? SimpleTypes::Spreadsheet::celltypeSharedString : SimpleTypes::Spreadsheet::celltypeNumber});
  std::wstring v; for (const char* p = argv[5]; *p; ++p) v += (wchar_t)*p; c.m_oValue.set(CText{v});
  CSVWriter::Impl w(x); w.WriteCell(&c);
  printf("%s\n", narrow(g_out).c_str());
  return 0;
}
"""

CASES = [
    # styles, sst, s, t, value, want, label
    ('xfs2', 'none', '1', 'n', '1000', '1000|0.00', 'valid s=1 (numFmt 164 "0.00") - unchanged'),
    ('xfs2', 'none', '-1', 'n', '5', '5|', 'no s - unchanged'),
    ('none', 'none', '1', 'n', '5', '5|', 'no styles part at all (m_pStyles NULL) - unchanged'),
    ('noxfs', 'none', '1', 'n', '1000', '1000|', 'styles without cellXfs, s=1 (xlsx without styles.xml)'),
    ('xfs2', 'none', '7', 'n', '2', '2|', 's=7 past a 2-entry cellXfs'),
    ('xfs2', 'none', '300', 'n', '3', '3|', 's=300 past a 2-entry cellXfs'),
    ('xfs2', 'one', '-1', 's', '0', 'text', 't="s" index 0 with a sharedStrings part - unchanged'),
    ('xfs2', 'none', '-1', 's', '0', '0|', 't="s" without a sharedStrings part'),
]


def run_extracted():
    src = read(REL)
    code = HEAD.replace('@@FN@@', func(src, 'void CSVWriter::Impl::WriteCell(OOX::Spreadsheet::CCell *pCell)'))
    work = tempfile.mkdtemp(prefix='rd0102-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    inc = []
    for root in (REPO, os.path.normpath(os.path.join(HERE, '..', '..', 'core'))):
        for plat in ('mac_arm64', 'linux_64'):
            d = os.path.join(root, 'Common', '3dParty', 'boost', 'build', plat, 'include')
            if os.path.isdir(d) and not inc:
                inc = ['-I', d]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w'] + inc + [p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for st, sst, s, t, v, want, label in CASES:
        r = subprocess.run([exe, st, sst, s, t, v], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        got = r.stdout.strip()
        ok = r.returncode == 0 and got == want
        fails += not ok
        err = ''
        if r.returncode:
            lines = [l for l in r.stderr.splitlines() if 'READ PAST' in l or 'ERROR: AddressSanitizer' in l]
            err = (lines[0] if lines else 'rc=%d' % r.returncode).strip()
        print(('ok   ' if ok else 'FAIL ') + '%s: %s%s' % (label, got if r.returncode == 0 else 'CRASH ' + err[:160],
              '' if ok else '  (want %r)' % want))
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'
STYLES = ('<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="%sspreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="0.00"/></numFmts>'
          '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill>'
          '<fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>' % NS)


def make_xlsx(path, sheet, styles):
    """styles: 'part' (cellXfs of 2), 'dangling' (the relationship and override name xl/styles.xml, the part is missing), None"""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>%s</Types>'
                    % (NS, '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' if styles else ''))
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>%s</Relationships>'
                    % (NS, NS, '<Relationship Id="rId2" Type="%sofficeDocument/2006/relationships/styles" Target="styles.xml"/>' % NS if styles else ''))
        if styles == 'part':
            z.writestr('xl/styles.xml', STYLES)
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % (NS, sheet))


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
    work = tempfile.mkdtemp(prefix='rd0102-x2t-')
    files = [
        ('nostyles', '<row r="1"><c r="A1" s="1"><v>1000</v></c><c r="B1" s="2"><v>2</v></c></row>', 'dangling', '1000,2'),
        ('badxf', '<row r="1"><c r="A1" s="1"><v>1000</v></c><c r="B1" s="7"><v>2</v></c><c r="C1" s="300"><v>3</v></c></row>', 'part', '1000.00,2,3'),
        ('nosst', '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>5</v></c></row>', None, '0,5'),
    ]
    fails = 0
    for name, sheet, styles, want in files:
        src = os.path.join(work, name + '.xlsx'); make_xlsx(src, sheet, styles)
        res = []
        out = os.path.join(work, name + '.csv'); rc = x2t(exe, src, out, 0x0104, work)
        res.append(('csv', rc, out, want))
        out = os.path.join(work, name + '.json'); rc = x2t(exe, src, out, 0x0808, work)
        res.append(('json', rc, out, '[["%s"]]' % want.replace(',', '","')))
        eb = os.path.join(work, name + '-eb'); os.mkdir(eb)
        rc = x2t(exe, src, os.path.join(eb, 'Editor.bin'), 0x2002, work)
        out = os.path.join(work, name + '.eb.csv'); rc = rc or x2t(exe, os.path.join(eb, 'Editor.bin'), out, 0x0104, work)
        res.append(('Editor.bin -> csv', rc, out, want))
        for k, rc, out, w in res:
            got = open(out, encoding='utf-8-sig').read().strip() if rc == 0 and os.path.exists(out) else 'rc=%d' % rc
            ok = got == w; fails += not ok
            print(('ok   ' if ok else 'FAIL ') + 'x2t %s xlsx -> %s: %s%s' % (name, k, got, '' if ok else '  (want ' + w + ')'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


def main():
    fails = run_extracted()
    if os.environ.get('RD_X2T'):
        fails += run_x2t(os.environ['RD_X2T'])
    else:
        print('skip x2t end-to-end (set RD_X2T to an x2t built from the tree under test)')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
