#!/usr/bin/env python3
"""
#2566 "Lots of layout issues of an .odp document" - three ODP import defects in
core's ODF -> PPTX text conversion (OdfFile/Reader/Converter/pptx_text_context.cpp),
found with the reporter's ODF15_AfCEPq0.odp and x2t:

 1. LINEBREAK  text before a <text:line-break/> was dropped. Slide 1's title
    "The Road to ODF 1.5<br/><br/>Olivier Hallot" came out as one <a:br/> and
    "Olivier Hallot"; slide 8 lost three lines. Since upstream 9c8b739d0e
    line_break::pptx_convert set is_line_break and appended "\\n" to the pending
    run text, and the next dump_run() wrote only <a:br/> for all of it.
    Fixed by pptx_text_context::add_line_break(): the pending text is dumped as
    its own run first, then each break is its own <a:br/>.
 2. NESTED     each nested <text:list> added an empty paragraph at the new level
    (start_list() dumps the parent paragraph, the next start_paragraph()
    dumped it again as an empty styled one). Fixed by dump_paragraph() writing
    an empty styled paragraph only once (paragraph_pending_).
 3. OUTLINE    list levels 2..9 of an outline placeholder got the outline1 text
    properties (28 pt for all levels; master has 22/20/18 pt). Fixed by
    OutlineLevelStyle(): level N adds "<master>-outline<N+1>" after the base
    style in ApplyTextProperties()/ApplyParagraphProperties().

What runs: the REAL Impl methods (add_text, start/end_paragraph, start/end_span,
start/end_hyperlink, dump_run, dump_paragraph, start/end_list,
start/end_list_item, set_line_break, set_style_name, ApplyTextProperties,
ApplyParagraphProperties, and add_line_break / OutlineLevelStyle where they
exist) plus the REAL body of line_break::pptx_convert from
Format/paragraph_elements.cpp are extracted by brace matching and compiled into
a stand-in Impl with stub styles, XML-writer macros and property types. The
driver replays the call sequence the ODF tree walk makes for the reporter's
slide 1 title, a nested list, and an outline placeholder paragraph at level 3.

NOT claimed: the stub XML writer is not the real one (output is only checked
for runs, breaks and paragraph counts); rendering, list indents (positive
text-indent from min-label-width, a separate defect) and the rest of the
converter are not exercised here - the full x2t run on the reporter's file is
described in the commit messages.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the first #2566 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '1ee6da4394^')
BASELINE = bool(os.environ.get('BASELINE'))

CTX = 'OdfFile/Reader/Converter/pptx_text_context.cpp'
PARA = 'OdfFile/Reader/Format/paragraph_elements.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def extract(src, head):
    """Return the definition starting at `head` up to its matching closing brace, or None."""
    a = src.find(head)
    if a < 0:
        return None
    b = src.find('{', a)
    depth = 0
    for i in range(b, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[a:i + 1]
    sys.exit('unbalanced braces after ' + head)


PRELUDE = r'''
#include <cstdio>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#define _CP_OPT(T) std::optional<T>
namespace boost { static const std::nullopt_t none = std::nullopt;
    template <class K, class V> using unordered_map = std::unordered_map<K, V>; }
namespace XmlUtils { static std::wstring EncodeXmlString(const std::wstring& s) { return s; } }
namespace odf_types {
struct style_family { enum type { None, Paragraph, Text, Presentation, Graphic }; };
struct length { enum unit { pt, cm }; double v = 0; unit u = pt;
    length(double x = 0, unit uu = pt) : v(x), u(uu) {}
    double get_value() const { return v; } unit get_unit() const { return u; }
    double get_value_unit(unit) const { return v; } };
struct font_size { enum type { Length, Percent }; type t = Length; length l;
    type get_type() const { return t; } length get_length() const { return l; } };
struct length_or_percent { length l; length get_length() const { return l; } };
}
// recorded style cascades: one entry per Apply*Properties call, the names in order
static std::vector<std::vector<std::wstring>> g_cascades;
namespace odf_reader {
struct style_instance { std::wstring name_; style_instance* parent_ = nullptr;
    const std::wstring& name() const { return name_; } style_instance* parent() const { return parent_; } };
struct styles_container {
    std::map<std::wstring, style_instance*> by_name;
    style_instance* style_by_name(const std::wstring& n, odf_types::style_family::type, bool) const {
        auto it = by_name.find(n); return it == by_name.end() ? nullptr : it->second; }
    style_instance* style_default_by_type(odf_types::style_family::type) const { return nullptr; } };
struct text_format_properties { std::optional<odf_types::font_size> fo_font_size_;
    void apply_from(const text_format_properties&) {} void pptx_convert(...) {} };
typedef std::shared_ptr<text_format_properties> text_format_properties_ptr;
struct paragraph_format_properties { std::optional<odf_types::length_or_percent> fo_margin_top_, fo_margin_left_, fo_text_indent_;
    void apply_from(const paragraph_format_properties&) {} void pptx_convert(...) {} };
static void record(const std::vector<const style_instance*>& v) {
    std::vector<std::wstring> n; for (auto* s : v) n.push_back(s->name_); g_cascades.push_back(n); }
static text_format_properties_ptr calc_text_properties_content(const std::vector<const style_instance*>& v) {
    record(v); return std::make_shared<text_format_properties>(); }
static paragraph_format_properties calc_paragraph_properties_content(const std::vector<const style_instance*>& v) {
    record(v); return paragraph_format_properties(); }
struct text_list_style {};
struct list_style_container { text_list_style* list_style_by_name(const std::wstring&) { return nullptr; }
    void add_list_style(text_list_style*, const std::wstring&) {} };
struct odf_read_context { styles_container sc; list_style_container lc;
    styles_container& styleContainer() { return sc; } list_style_container& listStyleContainer() { return lc; } };
}
struct styles_context { std::wstringstream ts; std::wstring hl;
    void start() {} void start_process_style(odf_reader::style_instance*) {}
    std::wstring& hlinkClick() { return hl; } std::wstringstream& text_style() { return ts; } };
// minimal stand-in for core's simple_xml_writer macros
struct XW { std::wostream& s; bool once = true; XW(std::wostream& o) : s(o) {} };
struct XN { XW& w; std::wstring n; bool once = true;
    XN(XW& ww, const std::wstring& nn) : w(ww), n(nn) { w.s << L"<" << n << L">"; }
    ~XN() { w.s << L"</" << n << L">"; } };
#define CP_XML_WRITER(strm) for (XW _xw(strm); _xw.once; _xw.once = false)
#define CP_XML_NODE(name) for (XN _xn(_xw, name); _xn.once; _xn.once = false)
#define CP_XML_STREAM() (_xw.s)
#define CP_XML_ATTR(n, v) (_xw.s << L"@" << n << L"=" << v << L" ")
enum field_type { none, datetime };
struct hyperlink_data { std::wstring a, b; };
struct Impl {
    odf_reader::odf_read_context odf_context_;
    styles_context styles_context_;
    styles_context& get_styles_context() { return styles_context_; }
    std::wstring hyperlink_hId; hyperlink_data hyperlink_;
    bool in_span = false, in_paragraph = false, in_comment = false, is_predump = false, is_lasttext = false,
         is_line_break = false, in_hyperlink = false, paragraph_pending_ = false, has_style_name = false,
         header = false, first_element_list_item_ = false, in_list_ = false, process_layouts_ = false;
    odf_reader::styles_container* local_styles_ptr_ = nullptr;
    std::wstringstream text_, run_, paragraph_, field_value_;
    size_t paragraphs_cout_ = 0;
    std::wstring paragraph_style_name_, last_paragraph_style_name_, span_style_name_, base_style_name_;
    odf_types::style_family::type base_style_family_ = odf_types::style_family::None;
    std::vector<std::wstring> list_style_stack_;
    _CP_OPT(odf_types::length) last_run_font_size_;
    int new_list_style_number_ = 0;
    boost::unordered_map<std::wstring, std::wstring> list_style_renames_;
    field_type field_type_ = none;
    void dump_field() {}
    void write_rPr(std::wostream& s) { s << L"<rPr/>"; }
    void write_pPr(std::wostream& s) { s << L"<pPr lvl=" << (int)list_style_stack_.size() - 1 << L"/>"; }
    std::wstring find_list_rename(const std::wstring& n) { return n; }
    std::wstring current_list_style() { return list_style_stack_.empty() ? L"" : list_style_stack_.back(); }
@@DECLS@@
};
@@DEFS@@
struct TextCtxFacade { Impl& i;
    void set_line_break(bool& b) { i.set_line_break(b); }
    void add_text(const std::wstring& t) { i.add_text(t); }
@@FACADE@@
};
struct Ctx { Impl& i; TextCtxFacade f{i}; TextCtxFacade& get_text_context() { return f; } };
namespace oox { typedef Ctx pptx_conversion_context; }
@@LINEBREAK@@
static std::string narrow(const std::wstring& w) { return std::string(w.begin(), w.end()); }
static int count(const std::wstring& s, const std::wstring& n) {
    int c = 0; for (size_t p = s.find(n); p != std::wstring::npos; p = s.find(n, p + 1)) ++c; return c; }
int main() {
    { // 1. slide 1 title: <text:p>The Road to ODF 1.5<br/><br/><text:span T1>Olivier Hallot</text:span></text:p>
        Impl i; Ctx c{i};
        i.start_paragraph(L"P1"); i.add_text(L"The Road to ODF 1.5");
        line_break_pptx_convert(c); line_break_pptx_convert(c);
        i.start_span(L"T1"); i.add_text(L"Olivier Hallot"); i.end_span(); i.end_paragraph();
        i.dump_paragraph();
        std::wstring out = i.paragraph_.str();
        printf("LINEBREAK title=%d name=%d br=%d :: %s\n", count(out, L"<a:t>The Road to ODF 1.5</a:t>"),
               count(out, L"<a:t>Olivier Hallot</a:t>"), count(out, L"<a:br>"), narrow(out).c_str());
    }
    { // 2. <list L2><item><p>A</p><list><item><p>B</p></item></list></item></list>, then <p P1/><p P1>X</p>
        Impl i;
        i.start_list(L"L2", false); i.start_list_item(false);
        i.start_paragraph(L"P1"); i.add_text(L"A"); i.end_paragraph();
        i.start_list(L"", false); i.start_list_item(false);
        i.start_paragraph(L"P1"); i.add_text(L"B"); i.end_paragraph();
        i.end_list_item(); i.end_list(); i.end_list_item(); i.end_list();
        i.dump_paragraph();
        std::wstring out = i.paragraph_.str();
        Impl j;
        j.start_paragraph(L"P1"); j.end_paragraph(); j.start_paragraph(L"P1"); j.add_text(L"X"); j.end_paragraph();
        j.dump_paragraph();
        printf("NESTED paras=%d emptyStyled=%d :: %s\n", count(out, L"<a:p>"), count(j.paragraph_.str(), L"<a:p>"),
               narrow(out).c_str());
    }
    { // 3. outline placeholder (presentation style pr9 -> Testo-outline1), paragraph at list level 2
        Impl i;
        odf_reader::style_instance o1{L"Testo-outline1"}, o2{L"Testo-outline2", &o1}, o3{L"Testo-outline3", &o2},
                                   pr9{L"pr9", &o1};
        for (auto* s : {&o1, &o2, &o3, &pr9}) i.odf_context_.sc.by_name[s->name_] = s;
        i.base_style_name_ = L"pr9"; i.base_style_family_ = odf_types::style_family::Presentation;
        i.list_style_stack_ = {L"L2", L"L2", L"L2"};
        odf_reader::text_format_properties tp; odf_reader::paragraph_format_properties pp;
        g_cascades.clear();
        i.ApplyTextProperties(L"", L"P1", tp, false);
        i.ApplyParagraphProperties(L"P1", pp, false);
        i.list_style_stack_ = {L"L2"};
        i.ApplyTextProperties(L"", L"P1", tp, false);
        auto has = [](const std::vector<std::wstring>& v, const wchar_t* n) {
            for (auto& x : v) if (x == n) return 1; return 0; };
        printf("OUTLINE text=%d para=%d level1=%d\n", has(g_cascades[0], L"Testo-outline3"),
               has(g_cascades[1], L"Testo-outline3"),
               has(g_cascades[2], L"Testo-outline2") + has(g_cascades[2], L"Testo-outline3"));
    }
    return 0;
}
'''

METHODS = ['add_text', 'start_paragraph', 'end_paragraph', 'start_span', 'end_span', 'start_hyperlink',
           'end_hyperlink', 'dump_run', 'dump_paragraph', 'start_list', 'end_list', 'start_list_item',
           'end_list_item', 'set_line_break', 'set_style_name', 'ApplyTextProperties',
           'ApplyParagraphProperties']
OPTIONAL = ['add_line_break', 'OutlineLevelStyle']


def main():
    src = read(CTX)
    decls, defs, have = [], [], set()
    cls = extract(src, 'class pptx_text_context::Impl')
    for name in METHODS + OPTIONAL:
        body = extract(src, 'pptx_text_context::Impl::%s(' % name)
        if body is None:
            if name in OPTIONAL:
                continue
            sys.exit('Impl::%s not found - the extractor needs updating' % name)
        have.add(name)
        # declaration (with its default arguments) from the class body
        m = re.search(r'^[ \t]*([^\n;/]*\b%s\s*\([^;]*\)\s*;)' % name, cls, re.M)
        if not m:
            sys.exit('declaration of Impl::%s not found' % name)
        decls.append('    ' + m.group(1))
        line_start = src.rfind('\n', 0, src.find('pptx_text_context::Impl::%s(' % name)) + 1
        ret = src[line_start:src.find('pptx_text_context::Impl::%s(' % name)].strip()
        defs.append('%s %s' % (ret, body.replace('pptx_text_context::Impl::', 'Impl::')))
    pe = read(PARA)
    lb = extract(pe, 'void line_break::pptx_convert(oox::pptx_conversion_context & Context)')
    if lb is None:
        sys.exit('line_break::pptx_convert not found - the extractor needs updating')
    lb = lb.replace('line_break::pptx_convert', 'static line_break_pptx_convert')
    facade = '    void add_line_break() { i.add_line_break(); }' if 'add_line_break' in have else ''
    code = (PRELUDE.replace('@@DECLS@@', '\n'.join(decls)).replace('@@DEFS@@', '\n'.join(defs))
            .replace('@@FACADE@@', facade).replace('@@LINEBREAK@@', lb.replace('void static', 'static void')))
    work = tempfile.mkdtemp(prefix='i2566-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(code)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=c++17', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    where = 'baseline ' + BASE_REF if BASELINE else 'working tree'
    checks = [
        ('LINEBREAK', 'LINEBREAK title=1 name=1 br=2', 'title text before two <text:line-break/> kept, two <a:br/>'),
        ('NESTED', 'NESTED paras=2 emptyStyled=2', 'nested list adds no empty paragraph; empty <text:p P1/> kept once'),
        ('OUTLINE', 'OUTLINE text=1 para=1 level1=0', 'list level 3 cascades Testo-outline3; level 1 adds none'),
    ]
    ok_all = r.returncode == 0 and 'AddressSanitizer' not in out
    for tag, want, what in checks:
        line = next((l for l in out.splitlines() if l.startswith(tag + ' ')), '(no output)')
        ok = line.startswith(want)
        ok_all = ok_all and ok
        print('%s %s (%s): %s' % ('ok  ' if ok else 'FAIL', what, where, line.split(' :: ')[0]))
    if r.returncode or 'AddressSanitizer' in out:
        print(out[-2000:])
    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
