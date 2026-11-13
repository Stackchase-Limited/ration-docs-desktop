#!/usr/bin/env python3
"""
RD-0100 (found converting Apache POI's 52348.xlsx; no upstream issue): a number
format built on the General token was mangled by the CSV/JSON writer.
  - xlsx -> mail-merge JSON (0x0808): 52348.xlsx declares numFmtId 0 as
    formatCode="General", and its numbers came out as "1000eneral",
    "800eneral", "600eneral" (600.25 - the fraction lost too).
  - a custom format General" kg" gave "1000eneral kg" in JSON and plain "1000"
    (the " kg" dropped) in Save as CSV (xlsx/Editor.bin -> csv, binary path).

Cause (OOXML/Binary/Sheets/Writer/CSVWriter.cpp,
CSVWriter::Impl::ConvertValueCellToString): General has no 0/#/? placeholder,
so the number arm took position 0 as both the first and last digit, printed the
integer part, and pasted the code from position 1 ("eneral...") after it. A
cell without a type (binary path) went through detect_format, which also finds
no placeholder and calls the format text - the value was kept, the literal lost.
Fix: a General token in the section (outside quotes, escapes, [..]) means the
value as it stands, between the section's literal run-in and run-out; text,
error and boolean cells are left as they were.

What runs:
  1. the REAL ConvertValueCellToString, detect_format, numfmt_literal and
     (fixed tree) numfmt_find_general, extracted by brace matching from
     CSVWriter.cpp, compiled against a stub CSVWriter::Impl (real boost: regex,
     format, string algorithms). convert_date_time / fraction / scientific are
     stubs - no case here reaches them. Each case is (format code, cell type
     as the reader leaves it, stored value) -> written text.
  2. only if RD_X2T=<x2t binary> is set (NOT built by this test): a generated
     xlsx with General-based formats converted to json and to csv by that x2t
     (RD_FONTS: a font cache dir, copied first since x2t may rewrite AllFonts.js;
     DYLD/LD path from RD_X2T_LIBS). Not claimed without it.
NOT claimed: how a spreadsheet application would DISPLAY General (it trims
the stored value, e.g. 1000.0 -> 1000); the writer keeps the stored text, as it
already did for the built-in numFmtId 0.

  RD_REPO=<core checkout>   (default ../../core)
  RD_BOOST=<boost build dir with include/ and lib/>  (default: RD_REPO's, then ../../core's
                            Common/3dParty/boost/build/mac_arm64 or linux_64)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0100 commit
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REPO = os.environ.get('RD_REPO') or MAIN_CORE
BASE_REF = os.environ.get('BASE_REF', '3606acc7de^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/Binary/Sheets/Writer/CSVWriter.cpp'


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


def boost_dir():
    if os.environ.get('RD_BOOST'):
        return os.environ['RD_BOOST']
    plat = 'mac_arm64' if platform.system() == 'Darwin' else 'linux_64'
    for root in (REPO, MAIN_CORE):
        d = os.path.join(root, 'Common', '3dParty', 'boost', 'build', plat)
        if os.path.isdir(os.path.join(d, 'include')):
            return d
    sys.exit('boost build not found - set RD_BOOST')


HEAD = r"""
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <list>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include <locale>
#include <boost/optional.hpp>
#include <boost/regex.hpp>
#include <boost/format.hpp>
#include <boost/algorithm/string.hpp>
typedef long long _INT64;
namespace SimpleTypes { namespace Spreadsheet { enum ECellTypeType {
  celltypeBool = 0, celltypeDate = 1, celltypeError = 2, celltypeInlineStr = 3, celltypeNumber = 4,
  celltypeSharedString = 5, celltypeStr = 6, celltypePercentage = 7, celltypeScientific = 8,
  celltypeFraction = 9, celltypeTime = 10, celltypeCurrency = 11, celltypeDateTime = 12 }; } }
