#!/usr/bin/env python3
"""
RD-0112 (found while checking RD-0107; no upstream issue): CRASH - x2t died with SIGSEGV converting
to .xlsb a sheet whose sort condition sorts by cell or font colour without a dxfId
(<sortCondition sortBy="cellColor" ref="A2:A2"/>; dxfId is optional in the schema).

Cause: both CSortCondition::toBin variants (OOXML/XlsxFormat/Table/Autofilter.cpp: the record
object and the stream writer) read m_oDxfId->GetValue() for sortbyCellColor/sortbyFontColor
without checking m_oDxfId.IsInit() - a NULL dereference. CSortCondition::toXLS already checked.
Fix: the value is taken only when dxfId is present.

What runs: the REAL CSortCondition::toBin() and toBin(StreamCacheWriterPtr&), extracted by brace
matching, against stubs (nullable<> that dereferences its pointer like the real one; a record
stub that collects bytes), built with -fsanitize=address; each is run for sortBy = cellColor and
fontColor with no dxfId, and cellColor with dxfId=7. Checked: no crash, and dxfId 7 is written
when given.
Also, only if RD_X2T is set (RD_X2T_BASE with BASELINE=1): an xlsx with such a sort condition is
converted to xlsb; checked: x2t exits 0. RD_FONTS / RD_X2T_LIBS as in rd-0105.
NOT claimed: what Excel shows for such a sort (the xlsb holds dxf index 0 with RD-0107, as the
record has no "none" value).

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
BASE_REF = os.environ.get('BASE_REF', 'd179ace671^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/XlsxFormat/Table/Autofilter.cpp'


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


DRIVER = r"""
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <memory>
typedef unsigned short _UINT16; typedef unsigned int _UINT32;
#define SETBIT(x, n, v) { if (v) x |= (1 << n); }
#define SETBITS(x, f, t, v) { x |= ((v) << f); }
template<class T> struct nullable { T* p = nullptr; bool IsInit() const { return p != nullptr; }
  T* operator->() const { return p; }                 // as the real nullable: no check
  bool operator==(int v) const { return p->v == v; } };
namespace SimpleTypes { struct COnOff { bool v; bool GetValue() const { return v; } };
  struct CRelationshipId { std::wstring v; std::wstring GetValue() const { return v; } };
  struct CUnsignedDecimalNumber { unsigned v; unsigned GetValue() const { return v; } };
  namespace Spreadsheet { enum ESortBy { sortbyCellColor = 0, sortbyFontColor = 1, sortbyIcon = 2, sortbyValue = 3 };
    struct CSortBy { int v; }; } }
