#!/usr/bin/env python3
"""
RD-0016 (our corpus run, no upstream issue): saving a spreadsheet with a 3-D
surface chart that has no c:bandFmts (e.g. one that came from an .xls) crashed
x2t (SIGSEGV), so the save failed.

Found on POI's spreadsheet/49581.xls: open works, the save (Editor.bin -> XLSX)
dies with SIGSEGV in the release x2t; the AddressSanitizer x2t shows SEGV on
address 0 in CT_bandFmts::toXML called from CT_Surface3DChart::toXML
(OOXML/XlsxFormat/Chart/ChartSerialize.cpp).

Cause: c:bandFmts is optional (CT_Surface3DChart::m_bandFmts stays NULL when
the binary has none - BinaryChartReader only sets it when the record is
there), and CT_SurfaceChart::toXML checks it, but CT_Surface3DChart::toXML
called m_bandFmts->toXML unconditionally. Fix: the same NULL check.

What runs: the REAL CT_Surface3DChart::toXML is lifted out of
ChartSerialize.cpp by brace matching (git show BASE_REF:... with BASELINE=1)
and compiled with -fsanitize=address against stand-ins for the string
builder and the member types (wireframe, series, band formats, extLst) that
record what is written. A surface 3-D chart with one series and no band formats
is serialised. Passes when ASan reports nothing and the XML has the series and
no c:bandFmts.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ChartSerialize.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0016 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'ce4bbdb6aa^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
    sys.exit('unbalanced braces after %r' % start)


DRIVER = r'''
#include <cstdio>
#include <string>
#include <vector>
namespace NSStringUtils { struct CStringBuilder { std::wstring s; void WriteString(const std::wstring& w) { s += w; } }; }
namespace OOX { namespace Spreadsheet {
    struct Tag { void toXML(const std::wstring& n, NSStringUtils::CStringBuilder& w) const { w.WriteString(L"<" + n + L"/>"); } };
    struct CT_SurfaceSer : Tag {};
    /* like the real one: writes its m_bandFmt items */
    struct CT_bandFmts { std::vector<int> m_bandFmt; void toXML(const std::wstring& n, NSStringUtils::CStringBuilder& w) const {
        w.WriteString(L"<" + n + L">"); for (size_t i = 0; i < m_bandFmt.size(); ++i) w.WriteString(L"<c:bandFmt/>"); w.WriteString(L"</" + n + L">"); } };
    struct ExtLst { std::wstring toXMLWithNS(const std::wstring&) const { return L""; } };
    struct NullableExt { ExtLst* p = nullptr; bool IsInit() const { return p != nullptr; } ExtLst* operator->() const { return p; } };
    struct CT_Surface3DChart {
        Tag m_wireframe; std::vector<CT_SurfaceSer*> m_ser; CT_bandFmts* m_bandFmts = NULL;
        std::vector<unsigned int> m_axId; NullableExt m_extLst;
        void toXML(const std::wstring& sNodeName, NSStringUtils::CStringBuilder& writer) const;
    };
@@TOXML@@
}}
int main() {
    OOX::Spreadsheet::CT_Surface3DChart c;
    c.m_ser.push_back(new OOX::Spreadsheet::CT_SurfaceSer());
    c.m_axId.push_back(1);
    NSStringUtils::CStringBuilder w;
    c.toXML(L"c:surface3DChart", w);
    printf("XML=%ls\n", w.s.c_str());
    return 0;
}
'''


def main():
    src = read('OOXML/XlsxFormat/Chart/ChartSerialize.cpp')
    fn = block(src, 'void CT_Surface3DChart::toXML(const std::wstring& sNodeName, NSStringUtils::CStringBuilder& writer) const')
    work = tempfile.mkdtemp(prefix='rd0016-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@TOXML@@', fn))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not a and '<c:ser/>' in out and 'bandFmts' not in out
    print(('ok   ' if ok else 'FAIL ') + 'surface 3-D chart without band formats (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else ('serialised' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
