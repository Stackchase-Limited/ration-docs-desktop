#!/usr/bin/env python3
"""
RD-0104 (found by corpus testing of Editor.bin round trips; no upstream issue):
x2t crashed (SIGSEGV) converting ANY .xlsb to
  - a base64 Editor.bin (m_bIsNoBase64=false), or
  - mail-merge JSON (0x0808).
Desktop paths that do this: AscDesktopEditor.convertFile (CConvertFileInEditor,
which always passes m_bIsNoBase64=false) - External Links "update values" from a
linked .xlsb (sdkjs/common/ExternalDataLoader.js) and a Word mail merge whose
recipient list is an .xlsb (sdkjs/word/api.js, JSON). Opening an .xlsb normally
(no-base64 Editor.bin) was not affected.

Cause (OOXML/Binary/Sheets/Reader/BinaryWriterS.cpp, BinaryFileWriter::Open):
only the no-base64 branch of the file-type switch reads the unpacked input into
a CXlsb. The other branch (base64, and any JSON target) built a plain CXlsx, and
the XLSB block after the switch called dynamic_cast<CXlsb*>(pXlsx)->PrepareSi()
on the NULL that cast gives.
Fix: an XLSB input on that branch is read into a CXlsb (default-constructed,
then Read(), as the no-base64 branch does).

What runs:
  1. the REAL file-type switch and the XLSB block of BinaryFileWriter::Open,
     extracted by brace matching, against stub CXlsx/CXlsb (Read records which
     class read the input; PrepareSi touches a member, so a NULL `this` is an
     ASan SEGV), CSVReader, CXlsbBinaryWriter, COfficeFileFormatChecker. Each
     case is (input type, base64?, JSON target?) -> which class read the input
     and whether the XLSB preparation ran on it.
  2. only if RD_X2T=<x2t binary> is set (NOT built by this test): an xlsb made by
     that x2t from a generated xlsx is converted to a base64 Editor.bin and back
     to csv, and to mail-merge JSON (RD_FONTS: a font cache dir, copied first
     since x2t may rewrite AllFonts.js; DYLD/LD path from RD_X2T_LIBS). Not
     claimed without it.
NOT claimed: the desktop GUI (external links / mail merge dialogs) was not driven.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0104 commit
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '87d8fd27d1^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/Binary/Sheets/Reader/BinaryWriterS.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start, frm=0):
    """the statement beginning at `start`, through its brace-matched body (the REAL code)."""
    a = src.find(start, frm)
    if a < 0:
        sys.exit(repr(start) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1], i + 1
        i += 1


HEAD = r"""
#include <cstdio>
#include <cstdlib>
#include <string>
typedef unsigned int UINT; typedef unsigned char BYTE; typedef unsigned int _UINT32; typedef int _INT32;
namespace BinXlsxRW { namespace c_oFileTypes { enum c_oFileTypes { XLSX = 1, CSV = 2, JSON = 3, XLSB = 4 }; } }
#define AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSB 0x0108
static const int g_nFormatVersionNoBase64 = 10;
namespace OOX { struct CPath { std::wstring p; CPath(const std::wstring& s) : p(s) {} };
namespace Spreadsheet {
  struct CXlsx {
    bool m_bNeedCalcChain = true; void* m_pXlsbWriter = NULL; const char* readAs = "none";
    CXlsx() {}
    CXlsx(const CPath& p) { Read(p); }      // as core: the constructor reads
    virtual ~CXlsx() {}
    virtual void Read(const CPath&) { readAs = kind(); }
    virtual const char* kind() { return "CXlsx"; }
  };
  struct CXlsb : CXlsx {
    bool prepared = false;
    const char* kind() override { return "CXlsb"; }
    void PrepareSi() { prepared = true; }   // a member write: NULL this is a SEGV
    void PrepareTableFormula() { prepared = prepared && true; }
    void ReadSheetData() { prepared = prepared && true; }
  };
} }
struct CSVReader { int Read(const std::wstring&, OOX::Spreadsheet::CXlsx&, UINT, const std::wstring&, _INT32) { return 0; } };
namespace NSBinPptxRW { struct CXlsbBinaryWriter { void CreateFileW(const std::wstring&) {} void WriteStringUtf8(const std::wstring&) {}
  void WriteReserved(int) {} int GetPositionAbsolute() { return 0; } void CloseFile() {} }; }
static bool g_bInputIsXlsb = false;   // what the real checker finds in the unpacked input
struct COfficeFileFormatChecker { int nFileType = 0; bool isOOXFormatFile(const std::wstring&, bool) { nFileType = g_bInputIsXlsb ? AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSB : 0x0101; return true; } };
static std::wstring WriteFileHeader(int, int) { return L""; }
static int GetMainTableSize() { return 0; }