namespace XLS {
  struct CondDataValue { _UINT32 condDataValue = 0; _UINT32 reserved = 0; };
  struct BaseObject { virtual ~BaseObject() {} }; typedef std::shared_ptr<BaseObject> BaseObjectPtr;
  struct CFRecord { int type; std::vector<unsigned char> b;
    template<class T> CFRecord& operator<<(T& v) { const unsigned char* p = (const unsigned char*)&v; b.insert(b.end(), p, p + sizeof(T)); return *this; } };
  typedef std::shared_ptr<CFRecord> CFRecordPtr;
  struct StreamCacheWriter { std::vector<CFRecordPtr> out; CFRecordPtr getNextRecord(int t) { auto r = std::make_shared<CFRecord>(); r->type = t; return r; }
    void storeNextRecord(CFRecordPtr r) { out.push_back(r); } };
  typedef std::shared_ptr<StreamCacheWriter> StreamCacheWriterPtr;
}
namespace XLSB {
  enum { rt_BeginSortCond = 532, rt_EndSortCond = 533 };
  struct UncheckedRfX { _UINT32 a[4] = {0,0,0,0}; UncheckedRfX& operator=(const std::wstring&) { return *this; } };
  struct XLNullableWideString { _UINT32 cch = 0; void setSize(_UINT32 n) { cch = n; } XLNullableWideString& operator=(const wchar_t*) { return *this; } };
  struct BeginSortCond : XLS::BaseObject { bool fSortDes; _UINT16 sortOn; UncheckedRfX rfx; XLS::CondDataValue condDataValue; XLNullableWideString stSslist; };
  struct SORTCOND : XLS::BaseObject { XLS::BaseObjectPtr m_BrtBeginSortCond; };
}
namespace OOX { namespace Spreadsheet {
  struct CSortCondition {
    nullable<SimpleTypes::COnOff> m_oDescending; nullable<SimpleTypes::CRelationshipId> m_oRef;
    nullable<SimpleTypes::Spreadsheet::CSortBy> m_oSortBy; nullable<SimpleTypes::CUnsignedDecimalNumber> m_oDxfId;
    XLS::BaseObjectPtr toBin(); void toBin(XLS::StreamCacheWriterPtr& writer);
  };
@@FNS@@
} }
int main(int argc, char** argv) {
  // argv: tree|stream  sortBy(0 cell/1 font)  dxfId(-1 none)
  OOX::Spreadsheet::CSortCondition c;
  SimpleTypes::Spreadsheet::CSortBy by{atoi(argv[2])}; c.m_oSortBy.p = &by;
  SimpleTypes::CUnsignedDecimalNumber dx{(unsigned)atoi(argv[3])}; if (atoi(argv[3]) >= 0) c.m_oDxfId.p = &dx;
  unsigned v;
  if (argv[1][0] == 't') { auto o = c.toBin(); auto s = std::static_pointer_cast<XLSB::SORTCOND>(o);
    v = std::static_pointer_cast<XLSB::BeginSortCond>(s->m_BrtBeginSortCond)->condDataValue.condDataValue; }
  else { auto w = std::make_shared<XLS::StreamCacheWriter>(); c.toBin(w); memcpy(&v, w->out[0]->b.data() + 2 + 16, 4); }
  printf("ok %u\n", v);
  return 0;
}
"""


def run_extracted():
    src = read(REL)
    f1 = block(src, 'XLS::BaseObjectPtr CSortCondition::toBin()')
    f2 = block(src, 'void CSortCondition::toBin(XLS::StreamCacheWriterPtr& writer)')
    fns = f1 + '\n' + f2
    work = tempfile.mkdtemp(prefix='rd0112-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FNS@@', fns))
    r = subprocess.run(['c++', '-std=gnu++14', '-w', '-g', '-fsanitize=address', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for kind in ('tree', 'stream'):
        for by, dx, want, label in (('0', '-1', None, 'cellColor, no dxfId'), ('1', '-1', None, 'fontColor, no dxfId'), ('0', '7', '7', 'cellColor, dxfId=7')):
            r = subprocess.run([p[:-4], kind, by, dx], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
            got = r.stdout.strip()
            ok = r.returncode == 0 and got.startswith('ok') and (want is None or got == 'ok ' + want)
            if r.returncode:
                lines = [l for l in r.stderr.splitlines() if 'ERROR: AddressSanitizer' in l]
                got = 'CRASH ' + (lines[0].strip()[:110] if lines else 'rc=%d' % r.returncode)
            fails += not ok
            print(('ok   ' if ok else 'FAIL ') + 'CSortCondition::toBin (%s) %s: %s' % ('record object' if kind == 'tree' else 'stream writer', label, got))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'


def make_xlsx(path):
    sheet = ('<sheetData><row r="1"><c r="A1"><v>3</v></c></row><row r="2"><c r="A2"><v>1</v></c></row></sheetData>'
             '<autoFilter ref="A1:A2"><sortState ref="A2:A2"><sortCondition sortBy="cellColor" ref="A2:A2"/></sortState></autoFilter>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main">%s</worksheet>' % (NS, sheet))


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0112-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    td = tempfile.mkdtemp(dir=work)
    fonts = ''
    if os.environ.get('RD_FONTS'):
        fd = os.path.join(work, 'fonts'); shutil.copytree(os.environ['RD_FONTS'], fd)
        fonts = '<m_sFontDir>%s</m_sFontDir><m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath>' % (fd, fd)
    p = os.path.join(td, 'params.xml')
    open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s/out.xlsb</m_sFileTo>'
                       '<m_nFormatTo>264</m_nFormatTo>%s<m_sTempDir>%s</m_sTempDir></TaskQueueDataConvert>' % (src, work, fonts, td))
    env = dict(os.environ)
    if os.environ.get('RD_X2T_LIBS'):
        env['DYLD_FRAMEWORK_PATH'] = env['LD_LIBRARY_PATH'] = os.environ['RD_X2T_LIBS']
    rc = subprocess.run([exe, p], capture_output=True, env=env, timeout=120).returncode
    ok = rc == 0 and os.path.exists(os.path.join(work, 'out.xlsb'))
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx (cellColor sort, no dxfId) -> xlsb: rc=%d' % rc)
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
