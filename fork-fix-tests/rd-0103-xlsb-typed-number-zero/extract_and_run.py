#!/usr/bin/env python3
"""
RD-0103 (found by corpus testing of Editor.bin round trips; no upstream issue):
every number of a TYPED cell was written to .xlsb as 0.
  - xlsx -> xlsb (x2t): a cell written <c r="A1" t="n"><v>11</v></c> - the
    explicit t="n" that openpyxl and many exporters emit - came out as 0; a
    formula cell with t="n" lost its cached result the same way.
  - base64 Editor.bin (XLSY;v2, m_bIsNoBase64=false) -> xlsb: the same cells
    0, since that bin keeps the source's t="n" (untyped numbers survive it).
The desktop's normal Save As xlsb converts a raw (v10) Editor.bin whose sheet
data is already XLSB records; it was run during the fix (x2t-written and
sdkjs-written bins) and was NOT affected.

Cause (OOXML/XlsxFormat/Worksheets/SheetData.cpp, CCell::toBin - both the
record-tree and the stream-writer variant): a celltypeNumber cell is written
from realCache, which only processCellType fills, and processCellType runs only
when m_oType is not set. A typed cell kept realCache = 0. (CCell::toXLS had the
missing else-branch.)
Fix: readNumberCache parses a typed number cell's stored text into realCache
and marks it a double - what processCellType gives an untyped number too.

What runs:
  1. the REAL type/realCache code of both CCell::toBin variants - the slice from
     `if(!m_oType.IsInit())` up to the cell-type switch, extracted from the
     source - together with the REAL processCellType and (fixed tree)
     readNumberCache, against stub nullable/CCellTypeType/CText. Each case is
     (t attribute or none, stored text) -> the realCache/isReal the record is
     written from.
  2. only if RD_X2T=<x2t binary> is set (NOT built by this test): a generated
     xlsx with t="n" cells and a t="n" formula converted by that x2t to xlsb and
     back to csv, and the same xlsx -> base64 Editor.bin -> xlsb -> csv
     (RD_FONTS: a font cache dir, copied first since x2t may rewrite AllFonts.js;
     DYLD/LD path from RD_X2T_LIBS). Not claimed without it.
NOT claimed: the desktop's encrypted (cloud crypto) "download as xlsb", which
also converts a base64 bin, was not driven.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0103 commit
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'fa18fad69d^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/XlsxFormat/Worksheets/SheetData.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig, required=True):
    """sig ... its brace-matched body (the REAL code)."""
    a = src.find(sig)
    if a < 0:
        if required:
            sys.exit(repr(sig) + ' not found - the extractor needs updating')
        return ''
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


def slice_in(src, fn_sig, start, end):
    """the REAL statements of function fn_sig from `start` up to (not including) `end`."""
    body = func(src, fn_sig)
    a = body.find(start)
    b = body.find(end, a)
    if a < 0 or b < 0:
        sys.exit('%r .. %r not found in %s - the extractor needs updating' % (start, end, fn_sig))
    return body[a:b]


HEAD = r"""
#include <algorithm>
#include <cctype>
#include <cfloat>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cwchar>
#include <string>
typedef long long _INT64;
#define MAXINT32 INT_MAX
#define MININT32 INT_MIN
template<class T> struct nullable {
  T* p = NULL;
  bool IsInit() const { return p != NULL; }
  void Init() { if (!p) p = new T(); }
  T* operator->() const { return p; }
  T& get() const { return *p; }
};
namespace SimpleTypes { namespace Spreadsheet {
  enum ECellTypeType { celltypeBool = 0, celltypeDate = 1, celltypeError = 2, celltypeInlineStr = 3, celltypeNumber = 4,
    celltypeSharedString = 5, celltypeStr = 6 };
  struct CCellTypeType { ECellTypeType v = celltypeNumber; ECellTypeType GetValue() const { return v; } void SetValue(ECellTypeType x) { v = x; } };
} }
struct CText { std::wstring m_sText; };
@@FN@@
struct CCell {
  nullable<SimpleTypes::Spreadsheet::CCellTypeType> m_oType;
  nullable<CText> m_oValue;
  void tree(bool& isReal, double& realCache) { @@TREE@@ }
  void stream(bool& isReal, double& realCache) { @@STREAM@@ }
};
int main(int argc, char** argv) {
  // argv: <variant tree|stream> <t: n | s | - (none)> <stored text>
  CCell c;
  if (argv[2][0] != '-') { c.m_oType.Init(); c.m_oType->SetValue(argv[2][0] == 'n' ? SimpleTypes::Spreadsheet::celltypeNumber : SimpleTypes::Spreadsheet::celltypeStr); }
  c.m_oValue.Init(); for (const char* s = argv[3]; *s; ++s) c.m_oValue->m_sText += (wchar_t)*s;
  bool isReal = false; double realCache = 0;
  if (argv[1][0] == 't') c.tree(isReal, realCache); else c.stream(isReal, realCache);
  printf("%s %.17g\n", c.m_oType->GetValue() == SimpleTypes::Spreadsheet::celltypeNumber ? (isReal ? "real" : "rk") : "other", realCache);
  return 0;
}
"""

CASES = [
    # t, text, want, label
    ('-', '11', 'real 11', 'untyped 11 (unchanged)'),
    ('-', '600.25', 'real 600.25', 'untyped 600.25 (unchanged)'),
    ('n', '11', 'real 11', 't="n" 11'),
    ('n', '-2.5', 'real -2.5', 't="n" -2.5'),
    ('n', '123456789012', 'real 123456789012', 't="n" 123456789012'),
    ('n', '1.5E+300', 'real 1.5000000000000001e+300', 't="n" 1.5E+300'),
    ('n', 'abc', 'rk 0', 't="n" with unparseable text: 0 as before'),
    ('s', 'abc', 'other 0', 't="str" (unchanged)'),
]


def run_extracted():
    src = read(REL)
    fns = func(src, 'const SimpleTypes::Spreadsheet::ECellTypeType processCellType(') + '\n' + \
        func(src, 'static void readNumberCache(', required=False)
    tree = slice_in(src, 'XLS::BaseObjectPtr CCell::toBin(sharedFormula &sharedFormulas)', 'if(!m_oType.IsInit())', 'switch (m_oType->GetValue())')
    stream = slice_in(src, 'void CCell::toBin(XLS::StreamCacheWriterPtr& writer)', 'if(!m_oType.IsInit())', 'auto cellType = m_oType->GetValue();')
    code = HEAD.replace('@@FN@@', fns).replace('@@TREE@@', tree).replace('@@STREAM@@', stream)
    work = tempfile.mkdtemp(prefix='rd0103-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for variant in ('tree', 'stream'):
        for t, text, want, label in CASES:
            r = subprocess.run([exe, variant, t, text], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
            got = r.stdout.strip()
            ok = r.returncode == 0 and got == want
            fails += not ok
            print(('ok   ' if ok else 'FAIL ') + 'toBin(%s) %s -> %s%s' % (variant, label, got or r.stderr.strip()[-200:],
                  '' if ok else '  (want %r)' % want))
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'
SHEET = ('<row r="1"><c r="A1" t="n"><v>11</v></c><c r="B1" t="n"><v>-2.5</v></c><c r="C1" t="n"><v>123456789012</v></c><c r="D1"><v>7</v></c></row>'
         '<row r="2"><c r="A2" t="n"><f>A1*2</f><v>22</v></c><c r="B2"><f>B1*2</f><v>-5</v></c></row>')
WANT = '11,-2.5,123456789012,7 | 22,-5,,'


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


def csv_of(exe, xlsb, work):
    out = xlsb + '.csv'
    rc = x2t(exe, xlsb, out, 0x0104, work)
    if rc or not os.path.exists(out):
        return 'rc=%d' % rc
    return open(out, encoding='utf-8-sig').read().strip().replace('\r', '').replace('\n', ' | ')


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0103-x2t-')
    src = os.path.join(work, 'typed.xlsx'); make_xlsx(src)
    fails = 0
    xlsb = os.path.join(work, 'direct.xlsb')
    rc = x2t(exe, src, xlsb, 0x0108, work)
    got = csv_of(exe, xlsb, work) if rc == 0 else 'rc=%d' % rc
    ok = got == WANT; fails += not ok
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx (t="n") -> xlsb -> csv: %s%s' % (got, '' if ok else '  (want ' + WANT + ')'))
    eb = os.path.join(work, 'eb'); os.mkdir(eb)
    rc = x2t(exe, src, os.path.join(eb, 'Editor.bin'), 0x2002, work, '<m_bIsNoBase64>false</m_bIsNoBase64>')
    xlsb = os.path.join(work, 'b64.xlsb')
    rc = rc or x2t(exe, os.path.join(eb, 'Editor.bin'), xlsb, 0x0108, work)
    got = csv_of(exe, xlsb, work) if rc == 0 else 'rc=%d' % rc
    ok = got == WANT; fails += not ok
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> base64 Editor.bin -> xlsb -> csv: %s%s' % (got, '' if ok else '  (want ' + WANT + ')'))
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
