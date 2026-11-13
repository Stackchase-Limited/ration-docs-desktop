#!/usr/bin/env python3
"""
RD-0111 (found by corpus determinism checks; no upstream issue): an .xlsb written from a workbook
whose shared strings carry phonetic properties (<si>...<phoneticPr fontId=.../></si>, Japanese
files; POI's 47813.xlsx) got uninitialised bytes in each such BrtSSTItem's phonetic run - the
xlsb differed between runs ('aaaaaaaaaaaa' under -ftrivial-auto-var-init=pattern).

Cause: CSi::toBin (OOXML/XlsxFormat/SharedStrings/Si.cpp) declares a local XLSB::PhRun and fills
it only from the attributes present (CPhonetic::toBin: ifnt/alcH/phType if given; CRPh::toBin:
ichFirst/ichMom if an rPh follows; cchMom never), then PhRun::save writes all 12 bytes. PhRun
(OOXML/XlsbFormat/Biff12_structures/PhRun.h) has no constructor. Fix: its members default to 0.

What runs: the REAL PhRun class (header) and PhRun::save (PhRun.cpp), extracted by brace
matching, against a stub CFRecord that collects the bytes; a PhRun default-constructed on a
stack compiled with -ftrivial-auto-var-init=pattern and one placement-new'd into 0xAA memory
are saved. Checked: the 12 bytes are 0.
Also, only if RD_X2T is set (RD_X2T_BASE with BASELINE=1): an xlsx with a phoneticPr shared
string is converted to xlsb three times; checked: sharedStrings.bin identical and the run's
ichFirst/ichMom/cchMom are 0. RD_FONTS / RD_X2T_LIBS as in rd-0105.
NOT claimed: rPh elements before phoneticPr are still not written as runs (CSi::toBin only looks
after the phoneticPr) - unchanged.

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
BASE_REF = os.environ.get('BASE_REF', '24a9dbda62^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start, semi=False):
    a = src.find(start)
    if a < 0:
        sys.exit(repr(start) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1] + (';' if semi else '')
        i += 1


DRIVER = r"""
#include <cstdio>
#include <cstring>
#include <new>
#include <memory>
#include <vector>
typedef unsigned short _UINT16; typedef unsigned char BYTE;
#define BASE_STRUCTURE_DEFINE_CLASS_NAME(x)
#define SETBITS(to, from, num, val) to |= ((val) << (from));
namespace XLS {
  enum ElementType { typeBiffStructure };
  struct CFRecord { std::vector<unsigned char> b;
    template<class T> CFRecord& operator<<(T& v) { const unsigned char* p = (const unsigned char*)&v; b.insert(b.end(), p, p + sizeof(T)); return *this; } };
  struct BiffStructure { virtual ~BiffStructure() {} virtual void load(CFRecord&) {} virtual void save(CFRecord&) {} };
  typedef std::shared_ptr<BiffStructure> BiffStructurePtr;
}
namespace XLSB {
@@CLASS@@
XLS::BiffStructurePtr PhRun::clone() { return XLS::BiffStructurePtr(new PhRun(*this)); }
void PhRun::load(XLS::CFRecord&) {}
@@SAVE@@
}
static void dump(const char* what, XLSB::PhRun& r) { XLS::CFRecord rec; r.save(rec); printf("%s ", what);
  for (unsigned char c : rec.b) printf("%02x", c); printf("\n"); }
__attribute__((noinline)) static void onStack() { XLSB::PhRun r; dump("stack", r); }
int main() {
  onStack();
  alignas(XLSB::PhRun) unsigned char mem[sizeof(XLSB::PhRun)]; memset(mem, 0xAA, sizeof mem);
  XLSB::PhRun* h = new (mem) XLSB::PhRun; dump("heap", *h);
  return 0;
}
"""


def run_extracted():
    cls = block(read('OOXML/XlsbFormat/Biff12_structures/PhRun.h'), 'class PhRun', True)
    save = block(read('OOXML/XlsbFormat/Biff12_structures/PhRun.cpp'), 'void PhRun::save(XLS::CFRecord& record)')
    work = tempfile.mkdtemp(prefix='rd0111-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@CLASS@@', cls).replace('@@SAVE@@', save))
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-ftrivial-auto-var-init=pattern', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    out = dict(l.split(' ') for l in subprocess.run([p[:-4]], capture_output=True, text=True).stdout.split('\n') if l)
    fails = 0
    for k, label in (('stack', 'PhRun local (stack, pattern-filled) saved'), ('heap', 'PhRun in 0xAA memory saved')):
        ok = out.get(k) == '0' * 20
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s: %s' % (label, out.get(k)))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'


def make_xlsx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="%sofficeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>' % (NS, NS, NS))
        z.writestr('xl/sharedStrings.xml', '<sst xmlns="%sspreadsheetml/2006/main" count="1" uniqueCount="1"><si><t>Angle</t><phoneticPr fontId="1"/></si></sst>' % NS)
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>' % NS)


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
    work = tempfile.mkdtemp(prefix='rd0111-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    sst = []
    for k in range(3):
        o = os.path.join(work, '%d.xlsb' % k)
        rc = x2t(exe, src, o, 0x0108, work)
        if rc:
            print('FAIL x2t xlsx -> xlsb: rc=%d' % rc)
            return 1
        sst.append(zipfile.ZipFile(o).read('xl/sharedStrings.bin'))
    # BrtSSTItem: flags(1) cch(4) "Angle"(10) phoneticStr cch(4) dwPhoneticRun(4) PhRun(12)
    i = sst[0].find(b'A\x00n\x00g\x00l\x00e\x00')
    run = sst[0][i + 10 + 8:i + 10 + 8 + 6].hex() if i >= 0 else 'none'
    ok = sst[0] == sst[1] == sst[2] and run == '0' * 12
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> xlsb x3: sharedStrings.bin %s, phonetic run ichFirst/ichMom/cchMom %s'
          % ('identical' if sst[0] == sst[1] == sst[2] else 'DIFFER', run))
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