static OOX::Spreadsheet::CXlsx* run(BYTE fileType, BYTE saveFileType, bool bIsNoBase64) {
  std::wstring sInputDir = L"in", sFileDst = L"out", sDelimiter = L",";
  UINT nCodePage = 46; _INT32 Lcid = 0; _UINT32 result = 0; int m_nLastFilePosOffset = 0;
  OOX::Spreadsheet::CXlsx *pXlsx = NULL;
  @@SWITCH@@
  if (pXlsx)
  {
    @@XLSB@@
  }
  (void)result; (void)m_nLastFilePosOffset;
  return pXlsx;
}
int main(int argc, char** argv) {
  // argv: <input xlsx|xlsb> <base64 0|1> <json 0|1>
  BYTE ft = argv[1][3] == 'b' ? BinXlsxRW::c_oFileTypes::XLSB : BinXlsxRW::c_oFileTypes::XLSX;
  g_bInputIsXlsb = ft == BinXlsxRW::c_oFileTypes::XLSB;
  BYTE sft = argv[3][0] == '1' ? BinXlsxRW::c_oFileTypes::JSON : ft;
  OOX::Spreadsheet::CXlsx* x = run(ft, sft, argv[2][0] != '1');
  OOX::Spreadsheet::CXlsb* b = dynamic_cast<OOX::Spreadsheet::CXlsb*>(x);
  printf("read as %s%s\n", x ? x->readAs : "-", b ? (b->prepared ? ", xlsb prepared" : ", NOT prepared") : "");
  return 0;
}
"""

CASES = [
    # input, base64, json, want, label
    ('xlsx', '0', '0', 'read as CXlsx', 'xlsx -> no-base64 Editor.bin (unchanged)'),
    ('xlsx', '1', '0', 'read as CXlsx', 'xlsx -> base64 Editor.bin (unchanged)'),
    ('xlsb', '0', '0', 'read as CXlsb, xlsb prepared', 'xlsb -> no-base64 Editor.bin, the desktop open (unchanged)'),
    ('xlsb', '1', '0', 'read as CXlsb, xlsb prepared', 'xlsb -> base64 Editor.bin (convertFile)'),
    ('xlsb', '0', '1', 'read as CXlsb, xlsb prepared', 'xlsb -> mail-merge JSON'),
]


def run_extracted():
    src = read(REL)
    a = src.find('_UINT32 BinaryFileWriter::Open(')
    if a < 0:
        sys.exit('BinaryFileWriter::Open not found - the extractor needs updating')
    sw, end = block(src, 'switch(fileType)', a)
    xb, _ = block(src, 'if (fileType == BinXlsxRW::c_oFileTypes::XLSB)', end)
    code = HEAD.replace('@@SWITCH@@', sw).replace('@@XLSB@@', xb)
    work = tempfile.mkdtemp(prefix='rd0104-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for inp, b64, js, want, label in CASES:
        r = subprocess.run([exe, inp, b64, js], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        got = r.stdout.strip()
        ok = r.returncode == 0 and got == want
        fails += not ok
        if r.returncode:
            lines = [l for l in r.stderr.splitlines() if 'ERROR: AddressSanitizer' in l]
            got = 'CRASH ' + (lines[0].strip()[:140] if lines else 'rc=%d' % r.returncode)
        print(('ok   ' if ok else 'FAIL ') + '%s: %s%s' % (label, got, '' if ok else '  (want %r)' % want))
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


NS = 'http://schemas.openxmlformats.org/'
# shared strings, not inline ones: an xlsb with inline-string cells (BrtCellSt) loses their text on
# the way to ANY Editor.bin - a separate defect, not this one.
SHEET = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
         '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>10</v></c></row>')
SST = '<sst xmlns="%sspreadsheetml/2006/main" count="3" uniqueCount="3"><si><t>Name</t></si><si><t>Score</t></si><si><t>Ada</t></si></sst>' % NS


def make_xlsx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>' % NS)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS, NS))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (NS, NS))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="%sofficeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>' % (NS, NS, NS))
        z.writestr('xl/sharedStrings.xml', SST)
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


def text(path, rc):
    if rc or not os.path.exists(path):
        return 'rc=%d' % rc
    return open(path, encoding='utf-8-sig').read().strip().replace('\r', '').replace('\n', ' | ')


def run_x2t(exe):
    work = tempfile.mkdtemp(prefix='rd0104-x2t-')
    src = os.path.join(work, 'in.xlsx'); make_xlsx(src)
    xlsb = os.path.join(work, 'in.xlsb')
    fails = 0
    rc = x2t(exe, src, xlsb, 0x0108, work)
    if rc:
        print('FAIL x2t xlsx -> xlsb (setup): rc=%d' % rc)
        return 1
    eb = os.path.join(work, 'eb'); os.mkdir(eb)
    rc = x2t(exe, xlsb, os.path.join(eb, 'Editor.bin'), 0x2002, work, '<m_bIsNoBase64>false</m_bIsNoBase64>')
    csv = os.path.join(work, 'back.csv')
    rc = rc or x2t(exe, os.path.join(eb, 'Editor.bin'), csv, 0x0104, work)
    want = 'Name,Score | Ada,10'
    got = text(csv, rc); ok = got == want; fails += not ok
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsb -> base64 Editor.bin -> csv: %s%s' % (got, '' if ok else '  (want ' + want + ')'))
    js = os.path.join(work, 'out.json')
    rc = x2t(exe, xlsb, js, 0x0808, work)
    want = '[["Name","Score"],["Ada","10"]]'
    got = text(js, rc); ok = got == want; fails += not ok
    print(('ok   ' if ok else 'FAIL ') + 'x2t xlsb -> mail-merge json: %s%s' % (got, '' if ok else '  (want ' + want + ')'))
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
