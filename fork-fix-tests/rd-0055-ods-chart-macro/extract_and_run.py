#!/usr/bin/env python3
"""
RD-0055 (UPSTREAM_TRIAGE.md "Latent problems": "GraphicFrame (chart) @macro is
still dropped on ODS"): a macro assigned to a chart in a workbook was lost when
the workbook was saved as .ods - the chart came back inert, while the macro
body (jsaProject.bin) survived. Same defect as #2187, for the one drawing kind
that fix left out.

Cause, both halves of core/OdfFile:
  - writer, Writer/Converter/ConvertDrawing.cpp OoxConverter::convert(
    PPTX::Logic::GraphicFrame*): never passed graphicFrame/@macro to
    drawing_context()->set_macro (Shape/Pic/CxnSp do since #2187), so no
    office:event-listeners was written on the chart's draw:frame;
  - reader, Reader/Converter/xlsx_drawing.cpp xml_serialize_chart: never wrote
    @macro on xdr:graphicFrame, so a listener read back from ODS (the
    draw_frame xlsx_convert path from #2187 already reads it) was dropped.
Fix: the same one-line hook on both sides.

What runs (no converter needed):
  1. the REAL xml_serialize_chart, extracted by brace matching and compiled
     against the real header-only xml writer (OdfFile/Common/xml/
     simple_xml_writer.h), with a stub _xlsx_drawing carrying a macro;
     passes when xdr:graphicFrame has macro="..." (and none without one);
  2. the REAL OoxConverter::convert(PPTX::Logic::GraphicFrame*), extracted
     and compiled with stub GraphicFrame/drawing context; passes when the
     frame's macro reaches set_macro.
  BASELINE=1 reads both files at BASE_REF; both must fail there.

Optional end-to-end (RD_X2T=<converter built from the tree under test>):
chart_fixture.py builds the #2187 fixture plus a bar chart whose
graphicFrame carries the macro, runs xlsx -> ods -> xlsx and requires the
chart's @macro back. Seen once by hand: the fixed converter brings it back
and writes the listener on the chart's draw:frame; the pre-fix one returns
the chart without it.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0055 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '46e22fe61e^')
BASELINE = bool(os.environ.get('BASELINE'))
LABEL = 'baseline ' + BASE_REF if BASELINE else 'working tree'


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


def build_run(name, src, extra_inc=()):
    work = tempfile.mkdtemp(prefix='rd0055-')
    p = os.path.join(work, name + '.cpp')
    open(p, 'w').write(src)
    exe = os.path.join(work, name)
    cmd = ['c++', '-std=gnu++11', '-w', '-O0'] + ['-I' + i for i in extra_inc] + [p, '-o', exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    return subprocess.run([exe], capture_output=True, text=True).stdout


def reader_half():
    fn = block(read('OdfFile/Reader/Converter/xlsx_drawing.cpp'),
               'void xml_serialize_chart(std::wostream & strm, _xlsx_drawing & val)')
    src = r'''
#include <xml/simple_xml_writer.h>
#include <cstdio>
namespace cpdoccore { namespace oox {
struct _xlsx_drawing {
    std::wstring macro, name, objectId; int id = 2; bool hidden = false;
    void serialize_xfrm(std::wostream &, const std::wstring &) {}
};
''' + fn + r'''
}}
using namespace cpdoccore::oox;
int main() {
    for (int i = 0; i < 2; ++i) {
        _xlsx_drawing d; d.name = L"Chart 1"; d.objectId = L"rId1";
        if (i == 0) d.macro = L"jsaProject_{G}";
        std::wstringstream s; xml_serialize_chart(s, d);
        std::wstring x = s.str(); std::string a(x.begin(), x.end());
        printf("X%d %s\n", i, a.c_str());
    }
    return 0;
}
'''
    out = build_run('reader', src, [os.path.join(REPO, 'OdfFile', 'Common'), os.path.join(REPO, 'OdfFile', 'Common', 'xml', '..')])
    with_m = re.search(r'^X0 (.*)$', out, re.M)
    without = re.search(r'^X1 (.*)$', out, re.M)
    ok = bool(with_m and without) and re.search(r'<xdr:graphicFrame macro="jsaProject_\{G\}">', with_m.group(1)) \
        and 'macro=' not in without.group(1)
    print(('ok   ' if ok else 'FAIL ') + 'ODS reader writes chart @macro (%s): %s' % (
        LABEL, (with_m.group(1)[:80] + '...') if with_m else out))
    return ok


def writer_half():
    fn = block(read('OdfFile/Writer/Converter/ConvertDrawing.cpp'),
               'void OoxConverter::convert(PPTX::Logic::GraphicFrame *oox_graphic_frame)')
    src = r'''
#include <string>
#include <cstdio>
template <class T> struct nullable { T* p = 0; bool IsInit() const { return p != 0; } bool is_init() const { return p != 0; }
    T& operator*() { return *p; } T* operator->() { return p; } T* GetPointer() { return p; } };
struct Any {};
struct ElemHolder { Any* GetPointer() { return 0; } };
namespace PPTX { namespace Logic {
struct GraphicFrame {
    nullable<std::wstring> macro;
    nullable<Any> nvGraphicFramePr, xfrm, chartRec, smartArt, olePic, table;
    struct { bool is_init() { return false; } ElemHolder GetElem() { return ElemHolder(); } } element;
};
}}
struct DrawingContext { std::wstring macro; void set_macro(const std::wstring& m) { macro = m; } };
struct OdfContext { DrawingContext dc; DrawingContext* drawing_context() { return &dc; } };
struct OoxConverter {
    OdfContext ctx;
    virtual ~OoxConverter() {}
    OdfContext* odf_context() { return &ctx; }
    template <class T> void convert(T*) {}
    void convert(PPTX::Logic::GraphicFrame *oox_graphic_frame);
};
struct PptxConverter : OoxConverter { template <class T> void convert(T*) {} };
''' + fn + r'''
int main() {
    std::wstring m = L"jsaProject_{G}";
    PPTX::Logic::GraphicFrame f; f.macro.p = &m;
    OoxConverter c; c.convert(&f);
    PPTX::Logic::GraphicFrame g;
    OoxConverter c2; c2.convert(&g);
    std::string a(c.ctx.dc.macro.begin(), c.ctx.dc.macro.end());
    printf("SET=[%s] EMPTY=[%d]\n", a.c_str(), (int)c2.ctx.dc.macro.empty());
    return 0;
}
'''
    out = build_run('writer', src).strip()
    ok = out == 'SET=[jsaProject_{G}] EMPTY=[1]'
    print(('ok   ' if ok else 'FAIL ') + 'ODS writer passes chart @macro to the drawing (%s): %s' % (LABEL, out))
    return ok


def e2e():
    x2t = os.environ.get('RD_X2T')
    if not x2t:
        print('skip end-to-end chart round trip (set RD_X2T)')
        return True
    sys.path.insert(0, HERE)
    import chart_fixture as C
    R = C.R
    R.X2T = x2t
    if os.environ.get('X2T_FRAMEWORKS'):
        R.FRAMEWORKS = os.environ['X2T_FRAMEWORKS']
    d = tempfile.mkdtemp(prefix='rd0055-e2e-')
    C.build(os.path.join(d, 'in.xlsx'), R.MACRO)
    rc1 = R.convert(os.path.join(d, 'in.xlsx'), os.path.join(d, 'mid.ods'), R.FORMAT_ODS, d)
    rc2 = R.convert(os.path.join(d, 'mid.ods'), os.path.join(d, 'out.xlsx'), R.FORMAT_XLSX, d)
    frames, charts = C.frames(os.path.join(d, 'out.xlsx')) if rc1 == 0 and rc2 == 0 else ([], [])
    ok = frames == [R.MACRO] and len(charts) == 1
    print(('ok   ' if ok else 'FAIL ') + 'xlsx -> ods -> xlsx chart @macro (%s): %s' % (x2t, frames or 'rc=%d/%d' % (rc1, rc2)))
    return ok


if __name__ == '__main__':
    results = [reader_half(), writer_half(), e2e()]
    sys.exit(0 if all(results) else 1)
