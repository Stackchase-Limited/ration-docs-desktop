#!/usr/bin/env python3
"""
RD-0056 (UPSTREAM_TRIAGE.md "Latent problems": "draw_frame::serialize writes
office:event-listeners before the frame content"): our ODF writer put
<office:event-listeners> first inside <draw:frame>, before the draw:image /
draw:object / draw:text-box it frames. The ODF 1.2 schema (OpenDocument-v1.2-
os-schema.rng, define "draw-frame") has the frame content first, then
office:event-listeners, glue points, image map, svg:title/desc, contour - so
every frame carrying a listener was invalid ODF. It is a live path: shape
hyperlinks/actions from pptx (start_action) and, since #2187 / RD-0055, macro
bindings on pictures and charts saved to ODS. LibreOffice reads either order;
a validating consumer does not. Fix: the listeners are written after the
content (core/OdfFile/Writer/Format/draw_frame.cpp, draw_frame::serialize).

What runs: the REAL draw_frame::serialize, extracted by brace matching (git
show BASE_REF:... with BASELINE=1), compiled against the real header-only xml
writer (OdfFile/Common/xml/simple_xml_writer.h) with stub draw_base content
(a draw:object) and a stub listener element. Passes when the output is
<draw:frame ...><draw:object/><office:event-listeners/></draw:frame>.

Checked once by hand with a converter built from this branch: the #2187
fixture's .ods now has <draw:frame><draw:text-box|draw:image/>
<office:event-listeners>...</draw:frame> for every bound shape, and
issue-2187-shape-macro/run.py (which reads the bindings back) still passes.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read draw_frame.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0056 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '63425b8f66^')
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


def main():
    fn = block(read('OdfFile/Writer/Format/draw_frame.cpp'), 'void draw_frame::serialize(std::wostream & _Wostream)')
    src = r'''
#include <xml/simple_xml_writer.h>
#include <memory>
#include <cstdio>
using namespace cpdoccore;
struct elm { std::wstring tag; void serialize(std::wostream & s) { CP_XML_WRITER(s) { CP_XML_NODE(tag) {} } } };
typedef std::shared_ptr<elm> office_element_ptr;
struct attlist { void serialize(CP_ATTR_NODE) { CP_XML_ATTR(L"draw:name", L"Chart 1"); } };
struct draw_base {
    office_element_ptr content;
    void serialize_attlist(CP_ATTR_NODE) {}
    void serialize(std::wostream & s) { content->serialize(s); }
};
struct draw_frame : draw_base {
    static const wchar_t * ns; static const wchar_t * name;
    attlist draw_frame_attlist_;
    office_element_ptr office_event_listeners_;
    void serialize(std::wostream & _Wostream);
};
const wchar_t * draw_frame::ns = L"draw";
const wchar_t * draw_frame::name = L"frame";
''' + fn + r'''
int main() {
    draw_frame f;
    f.content.reset(new elm); f.content->tag = L"draw:object";
    f.office_event_listeners_.reset(new elm); f.office_event_listeners_->tag = L"office:event-listeners";
    std::wstringstream s; f.serialize(s);
    std::wstring x = s.str(); printf("%s\n", std::string(x.begin(), x.end()).c_str());
    return 0;
}
'''
    work = tempfile.mkdtemp(prefix='rd0056-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(src)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-O0', '-I' + os.path.join(REPO, 'OdfFile', 'Common'), p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    out = subprocess.run([exe], capture_output=True, text=True).stdout.strip()
    ok = re.fullmatch(r'<draw:frame draw:name="Chart 1"><draw:object\s*/><office:event-listeners\s*/></draw:frame>', out) is not None
    print(('ok   ' if ok else 'FAIL ') + 'draw:frame child order (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree', out))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
