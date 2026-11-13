#!/usr/bin/env python3
"""
RD-0090 (found while testing mail merge, no upstream issue): an .xlsx whose
text cells are inline strings (t="inlineStr", <is><t>..</t></is>) and which
has no sharedStrings part - what x2t's own csv -> xlsx writes, and openpyxl
write-only mode and many exporters - lost or duplicated its text whenever x2t
read it through the full OOXML model:
  - xlsx -> mail-merge JSON (0x0808): [["Name"],["Ada Lovelace","","10"],...]
  - xlsx -> ods: the same cells empty
  - xlsx -> Editor.bin with m_bIsNoBase64=false (the desktop's
    convert_local_file / "send to" conversions): Name,Name,Name and
    "Ada Lovelace,Ada Lovelace,10" - the first cell's text copied over the rest.
The normal editor open (Editor.bin, streaming XLSB path) was not affected.

Cause (OOXML/XlsxFormat/Worksheets/SheetData.cpp, CRow::compressCell): while a
row is read, a cell with neither m_oValue nor m_oFormula is folded into the
previous cell as a repeat (m_oRepeated) - meant for runs of empty styled cells.
Without a sharedStrings part, CCell::AfterRead cannot move an inline string
into m_oValue during reading (PrepareWorksheet does it afterwards), so such a
cell has only m_oRichText and was taken for empty: B1 and C1 became "A1
repeated 3 times". CSVWriter (json) ignores the repeat, so they vanished;
BinaryWorksheetTableWriter::WriteCells expands it, copying A1 into B1 and C1.
The same check on the PREVIOUS cell let an empty cell become a repeat of an
inline-string or formula-only cell.
Fix: a cell with m_oRichText is not empty, and a cell is only repeated when the
previous one has no value, formula or inline text either.

What runs:
  1. the REAL CRow::compressCell, extracted by brace matching, against stub
     CCell/CRow/nullable types, fed cells the way CRow::fromXML does (push the
     cell unless compressCell folded it). Cells are as CCell::fromXML leaves
     them: col set, m_oRichText only for an inline string (no sharedStrings).
  2. only if RD_X2T=<x2t binary> is set (it is NOT built by this test): a
     generated 3x3 inline-string xlsx converted to JSON and to base64
     Editor.bin -> csv by that x2t (RD_FONTS: a font cache dir, copied to a
     temp dir first since x2t may rewrite AllFonts.js; DYLD/LD path from
     RD_X2T_LIBS). Not claimed without it.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0090 commit
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '012cb19776^')
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


HEAD = r"""
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
template<class T> struct nullable {
  bool b = false; T v = T();
  bool IsInit() const { return b; }
  T get() const { return v; }
  void reset() { b = false; }
  nullable& operator=(T x) { v = x; b = true; return *this; }
};
struct CText {};
struct CFormula {};
struct CCell {
  nullable<int> m_oCol, m_oStyle, m_oRepeated;
  nullable<int> m_oValue;       // stands for nullable<CText> / its presence
  nullable<int> m_oFormula;     // nullable<CFormula>
  nullable<int> m_oRichText;    // nullable<CSi>: an <is> inline string
};
struct CRow { std::vector<CCell*> m_arrItems; bool compressCell(CCell* pCell); };
@@FN@@
int main(int argc, char** argv) {
  // each char is one cell of a row, columns 0,1,2..: i inline string, v value, f formula only, - empty (styled)
  const char* row = argv[1];
  CRow r;
  for (int c = 0; row[c]; ++c) {
    CCell* p = new CCell; p->m_oCol = c;
    if (row[c] == 'i') p->m_oRichText = 1;
    if (row[c] == 'v') p->m_oValue = 1;
    if (row[c] == 'f') p->m_oFormula = 1;
    if (!r.compressCell(p)) r.m_arrItems.push_back(p); else delete p;  // as CRow::fromXML
  }
  std::string out;
  for (CCell* p : r.m_arrItems) {
    char b[64];
    const char* k = p->m_oRichText.IsInit() ? "is" : p->m_oValue.IsInit() ? "v" : p->m_oFormula.IsInit() ? "f" : "-";
    snprintf(b, sizeof b, "%s%d:%s", out.empty() ? "" : " ", p->m_oCol.get(), k);
    out += b;
    if (p->m_oRepeated.IsInit()) { snprintf(b, sizeof b, "*%d", p->m_oRepeated.get()); out += b; }
  }
  printf("%s\n", out.c_str());
  return 0;
}
"""

CASES = [
    ('iii', 'three inline strings, no sharedStrings part (x2t csv->xlsx header row)', '0:is 1:is 2:is'),
    ('iiv', 'inline, inline, number', '0:is 1:is 2:v'),
    ('i-', 'inline string then an empty styled cell (must not repeat the text)', '0:is 1:-'),
    ('f-', 'formula without cached value then an empty cell (must not repeat the formula)', '0:f 1:-'),
    ('---', 'three empty styled cells: still compressed (unchanged)', '0:-*3'),
    ('v--', 'value then two empty cells: still compressed (unchanged)', '0:v 1:-*2'),
]


def run_extracted():
    src = read('OOXML/XlsxFormat/Worksheets/SheetData.cpp')
    code = HEAD.replace('@@FN@@', func(src, 'bool CRow::compressCell(CCell* pCell)'))
    work = tempfile.mkdtemp(prefix='rd0090-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, label, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        got = r.stdout.strip()
        ok = r.returncode == 0 and got == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s%s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              got or r.stderr.strip()[-200:], '' if ok else '  (want ' + want + ')'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


def make_inline_xlsx(path):
    rows = [['Name', 'City', 'Score'], ['Ada Lovelace', 'London', 10], ['Alan Turing', 'Wilmslow', 20]]
    xml = []
    for n, row in enumerate(rows, 1):
        cs = []
        for c, v in enumerate(row):
            ref = 'ABC'[c] + str(n)
            cs.append('<c r="%s"><v>%s</v></c>' % (ref, v) if isinstance(v, int) else
                      '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, v))
        xml.append('<row r="%d">%s</row>' % (n, ''.join(cs)))
    ns = 'http://schemas.openxmlformats.org/'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % ns)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (ns, ns))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (ns, ns))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (ns, ns))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % (ns, ''.join(xml)))


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
    work = tempfile.mkdtemp(prefix='rd0090-x2t-')
    src = os.path.join(work, 'inline.xlsx'); make_inline_xlsx(src)
    fails = 0
    js = os.path.join(work, 'out.json')
    rc = x2t(exe, src, js, 0x0808, work)
    got = open(js, encoding='utf-8-sig').read().strip() if rc == 0 and os.path.exists(js) else 'rc=%d' % rc
    want = '[["Name","City","Score"],["Ada Lovelace","London","10"],["Alan Turing","Wilmslow","20"]]'
    ok = got == want; fails += not ok
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> mail-merge json: ' + got)
    eb = os.path.join(work, 'eb'); os.mkdir(eb)
    rc = x2t(exe, src, os.path.join(eb, 'Editor.bin'), 0x2002, work, '<m_bIsNoBase64>false</m_bIsNoBase64>')
    csv = os.path.join(work, 'back.csv')
    rc = rc or x2t(exe, os.path.join(eb, 'Editor.bin'), csv, 0x0104, work)
    got = open(csv, encoding='utf-8-sig').read().strip().replace('\r', '').replace('\n', ' | ') if rc == 0 and os.path.exists(csv) else 'rc=%d' % rc
    want = 'Name,City,Score | Ada Lovelace,London,10 | Alan Turing,Wilmslow,20'
    ok = got == want; fails += not ok
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> Editor.bin (base64, desktop convert_local_file) -> csv: ' + got)
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