namespace XmlUtils {
  double GetDouble(const std::wstring& s) { return wcstod(s.c_str(), NULL); }
  void replace_all(std::wstring& s, const std::wstring& a, const std::wstring& b) { boost::algorithm::replace_all(s, a, b); }
}
std::wstring convert_fraction(const std::wstring& v) { return L"<fraction>"; }
std::wstring convert_scientific(const std::wstring& v) { return L"<scientific>"; }
struct CSVWriter { struct Impl {
  unsigned int language_code = 0;
  int m_nLcid = 0;
  std::wstring ConvertValueCellToString(const std::wstring &Value, boost::optional<int> format_type, std::wstring format_code);
  int detect_format(std::wstring & format_code);
  std::wstring convert_date_time(const std::wstring & sValue, std::wstring format_code, bool bDate = true, bool bTime = true) { return L"<date>"; }
  struct _numberFormat { bool bFloat = false; bool bThousands = false; bool bPercent = false;
    int count_int = 0; int count_float = 0; std::wstring format_string; };
  std::map<std::wstring, _numberFormat> mapNumberFormat;
}; };
@@FN@@
static std::string narrow(const std::wstring& w) { std::string r; for (wchar_t c : w) r += (c < 128 ? (char)c : '?'); return r; }
static std::wstring widen(const char* s) { std::wstring r; for (; *s; ++s) r += (wchar_t)*s; return r; }
int main(int argc, char** argv) {
  // argv: <format code> <type: -1 = none, else ECellTypeType> <value>
  CSVWriter::Impl w;
  boost::optional<int> t; int ti = atoi(argv[2]); if (ti >= 0) t = ti;
  printf("%s\n", narrow(w.ConvertValueCellToString(widen(argv[3]), t, widen(argv[1]))).c_str());
  return 0;
}
"""

N, NONE, STR, BOOL = '4', '-1', '6', '0'
CASES = [
    # code, type, value, want, label
    ('General', N, '1000.0', '1000.0', 'POI 52348: numFmtId 0 declared as "General", number cell (json path)'),
    ('General', N, '600.25', '600.25', 'the same, a fraction'),
    ('General" kg"', N, '1000', '1000 kg', 'General" kg", number cell (json path)'),
    ('General" kg"', NONE, '1000', '1000 kg', 'General" kg", untyped cell (Save as CSV binary path)'),
    ('"Total: "General', N, '600.25', 'Total: 600.25', 'literal before General'),
    ('[Red]general;[Blue]-General', N, '7', '7', 'any case, [..] directive dropped, first section'),
    ('General', STR, 'abc', 'abc', 'text cell under General (unchanged)'),
    ('General" kg"', BOOL, '1', '1', 'boolean cell under General" kg" (left as it was)'),
    ('"General"0', N, '5', 'General5', 'quoted "General" is a literal, 0 is the placeholder (unchanged)'),
    ('0.00" kg"', N, '3.14159', '3.14 kg', 'placeholder format with a literal (unchanged)'),
]


def run_extracted():
    src = read(REL)
    fns = [func(src, 'static std::wstring replace_unwanted('),
           func(src, 'int CSVWriter::Impl::detect_format('),
           func(src, 'static std::wstring numfmt_literal('),
           func(src, 'static size_t numfmt_find_general(', required=False),
           func(src, 'std::wstring CSVWriter::Impl::ConvertValueCellToString(')]
    code = HEAD.replace('@@FN@@', '\n'.join(fns))
    b = boost_dir()
    work = tempfile.mkdtemp(prefix='rd0100-')
    p = os.path.join(work, 'drv.cpp'); open(p, 'w').write(code); exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-g', '-w', '-I', os.path.join(b, 'include'), p,
                        os.path.join(b, 'lib', 'libboost_regex.a'), '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for fmt, typ, val, want, label in CASES:
        r = subprocess.run([exe, fmt, typ, val], capture_output=True, text=True)
        got = r.stdout.strip()
        ok = r.returncode == 0 and got == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s [%s] %s -> %r%s' % (label, fmt, val, got or r.stderr.strip()[-200:],
              '' if ok else '  (want %r)' % want))
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    shutil.rmtree(work, ignore_errors=True)
    return fails


def make_xlsx(path):
    ns = 'http://schemas.openxmlformats.org/'
    fmts = [(0, 'General'), (164, 'General" kg"'), (165, '"Total: "General')]
    nf = ''.join('<numFmt numFmtId="%d" formatCode="%s"/>' % (i, c.replace('"', '&quot;')) for i, c in fmts)
    xfs = ''.join('<xf numFmtId="%d" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>' % i for i, c in fmts)
    styles = ('<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="%sspreadsheetml/2006/main"><numFmts count="3">%s</numFmts>'
              '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3">%s</cellXfs></styleSheet>' % (ns, nf, xfs))
    sheet = '<row r="1"><c r="A1" s="0" t="n"><v>1000.5</v></c><c r="B1" s="1" t="n"><v>1000</v></c><c r="C1" s="2" t="n"><v>600.25</v></c></row>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%spackage/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>' % ns)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (ns, ns))
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (ns, ns))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" Type="%sofficeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="%sofficeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' % (ns, ns, ns))
        z.writestr('xl/styles.xml', styles)
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%sspreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % (ns, sheet))


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
    work = tempfile.mkdtemp(prefix='rd0100-x2t-')
    src = os.path.join(work, 'general.xlsx'); make_xlsx(src)
    fails = 0
    for fmt, ext, want in ((0x0808, 'json', '[["1000.5","1000 kg","Total: 600.25"]]'),
                           (0x0104, 'csv', '1000.5,1000 kg,Total: 600.25')):
        out = os.path.join(work, 'out.' + ext)
        rc = x2t(exe, src, out, fmt, work)
        got = open(out, encoding='utf-8-sig').read().strip() if rc == 0 and os.path.exists(out) else 'rc=%d' % rc
        ok = got == want; fails += not ok
        print(('ok   ' if ok else 'FAIL ') + 'x2t xlsx -> %s: %s%s' % (ext, got, '' if ok else '  (want ' + want + ')'))
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
