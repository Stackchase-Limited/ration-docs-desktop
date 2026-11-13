#!/usr/bin/env python3
"""
RD-0108 (found by corpus determinism checks; no upstream issue): a spreadsheet colour given as
rgb="RRGGBB" (6 digits, no alpha - common in xlsx styles, e.g. every border colour of POI's
52348.xlsx) was written to the Editor.bin (and xlsb/xlsx output) with a random alpha byte: the
same file gave a different Editor.bin on different runs (byte 5935 of 52348's: 0x64, 0x90, 0x00, 0x01).

Cause: SimpleTypes::Spreadsheet::CHexColor (OOXML/Common/SimpleTypes_Spreadsheet.cpp). Its
string constructors call FromString/Parse without initialising the members; Parse sets m_unA
only for 8 digits, and sets nothing at all for a string of another length (Parse still returns
true, so FromString's fallback does not run). Fix: the string constructors start from opaque
black, and Parse makes a 3- or 6-digit colour opaque.

What runs: the REAL CHexColor class (header) and its constructors, FromString, Parse, HexToInt,
ToInt (what the writers write; Get_A always says 255) (source), extracted by brace matching; each colour is constructed from a string in
memory filled with 0xAA (heap garbage). Checked: alpha 255 for "FF0000"/"F00"/"#00FF00", the
8-digit alpha kept, and a 5-character string gives opaque black (not garbage).
Also, only if RD_X2T is set (RD_X2T_BASE with BASELINE=1): an xlsx whose border colour is
rgb="FF0000" is converted to an Editor.bin three times, twice with MallocPreScribble=1 and once
without; checked: identical. RD_FONTS / RD_X2T_LIBS as in rd-0105.
NOT claimed: CHexColor's operator= on an existing colour (keeps the old alpha for 8 digits only).

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
BASE_REF = os.environ.get('BASE_REF', '5eb8c13c86^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start, semicolon=False):
    a = src.find(start)
    if a < 0:
        sys.exit(repr(start) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1] + (';' if semicolon else '')
        i += 1


DRIVER = r"""
#include <cstdio>
#include <cstring>
#include <string>
#include <new>
namespace SimpleTypes { namespace Spreadsheet {
@@CLASS@@
@@FNS@@
} }
using SimpleTypes::Spreadsheet::CHexColor;
int main(int argc, char** argv) {
  for (int i = 1; i < argc; ++i) {
    std::string s(argv[i]); std::wstring w(s.begin(), s.end());
    alignas(CHexColor) unsigned char mem[sizeof(CHexColor)]; memset(mem, 0xAA, sizeof mem);
    CHexColor* c = new (mem) CHexColor(w);
    printf("%s %08X\n", argv[i], (unsigned)c->ToInt());   // what the Editor.bin / xlsb writers write
  }
  return 0;
}
"""
CASES = [('FF0000', 'FFFF0000'), ('F00', 'FFFF0000'), ('#00FF00', 'FF00FF00'), ('80112233', '80112233'), ('12345', 'FF000000')]


def run_extracted():
    h = read('OOXML/Common/SimpleTypes_Spreadsheet.h')
    cls = block(h, 'class CHexColor', True)
    c = read('OOXML/Common/SimpleTypes_Spreadsheet.cpp')
    names = ['CHexColor::CHexColor()', 'CHexColor::CHexColor(unsigned char r', 'CHexColor::CHexColor(std::wstring & cwsValue)',
             'void CHexColor::FromString(const std::wstring &sValue)', 'CHexColor::CHexColor(const std::wstring& wsStr)',
             'bool CHexColor::Parse(', 'CHexColor::HexToInt(', 'int CHexColor::ToInt() const']
    fns = []
    for n in names:
        f = block(c, n)
        if n == 'CHexColor::HexToInt(':   # its return type sits before the name
            f = 'int ' + f
        fns.append(f)
    # members not extracted are declared but unused; give the virtual ToString a body
    fns.append('std::wstring CHexColor::ToString() const { return L""; }')
    work = tempfile.mkdtemp(prefix='rd0108-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CLASS@@', cls).replace('@@FNS@@', '\n'.join(fns)))
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    out = dict(l.split(' ') for l in subprocess.run([p[:-4]] + [k for k, _ in CASES], capture_output=True, text=True).stdout.split('\n') if l)
    fails = 0
    for k, want in CASES:
        ok = out.get(k) == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + 'CHexColor(L"%s") over 0xAA memory: ToInt %s%s' % (k, out.get(k), '' if ok else '  (want %s)' % want))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'
STYLES = ('<styleSheet xmlns="%sspreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="2"><border/>'
          '<border><left style="thin"><color rgb="FF0000"/></left><right style="thin"><color rgb="00FF00"/></right><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/></cellXfs></styleSheet>' % NS)


def make_xlsx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="%sofficeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' % (NS, NS, NS))
        z.writestr('xl/styles.xml', STYLES)
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" s="1"><v>1</v></c></row></sheetData></worksheet>' % NS)


def x2t(exe, src, dst, fmt, work, env_extra=None):
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
    env = dict(os.environ, **(env_extra or {}))
    if os.environ.get('RD_X2T_LIBS'):
        env['DYLD_FRAMEWORK_PATH'] = env['LD_LIBRARY_PATH'] = os.environ['RD_X2T_LIBS']
    return subprocess.run([exe, p], capture_output=True, env=env, timeout=120).returncode


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0108-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    bins = []
    for k, env in (('a', {'MallocPreScribble': '1'}), ('b', None), ('c', {'MallocPreScribble': '1', 'MallocScribble': '1'})):
        d = os.path.join(work, k); os.mkdir(d)
        rc = x2t(exe, src, os.path.join(d, 'Editor.bin'), 0x2002, work, env)
        bins.append(open(os.path.join(d, 'Editor.bin'), 'rb').read() if not rc else b'rc=%d' % rc)
    ok = bins[0] == bins[1] == bins[2] and not bins[0].startswith(b'rc=')
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx (rgb="FF0000" border) -> Editor.bin, 3 runs (2 scribbled): %s' % ('identical' if ok else 'differ'))
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
