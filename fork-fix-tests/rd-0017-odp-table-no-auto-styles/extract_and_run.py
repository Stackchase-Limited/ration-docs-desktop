#!/usr/bin/env python3
"""
RD-0017 (our corpus run, no upstream issue): opening an ODP/FODP whose table
cells need the default cell style, in a document that has no
office:automatic-styles element, crashed x2t (SIGSEGV).

Found on LibreOffice's sd/qa/unit/data/odp/tdf173489.fodp (a 1.6 KB flat ODP
with a table and no automatic styles): the release x2t dies with SIGSEGV on
open, the AddressSanitizer x2t with SEGV at address 0x10 in
table_table_cell::pptx_convert (OdfFile/Reader/Format/table_pptx.cpp).

Cause: when the document has no default table-cell style, pptx_convert creates
one and stores it in the document's office_automatic_styles container -
`dynamic_cast<office_automatic_styles*>(document->office_automatic_styles_.get())`
is NULL when the document has no such element, and `styles->styles_` was
dereferenced. Fix: the default style is only created when the container
exists; otherwise the cell goes on without it (the existing `if (style_inst)`
path).

What runs: the REAL fragment of table_table_cell::pptx_convert that looks up
or creates the default cell style (from "style_instance *style_inst =" up to the
following "if (style_inst)", git show BASE_REF:... with BASELINE=1) is compiled
with -fsanitize=address inside a stand-in context: style container, document
root with or without automatic styles, default_style/length/property
stand-ins. Two cases: a document without office:automatic-styles (must not
crash, no style created) and one with it (style created and registered, as
before). Passes when ASan reports nothing and both behave so.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read table_pptx.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0017 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '72e231853b^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
namespace odf_types { struct style_family { enum type { TableCell = 1 }; }; }
struct length { double v; enum unit { pt }; length(double x = 0, unit = pt) : v(x) {} };
struct style_table_cell_properties { struct { struct { bool has = false; length fo_padding_; } common_padding_attlist_; } attlist_; };
struct style_content { int style_family_ = 0; style_table_cell_properties props;
    style_table_cell_properties* get_style_table_cell_properties(bool) { return &props; } };
struct office_element { virtual ~office_element() {} };
typedef std::shared_ptr<office_element> office_element_ptr;
struct default_style : office_element { style_content content_; };
struct style_instance { style_content* c; style_content* content() const { return c; } };
struct office_automatic_styles : office_element { struct { std::vector<office_element_ptr> style_style_; } styles_; };
struct office_document_base : office_element { office_element_ptr office_automatic_styles_; };
struct StyleContainer { style_instance inst; bool has = false;
    style_instance* style_default_by_type(odf_types::style_family::type) { return has ? &inst : NULL; }
    void add_style(const wchar_t*, const wchar_t*, style_content* c, bool, bool, const wchar_t*, const wchar_t*,
                   const wchar_t*, const wchar_t*, const wchar_t*) { inst.c = c; has = true; } };
struct OdfContext { StyleContainer sc; StyleContainer& styleContainer() { return sc; } };
struct Impl { office_element* content; office_element* get_content() { return content; } };
struct Root { OdfContext oc; Impl impl; OdfContext& odf_context() { return oc; } Impl* get_impl() { return &impl; } };
struct Ctx { Root r; Root* root() { return &r; } };
static int run(Ctx& Context) {
@@FRAGMENT@@
    return style_inst ? 1 : 0;
}
int main() {
    { Ctx c; office_document_base doc; c.r.impl.content = &doc;            /* no office:automatic-styles */
      printf("NOAUTO=%d\n", run(c)); }
    { Ctx c; office_document_base doc; doc.office_automatic_styles_.reset(new office_automatic_styles());
      c.r.impl.content = &doc;
      int got = run(c);
      printf("AUTO=%d stored=%zu\n", got,
             static_cast<office_automatic_styles*>(doc.office_automatic_styles_.get())->styles_.style_style_.size()); }
    return 0;
}
'''


def main():
    src = read('OdfFile/Reader/Format/table_pptx.cpp')
    a = src.find('style_instance *style_inst = Context.root()->odf_context().styleContainer().style_default_by_type(odf_types::style_family::TableCell);')
    if a < 0:
        sys.exit('default cell style lookup not found - the extractor needs updating')
    b = src.find('if (style_inst)', a)
    frag = src[a:b]
    work = tempfile.mkdtemp(prefix='rd0017-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FRAGMENT@@', frag))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not m and 'NOAUTO=0' in out and 'AUTO=1 stored=1' in out
    print(('ok   ' if ok else 'FAIL ') + 'default table-cell style without office:automatic-styles (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + m.group(1)) if m else ('skipped there, created otherwise' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
