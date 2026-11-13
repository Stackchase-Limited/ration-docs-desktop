#!/usr/bin/env python3
"""
RD-0109 (found while checking x2t's xlsb writer for RD-0105; no upstream issue):
numbers written to .xlsb as TEXT. Any number cell without an explicit type whose text has 17 or
more characters and whose magnitude is above 15 - e.g. -25.780000000000001, which is what
SpreadsheetCommon::WriteDouble makes of -25.78 - was written as an inline string (BrtCellSt).
Hit by xlsx -> xlsb when the xlsx stores full precision, and by every Editor.bin -> xlsb (the
binary's numbers are doubles, turned back into text with WriteDouble) - i.e. Save As .xlsb.
In the corpus: 25.78 / -25.78 / 1234.56-style values came back as text cells.

Cause: OOXML/XlsxFormat/Common.cpp had `#define DBL_MAX 15` (meant as a digit count, next to
DBL_MAXDIG10 17). The Linux/mac core build is a unity build - DocxFormatLib/xlsx_format_logic.cpp
includes Common.cpp and then Worksheets/SheetData.cpp - so <cfloat>'s DBL_MAX was 15 in
processCellType, whose long-number branches check `tempVal <= DBL_MAX && tempVal >= -DBL_MAX`:
|value| > 15 failed and the cell kept celltypeStr. (Seen in the shipped x2t's code: the compare
is against 15.0.) Fix: the unused DBL_MAX macro is gone from Common.cpp.

What runs: the REAL top of Common.cpp (its includes stubbed, through the macros) followed by the
REAL processCellType from SheetData.cpp, in that order - as the unity file compiles them - on
WriteDouble-style texts; checked: each is classified as a number with the right value.
Also, only if RD_X2T is set (an x2t built from the tree under test; RD_X2T_BASE with
BASELINE=1): an xlsx whose cells hold such full-precision texts is converted to xlsb and back
to xlsx; checked: no cell came back as an inline string. RD_FONTS / RD_X2T_LIBS as in rd-0105.
NOT claimed: the desktop's own Save As .xlsb (JS-written Editor.bin) was not driven; it goes
through the same processCellType (Editor.bin -> xlsb via x2t was run).

  RD_REPO=<core checkout> (default ../../core); BASELINE=1 reads BASE_REF and must FAIL.
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
BASE_REF = os.environ.get('BASE_REF', 'aa16ec2c0d^')
BASELINE = bool(os.environ.get('BASELINE'))


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


VALUES = ['-25.780000000000001', '25.780000000000001', '1234.5599999999999', '-0.25600000000000001',
          '0.10000000000000001', '123456789012.12346', '1.5', '-25.78']

DRIVER = r"""
#include <cstdio>
#include <cstdlib>
#include <climits>
#include <cwchar>
#include <cfloat>
#include <string>
#include <algorithm>
typedef long long _INT64;
#ifndef MAXINT32
#define MAXINT32 INT_MAX
#define MININT32 INT_MIN
#endif
namespace SimpleTypes { namespace Spreadsheet { enum ECellTypeType { celltypeBool = 0, celltypeDate = 1, celltypeError = 2,
  celltypeInlineStr = 3, celltypeNumber = 4, celltypeSharedString = 5, celltypeStr = 6 }; } }
// ---- REAL Common.cpp, after the licence comment up to WriteDouble (#include lines dropped) ----
@@COMMON@@
// ---- REAL processCellType (SheetData.cpp), compiled after it as in xlsx_format_logic.cpp ----
@@FN@@
int main(int argc, char** argv) {
  for (int i = 1; i < argc; ++i) {
    std::string s(argv[i]); std::wstring w(s.begin(), s.end()); bool isReal = false; double v = 0;
    int t = processCellType(w, isReal, v);
    printf("%s %s %.17g\n", argv[i], t == SimpleTypes::Spreadsheet::celltypeNumber ? "number" : "TEXT", v);
  }
  return 0;
}
"""


def run_extracted():
    common = read('OOXML/XlsxFormat/Common.cpp')
    a = common.find('*/') + 2
    b = common.find('std::wstring OOX::Spreadsheet::SpreadsheetCommon::WriteDouble')
    if a < 0 or b < 0:
        sys.exit('Common.cpp layout changed - the extractor needs updating')
    top = '\n'.join(l for l in common[a:b].splitlines() if not l.strip().startswith('#include'))
    fn = block(read('OOXML/XlsxFormat/Worksheets/SheetData.cpp'), 'const SimpleTypes::Spreadsheet::ECellTypeType processCellType(')
    work = tempfile.mkdtemp(prefix='rd0109-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@COMMON@@', top).replace('@@FN@@', fn))
    r = subprocess.run(['c++', '-std=gnu++11', '-O2', '-w', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    out = subprocess.run([p[:-4]] + VALUES, capture_output=True, text=True).stdout.split('\n')
    fails = 0
    for line, v in zip(out, VALUES):
        parts = line.split()
        ok = len(parts) == 3 and parts[1] == 'number' and float(parts[2]) == float(v)
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + 'processCellType(%s): %s' % (v, ' '.join(parts[1:])))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'


def make_xlsx(path):
    cells = ''.join('<c r="%s1"><v>%s</v></c>' % (chr(65 + i), v) for i, v in enumerate(VALUES))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData><row r="1">%s</row></sheetData></worksheet>' % (NS, cells))


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


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0109-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    xlsb = os.path.join(work, 'out.xlsb'); back = os.path.join(work, 'back.xlsx')
    rc = x2t(exe, src, xlsb, 0x0108, work) or x2t(exe, xlsb, back, 0x0101, work)
    if rc:
        print('FAIL x2t xlsx -> xlsb -> xlsx: rc=%d' % rc)
        return 1
    xml = zipfile.ZipFile(back).read('xl/worksheets/sheet1.xml').decode('utf-8')
    text = re.findall(r'<c r="([A-Z]+1)"[^>]*t="inlineStr"', xml)
    ok = not text
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> xlsb -> xlsx: cells written as text: %s' % (', '.join(text) or 'none'))
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
