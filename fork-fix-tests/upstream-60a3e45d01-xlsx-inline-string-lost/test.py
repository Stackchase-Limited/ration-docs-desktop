#!/usr/bin/env python3
"""
Upstream 60a3e45d01 (ONLYOFFICE bug #82349), backported for 2026.3.1:
inline-string cell text was lost when saving to xlsx.

CCell::toXML2 (OOXML/XlsxFormat/Worksheets/SheetData.cpp) wrote <is> only for a cell holding rich
text; a cell of type inlineStr whose text sat in m_oValue - every inline string read from an
.xlsb (BrtCellSt) - came out as <c t="inlineStr"><v>Name</v></c>. Excel "repairs" such a file
and the text is gone. Fix: an inlineStr cell writes <is><t>text</t></is>.
Not the same path as RD-0090 (xlsx inline strings folded on open) or RD-0105 (xlsb inline
strings opened as 0 in the editor).

What runs - the REAL x2t: an xlsx with inline strings (Name/Score/Ada) and a number ->
.xlsb (x2t writes BrtCellSt cells) -> .xlsx, the direct xlsb->xlsx conversion. The sheet XML
of the result must have every inline-string cell as <is><t>..</t></is> with its text, no
inlineStr cell with a <v>, and the number as <v>10</v>.

  RD_X2T=<x2t>         (default ../../core/build/bin/mac_arm64/x2t; frameworks beside it or in
                        ../../core/build/lib/mac_arm64, or RD_X2T_LIBS)
  BASELINE=1           use RD_X2T_BASE (default .rd-work/mac-2026.3.0/payload/converter/x2t,
                        v2026.3.0 = aa16ec2c0d); must FAIL
  RD_FONTS             font cache (default .rd-work/fonts-cache; copied first)
Exit 77 (skip) without x2t or fonts.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RDWORK = os.path.normpath(os.path.join(ROOT, '..', '.rd-work'))
BASELINE = bool(os.environ.get('BASELINE'))
X2T = (os.environ.get('RD_X2T_BASE') or os.path.join(RDWORK, 'mac-2026.3.0', 'payload', 'converter', 'x2t')) if BASELINE \
    else (os.environ.get('RD_X2T') or os.path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64', 'x2t'))
FONTS = os.environ.get('RD_FONTS') or os.path.join(RDWORK, 'fonts-cache')
FMT_XLSX, FMT_XLSB = 0x0101, 0x0108
NS = 'http://schemas.openxmlformats.org/'
SHEET = ('<row r="1"><c r="A1" t="inlineStr"><is><t>Name</t></is></c><c r="B1" t="inlineStr"><is><t>Score</t></is></c></row>'
         '<row r="2"><c r="A2" t="inlineStr"><is><t>Ada &amp; Bob</t></is></c><c r="B2"><v>10</v></c></row>')

failures = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def libs():
    if os.environ.get('RD_X2T_LIBS'):
        return os.environ['RD_X2T_LIBS']
    d = os.path.dirname(X2T)
    if os.path.isdir(os.path.join(d, 'kernel.framework')):
        return d
    return os.path.normpath(os.path.join(d, '..', '..', 'lib', 'mac_arm64'))


def make_xlsx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % (NS, SHEET))


def x2t(src, dst, fmt, work, fonts):
    td = tempfile.mkdtemp(dir=work)
    p = os.path.join(td, 'params.xml')
    open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>'
                       '<m_nFormatTo>%d</m_nFormatTo><m_sFontDir>%s</m_sFontDir><m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath>'
                       '<m_sTempDir>%s</m_sTempDir></TaskQueueDataConvert>' % (src, dst, fmt, fonts, fonts, td))
    l = libs()
    r = subprocess.run([X2T, p], capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, DYLD_FRAMEWORK_PATH=l, DYLD_LIBRARY_PATH=l))
    if r.returncode or not os.path.exists(dst):
        sys.exit('x2t failed (%d) -> %s\n%s%s' % (r.returncode, dst, r.stdout[-800:], r.stderr[-800:]))


def main():
    for p, what in ((X2T, 'x2t'), (os.path.join(FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('x2t: %s%s' % (X2T, '  (BASELINE)' if BASELINE else ''))
    work = tempfile.mkdtemp(prefix='up60a3e4-')
    try:
        fonts = os.path.join(work, 'fonts')
        shutil.copytree(FONTS, fonts)
        src, xlsb, out = (os.path.join(work, n) for n in ('in.xlsx', 'mid.xlsb', 'out.xlsx'))
        make_xlsx(src)
        x2t(src, xlsb, FMT_XLSB, work, fonts)
        x2t(xlsb, out, FMT_XLSX, work, fonts)
        with zipfile.ZipFile(out) as z:
            sheet = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
        cells = dict(re.findall(r'<c r="([A-Z]+\d+)"[^>]*?(?:/>|>(.*?)</c>)', sheet))
        print('cells: %s' % cells)
        for ref, txt in (('A1', 'Name'), ('B1', 'Score'), ('A2', 'Ada &amp; Bob')):
            check(cells.get(ref) == '<is><t>%s</t></is>' % txt or cells.get(ref, '').startswith('<is><t xml:space="preserve">%s</t>' % txt),
                  '%s keeps its text as <is><t>%s</t></is>' % (ref, txt))
        check(not re.search(r't="inlineStr"[^>]*><v>', sheet), 'no inlineStr cell written with a <v>')
        check(cells.get('B2') == '<v>10</v>', 'the number cell is still <v>10</v>')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('FAIL: %d check(s) failed' % len(failures))
        sys.exit(1)
    print('PASS: upstream 60a3e45d01 xlsb -> xlsx keeps inline-string text')


if __name__ == '__main__':
    main()
