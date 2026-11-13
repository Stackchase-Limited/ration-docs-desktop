#!/usr/bin/env python3
"""
RD-0107 (found by corpus determinism checks; no upstream issue): every .xlsb written from a sheet
with a sort condition (<sortState><sortCondition .../>, autofilter sorts) got 8 uninitialised
bytes in its BrtBeginSortCond record - POI's 56644.xlsx -> xlsb differed on every run in record
532 of sheet2.bin ('aaaaaaaaaaaaaaaa' under -ftrivial-auto-var-init=pattern, 0s under =zero).

Cause: XLS::CondDataValue (MsBinaryFile/XlsFile/Format/Logic/Biff_structures/BitMarkedStructs.h)
is a plain struct of two _UINT32; it is written whole (record << condDataValue), and
CSortCondition::toBin (OOXML/XlsxFormat/Table/Autofilter.cpp: the stream writer's local, and the
BeginSortCond record object) sets condDataValue only for a sort by cell/font colour and never
sets `reserved`. Fix: both members default to 0 (as DXFNumIFmt in the same header does).

What runs: the REAL struct, extracted by brace matching, default-constructed (a) on a stack
compiled with -ftrivial-auto-var-init=pattern (as uninitialised stack reads look) and (b) by
placement new into memory filled with 0xAA (heap garbage, as in a BeginSortCond record object).
Checked: all 8 bytes are 0.
Also, only if RD_X2T is set (RD_X2T_BASE with BASELINE=1): an xlsx with a value sortCondition is
converted to xlsb three times; checked: the BrtBeginSortCond records are identical and their
condDataValue bytes are 0. RD_FONTS / RD_X2T_LIBS as in rd-0105.
NOT claimed: sort by icon (writes condDataValue where MS-XLSB has a CFFlag, whose `long` member is
8 bytes on macOS/Linux and 4 on Windows - separate, not changed).

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
BASE_REF = os.environ.get('BASE_REF', '3146952efa^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/XlsFile/Format/Logic/Biff_structures/BitMarkedStructs.h'


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
            if depth == 0: return src[a:i + 1] + ';'
        i += 1


DRIVER = r"""
#include <cstdio>
#include <cstring>
#include <new>
typedef unsigned int _UINT32;
@@STRUCT@@
static void dump(const char* what, const void* p) {
  const unsigned char* b = (const unsigned char*)p; printf("%s ", what);
  for (size_t i = 0; i < sizeof(CondDataValue); ++i) printf("%02x", b[i]); printf("\n"); }
__attribute__((noinline)) static void onStack() { CondDataValue v; dump("stack", &v); }
int main() {
  onStack();
  alignas(CondDataValue) unsigned char mem[sizeof(CondDataValue)]; memset(mem, 0xAA, sizeof mem);
  CondDataValue* h = new (mem) CondDataValue; dump("heap", h);
  return 0;
}
"""


def run_extracted():
    st = block(read(REL), 'struct CondDataValue')
    work = tempfile.mkdtemp(prefix='rd0107-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@STRUCT@@', st))
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-ftrivial-auto-var-init=pattern', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    out = dict(l.split(' ') for l in subprocess.run([p[:-4]], capture_output=True, text=True).stdout.split('\n') if l)
    fails = 0
    for k, label in (('stack', 'CondDataValue local (stack, pattern-filled)'), ('heap', 'CondDataValue in 0xAA memory')):
        ok = out.get(k) == '0' * 16
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s: %s' % (label, out.get(k)))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'


def make_xlsx(path):
    sheet = ('<sheetData><row r="1"><c r="A1"><v>3</v></c></row><row r="2"><c r="A2"><v>1</v></c></row><row r="3"><c r="A3"><v>2</v></c></row></sheetData>'
             '<autoFilter ref="A1:A3"><sortState ref="A2:A3"><sortCondition ref="A2:A3"/></sortState></autoFilter>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main">%s</worksheet>' % (NS, sheet))


def records(data):
    i = 0; out = []
    while i < len(data):
        t = data[i]; i += 1
        if t & 0x80: t = (t & 0x7f) | ((data[i] & 0x7f) << 7); i += 1
        n = 0; sh = 0
        for _ in range(4):
            b = data[i]; i += 1; n |= (b & 0x7f) << sh; sh += 7
            if not b & 0x80: break
        out.append((t, data[i:i + n])); i += n
    return out


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
    work = tempfile.mkdtemp(prefix='rd0107-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    got = []
    for k in range(3):
        o = os.path.join(work, '%d.xlsb' % k)
        rc = x2t(exe, src, o, 0x0108, work)
        if rc:
            print('FAIL x2t xlsx -> xlsb: rc=%d' % rc)
            return 1
        got.append([b for t, b in records(zipfile.ZipFile(o).read('xl/worksheets/sheet1.bin')) if t == 532])
    # flags(2) rfx(16) condDataValue(8) ...
    cdv = [r[0][18:26].hex() if r else 'none' for r in got]
    ok = got[0] and got[0] == got[1] == got[2] and all(c == '0' * 16 for c in cdv)
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> xlsb x3: BrtBeginSortCond condDataValue bytes %s' % ', '.join(cdv))
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
