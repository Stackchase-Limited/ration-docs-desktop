#!/usr/bin/env python3
r"""
#2556 - "Rows don't stay hidden" (spreadsheet, .ods).

Select every row below the first few, Hide rows, save as .ods, reopen: the rows
are visible again (hidden columns survive).  Reproduced end to end with the
headless cell editor and the real desktop save (x2t replaying changes0.json):
with the shipped x2t only row 6 is hidden after reopening; with the fixed one
all 1048571 rows are.

The desktop saves .ods as Editor.bin -> xlsx dir -> ods, and opens it as
ods -> xlsx dir -> Editor.bin.  Four places in core each lose part of a run of
hidden rows:

  W1  OOXML/XlsxFormat/Worksheets/SheetData.cpp  CSheetData::compressRow
      folds a run of empty rows into one CRow (m_oRepeated) comparing only r, s
      and ht, so a hidden row swallowed a visible one and vice versa.
  W2  OdfFile/Writer/Converter/XlsxConverter.cpp  XlsxConverter::convert(CRow)
      ignored m_oRepeated, so a folded run of hidden rows was written as ONE
      hidden table-row.
  R1  OdfFile/Reader/Format/table_xlsx.cpp  table_table_row::xlsx_convert
      wrote only the first row of a repeated empty row, and skipped an empty
      run longer than 0x0f00 rows outright, visibility="collapse" or not.
  R2  same file, table_rows::xlsx_convert, merged trailing empty rows while
      comparing the last row's style with itself (row_last for row_last_1) and
      never the visibility, so a visible trailing row joined a hidden run.

The test extracts those four functions (plus table_table_row::empty and
empty_content_cells from table.cpp, which R1 calls) from the REAL sources by
brace matching and runs them against minimal stubs of the OOX row model, the
ods writer context and the xlsx conversion context.  Nothing of the logic under
test is pasted in.  Each scenario fails on the baseline for its own reason, so a
fix to only some of the four places still fails.

What is NOT claimed: the stubs record which rows are written and whether they
carry the hidden flag; they do not produce real XML, styles or cells, and
nothing here checks row heights, outline groups or comments in a run (those
paths are unchanged).  The end-to-end check lives in the agent report.

  RD_REPO    core checkout (default ../../core)
  BASELINE=1 reads the sources via `git show $BASE_REF:<path>`; must FAIL there.
  BASE_REF   default '273f1f6558^' (re-pin after cherry-picking).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '273f1f6558^')

SHEETDATA = 'OOXML/XlsxFormat/Worksheets/SheetData.cpp'
XLSXCONV = 'OdfFile/Writer/Converter/XlsxConverter.cpp'
TABLE_XLSX = 'OdfFile/Reader/Format/table_xlsx.cpp'
TABLE_CPP = 'OdfFile/Reader/Format/table.cpp'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def extract(src, signature, rel):
    """The whole function whose definition starts with `signature`."""
    i = src.find(signature)
    if i < 0 or src.find(signature, i + 1) >= 0:
        raise SystemExit('%r not found exactly once in %s - the extractor needs updating' % (signature, rel))
    ob = src.index('{', i + len(signature))
    depth = 0
    for j in range(ob, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise SystemExit('unbalanced braces in %s' % rel)


sd, xc, tx, tc = read(SHEETDATA), read(XLSXCONV), read(TABLE_XLSX), read(TABLE_CPP)
compress_row = extract(sd, 'bool CSheetData::compressRow(CRow* pRow)', SHEETDATA)
convert_row = extract(xc, 'void XlsxConverter::convert(OOX::Spreadsheet::CRow *oox_row, OOX::Spreadsheet::CRow *oox_row_prev)', XLSXCONV)
row_convert = extract(tx, 'void table_table_row::xlsx_convert(oox::xlsx_conversion_context & Context)', TABLE_XLSX)
rows_convert = extract(tx, 'void table_rows::xlsx_convert(oox::xlsx_conversion_context & Context)', TABLE_XLSX)
row_empty = extract(tc, 'bool table_table_row::empty()', TABLE_CPP)
row_empty_cells = extract(tc, 'bool table_table_row::empty_content_cells(bool bWithCellStyle)', TABLE_CPP)

for needle, body in (('prevRow->m_oRepeated', compress_row), ('add_row_repeated', convert_row),
                     ('add_empty_row', row_convert), ('table_number_rows_repeated_ +=', rows_convert)):
    if needle not in body:
        raise SystemExit('extracted function lacks %r - wrong block?' % needle)

HARNESS = r'''
#include <cstdio>
#include <string>
#include <sstream>
#include <vector>
#include <memory>
#include <set>

/* ================= writer side: OOX row model + ods writer context ================= */
struct Num {                     /* stands in for COnOff / CDouble / CUnsignedDecimalNumber */
    double v;
    Num(double x = 0) : v(x) {}
    double GetValue() const { return v; }
    bool ToBool() const { return v != 0; }
    void SetValue(double x) { v = x; }
    bool operator==(const Num &o) const { return v == o.v; }
};
template<class T> struct nullable {
    std::shared_ptr<T> p;
    bool IsInit() const { return (bool)p; }
    T *operator->() const { return p.get(); }
    T &operator*() const { return *p; }
    nullable &operator=(const T &v) { p = std::make_shared<T>(v); return *this; }
    void reset() { p.reset(); }
    bool operator==(const nullable &o) const { if (!p && !o.p) return true; if (!p || !o.p) return false; return *p == *o.p; }
};
struct nullable_uint {           /* OOXML/Base/Nullable.h nullable_uint, as far as used */
    bool init = false; unsigned int v = 0;
    bool IsInit() const { return init; }
    unsigned int get() const { return v; }
    unsigned int get_value_or(unsigned int d) const { return init ? v : d; }
    nullable_uint &operator=(unsigned int x) { init = true; v = x; return *this; }
    void reset() { init = false; v = 0; }
};
struct nullable_int_ { bool init = false; int v = 0;
    bool IsInit() const { return init; } int get() const { return v; }
    int get_value_or(int d) const { return init ? v : d; } };

namespace SimpleTypes { namespace Spreadsheet { enum { celltypeSharedString = 1 }; } }
namespace OOX { namespace Spreadsheet {
struct CCell {
    nullable_uint m_oRepeated; nullable_int_ m_oStyle, m_oCol;
    nullable<Num> m_oValue, m_oFormula;
};
struct CRow {
    std::vector<CCell *> m_arrItems;
    nullable<Num> m_oCollapsed, m_oCustomFormat, m_oCustomHeight, m_oHidden, m_oHt,
                  m_oOutlineLevel, m_oPh, m_oR, m_oS, m_oThickBot, m_oThickTop, m_oDyDescent;
    nullable_uint m_oRepeated;
};
struct CSheetData {
    std::vector<CRow *> m_arrItems;
    bool compressRow(CRow* pRow);
};
''' + compress_row + r'''
} }

namespace odf_types { struct style_family { enum type { TableCell, TableRow }; }; }
struct OdsRow { int start; int repeated; bool hidden; };
static std::vector<OdsRow> g_ods;
struct ods_table_stub {
    int is_row_comment(int, int) { return -1; }
    int is_row_validation(int, int &) { return -1; }
    void set_row_hidden(bool) { g_ods.back().hidden = true; }
    void set_row_default_cell_style(std::wstring &) {}
    void set_row_height(double) {}
    void set_row_optimal_height(bool) {}
};
struct ods_styles_stub { std::wstring find_odf_style_name(int, odf_types::style_family::type, bool, bool) { return L""; } };
struct ods_context_stub {
    ods_table_stub t; ods_styles_stub s;
    ods_table_stub *current_table() { return &t; }
    ods_styles_stub *styles_context() { return &s; }
    void start_row(int r, int repeated, int, bool) { g_ods.push_back(OdsRow{r, repeated, false}); }
    void end_row() {}
    void add_row_repeated() { g_ods.back().repeated++; }
};
class XlsxConverter {
public:
    ods_context_stub ctx; ods_context_stub *ods_context = &ctx;
    void convert(OOX::Spreadsheet::CRow *oox_row, OOX::Spreadsheet::CRow *oox_row_prev);
    void convert(OOX::Spreadsheet::CCell *) {}
};
''' + convert_row + r'''

/* ================= reader side: odf row model + xlsx conversion context ================= */
struct RowRec { long r; bool hidden; };
static std::vector<RowRec> g_xlsx;
static void begin_node(const wchar_t *name) { if (std::wstring(name) == L"row") g_xlsx.push_back(RowRec{0, false}); }
template<class T> static void attr(const wchar_t *name, const T &v) {
    std::wstringstream s; s << v; std::wstring n(name);
    if (n == L"r") g_xlsx.back().r = std::stol(s.str());
    if (n == L"hidden") g_xlsx.back().hidden = s.str() == L"1";
}
#define CP_XML_WRITER(s) if (true)
#define CP_XML_NODE(n) if ((begin_node(n), true))
#define CP_XML_ATTR(n, v) attr(n, v)
static std::wstringstream g_stream;
#define CP_XML_STREAM() g_stream

template<class T> struct optional_ {
    std::shared_ptr<T> p;
    optional_() {} optional_(const T &v) : p(std::make_shared<T>(v)) {}
    explicit operator bool() const { return (bool)p; }
    bool operator!() const { return !p; }
    T *operator->() const { return p.get(); } T &operator*() const { return *p; }
    T get_value_or(const T &d) const { return p ? *p : d; }
};
namespace odf_types {
struct table_visibility { enum type { Visible, Collapse, Filter }; type t = Visible; type get_type() const { return t; } };
struct length { enum unit { pt }; double get_value_unit(unit) const { return 0; } };
struct fo_break { enum type { Page }; type get_type() const { return Page; } };
}
namespace oox { struct xlsx_conversion_context; }
namespace odf_reader {
using namespace odf_types;
struct style_table_cell_properties {};
struct style_table_cell_properties_attlist {};
struct style_table_row_properties { struct { optional_<length> style_row_height_; optional_<bool> style_use_optimal_row_height_;
    struct { optional_<fo_break> fo_break_before_, fo_break_after_; } common_break_attlist_; } attlist_; };
struct style_content { style_table_cell_properties *get_style_table_cell_properties() { return 0; }
    style_table_row_properties *get_style_table_row_properties() { return 0; } };
struct style_instance { style_content *content() { return 0; } };
static style_table_cell_properties_attlist calc_table_cell_properties(style_instance *) { return style_table_cell_properties_attlist(); }
struct styles_container_stub { style_instance *style_by_name(const std::wstring &, style_family::type, bool) { return 0; } };
struct odf_read_context { styles_container_stub s; styles_container_stub &styleContainer() { return s; } };

struct office_element { virtual ~office_element() {} virtual void xlsx_convert(oox::xlsx_conversion_context &) {} };
typedef std::shared_ptr<office_element> office_element_ptr;
struct table_table_cell : office_element {
    struct { unsigned int table_number_columns_repeated_ = 1; } attlist_;
    bool last_cell_ = false;
    bool value = false;                     /* false: an empty <table:table-cell number-columns-repeated=../> */
    bool empty(bool) { return !value; }
    void xlsx_convert(oox::xlsx_conversion_context &Context);
};
struct table_covered_table_cell : office_element { bool last_cell_ = false; bool empty() { return true; } };
struct table_table_row : office_element {
    struct { unsigned int table_number_rows_repeated_ = 1; optional_<std::wstring> table_style_name_, table_default_cell_style_name_;
             table_visibility table_visibility_; } attlist_;
    std::vector<office_element_ptr> content_;
    bool bHeader = false;
    bool empty();
    bool empty_content_cells(bool bWithCellStyle = true);
    void xlsx_convert(oox::xlsx_conversion_context &Context);
};
struct table_table_rows { void xlsx_convert(oox::xlsx_conversion_context &) {} };
struct table_rows {
    std::shared_ptr<table_table_rows> table_table_rows_;
    std::vector<office_element_ptr> table_table_row_;
    void xlsx_convert(oox::xlsx_conversion_context &Context);
};
}
namespace oox {
struct xlsx_table_state {
    long current = -1; bool endTable = false, emptyRow = true;
    std::vector<bool> group_rows_;
    bool get_end_table() { return endTable; } void set_end_table() { endTable = true; }
    void add_empty_row(int count, bool) { current += count; }
    void start_row(const std::wstring &, const std::wstring &, bool) { emptyRow = true; current++; }
    void set_row_break_before() {} void set_row_break_after() {}
    void end_row() {} bool is_empty_row() const { return emptyRow; }
};
struct xlsx_table_context { xlsx_table_state st; xlsx_table_state *state() { return &st; } int columns_count() { return 1024; } };
struct xlsx_sheet_stub { std::wstringstream s; std::wostream &sheetData() { return s; } };
struct xlsx_root_stub { odf_reader::odf_read_context c; odf_reader::odf_read_context &odf_context() { return c; } };
struct style_manager_stub { size_t xfId(void *, void *, odf_reader::style_table_cell_properties_attlist *, void *, const std::wstring &, int, bool) { return 0; } };
struct table_metrics_stub { void add_rows(int, double) {} };
struct xlsx_conversion_context {
    xlsx_table_context tc; xlsx_sheet_stub sh; xlsx_root_stub rt; style_manager_stub sm; table_metrics_stub tm;
    xlsx_table_context &get_table_context() { return tc; }
    xlsx_sheet_stub &current_sheet() { return sh; }
    xlsx_root_stub *root() { return &rt; }
    style_manager_stub &get_style_manager() { return sm; }
    table_metrics_stub &get_table_metrics() { return tm; }
    long current_table_row() { return tc.st.current; }
};
}
namespace odf_reader {
void table_table_cell::xlsx_convert(oox::xlsx_conversion_context &Context) { if (value) Context.get_table_context().state()->emptyRow = false; }
''' + row_empty + '\n' + row_empty_cells + '\n' + row_convert + '\n' + rows_convert + r'''
}

/* ================================== scenarios ================================== */
using namespace OOX::Spreadsheet;
static int g_fail = 0;
static void check(bool ok, const char *what) { printf("%s %s\n", ok ? "PASS" : "FAIL", what); if (!ok) g_fail = 1; }

static CRow *mkrow(int r, bool value, bool hidden, int outline = 0) {
    CRow *row = new CRow(); row->m_oR = Num(r);
    if (hidden) row->m_oHidden = Num(1);
    if (outline) row->m_oOutlineLevel = Num(outline);
    if (value) { CCell *c = new CCell(); c->m_oValue = Num(r); row->m_arrItems.push_back(c); }
    return row;
}
/* reads rows exactly as CSheetData::fromXML does (compressRow), then writes them as
   XlsxConverter's sheet loop does (convert(row, prev)); returns the hidden state per row */
static std::vector<int> write_ods(std::vector<CRow *> rows, int last) {
    CSheetData sd;
    for (CRow *r : rows) if (!sd.compressRow(r)) sd.m_arrItems.push_back(r);
    g_ods.clear();
    XlsxConverter conv;
    for (size_t i = 0; i < sd.m_arrItems.size(); i++) conv.convert(sd.m_arrItems[i], i > 0 ? sd.m_arrItems[i - 1] : NULL);
    std::vector<int> state(last + 1, -1);                 /* -1 not written, 0 visible, 1 hidden */
    for (const OdsRow &o : g_ods) for (int k = 0; k < o.repeated; k++) if (o.start + k <= last) state[o.start + k] = o.hidden;
    return state;
}

using namespace odf_reader;
static office_element_ptr odf_row(unsigned repeated, bool hidden, bool value_cell) {
    auto row = std::make_shared<table_table_row>();
    row->attlist_.table_number_rows_repeated_ = repeated;
    row->attlist_.table_style_name_ = optional_<std::wstring>(hidden ? L"ro2" : L"ro1");
    if (hidden) row->attlist_.table_visibility_.t = table_visibility::Collapse;
    auto cell = std::make_shared<table_table_cell>();
    cell->attlist_.table_number_columns_repeated_ = value_cell ? 1 : 1024;
    cell->value = value_cell;
    row->content_.push_back(cell);
    return row;
}
/* converts one ods table's rows as the reader does; returns the set of hidden xlsx rows and the max r */
static std::set<long> read_ods(std::vector<office_element_ptr> rows, long *max_r) {
    g_xlsx.clear();
    oox::xlsx_conversion_context ctx;
    table_rows tr; tr.table_table_row_ = rows;
    tr.xlsx_convert(ctx);
    std::set<long> hidden; *max_r = 0;
    for (const RowRec &r : g_xlsx) { if (r.hidden) hidden.insert(r.r); if (r.r > *max_r) *max_r = r.r; }
    return hidden;
}

int main() {
    /* W: rows 1-5 hold a value, rows 6..1000 are hidden and empty (what the editor writes
       after selecting 6:1048576 -> Hide rows, shortened) */
    {
        std::vector<CRow *> rows;
        for (int r = 1; r <= 5; r++) rows.push_back(mkrow(r, true, false));
        for (int r = 6; r <= 1000; r++) rows.push_back(mkrow(r, false, true));
        std::vector<int> st = write_ods(rows, 1000);
        int hidden = 0; bool ok = true;
        for (int r = 6; r <= 1000; r++) { if (st[r] == 1) hidden++; else ok = false; }
        char msg[160]; snprintf(msg, sizeof msg, "writer: hidden rows 6..1000 are all written hidden (%d of 995)", hidden);
        check(ok, msg);
    }
    /* W: an outline row followed by hidden rows, and a hidden row followed by an outline row:
       compressRow must not fold rows whose properties differ */
    {
        std::vector<CRow *> rows = { mkrow(1, true, false), mkrow(6, false, false, 1), mkrow(7, false, true), mkrow(8, false, true) };
        std::vector<int> st = write_ods(rows, 8);
        check(st[6] == 0 && st[7] == 1 && st[8] == 1, "writer: visible outline row 6 + hidden rows 7-8 keep their own visibility");
        rows = { mkrow(1, true, false), mkrow(6, false, true), mkrow(7, false, false, 1) };
        st = write_ods(rows, 7);
        check(st[6] == 1 && st[7] == 0, "writer: hidden row 6 does not hide the visible row 7 after it");
    }
    /* R: what the fixed writer produces for the issue: 5 rows, a hidden run, then the
       writer's trailing default row */
    {
        long max_r;
        std::vector<office_element_ptr> rows;
        for (int r = 1; r <= 5; r++) rows.push_back(odf_row(1, false, true));
        rows.push_back(odf_row(995, true, false));
        rows.push_back(odf_row(1, false, false));
        std::set<long> h = read_ods(rows, &max_r);
        char msg[160]; snprintf(msg, sizeof msg, "reader: repeated hidden row (995) gives hidden rows 6..1000 (%zu hidden, first %ld, last %ld)",
                                h.size(), h.empty() ? 0L : *h.begin(), h.empty() ? 0L : *h.rbegin());
        check(h.size() == 995 && *h.begin() == 6 && *h.rbegin() == 1000, msg);
        check(h.count(1001) == 0, "reader: the visible trailing row 1001 is not merged into the hidden run");
    }
    /* R: hidden down to the end of the sheet - a run far longer than 0x0f00 */
    {
        long max_r;
        std::vector<office_element_ptr> rows;
        for (int r = 1; r <= 5; r++) rows.push_back(odf_row(1, false, true));
        rows.push_back(odf_row(1048571, true, false));
        std::set<long> h = read_ods(rows, &max_r);
        char msg[160]; snprintf(msg, sizeof msg, "reader: hidden run 6..1048576 is read as 1048571 hidden rows (%zu)", h.size());
        check(h.size() == 1048571 && *h.begin() == 6 && *h.rbegin() == 1048576, msg);
    }
    /* R: unchanged behaviour - a long VISIBLE empty run is still skipped, not expanded */
    {
        long max_r;
        std::vector<office_element_ptr> rows;
        for (int r = 1; r <= 5; r++) rows.push_back(odf_row(1, false, true));
        rows.push_back(odf_row(1048571, false, false));
        read_ods(rows, &max_r);
        char msg[160]; snprintf(msg, sizeof msg, "reader: a long visible empty run is still not expanded (last row written %ld)", max_r);
        check(max_r >= 5 && max_r <= 6, msg);
    }
    printf(g_fail ? "RESULT: FAIL\n" : "RESULT: PASS\n");
    return g_fail;
}
'''

with tempfile.TemporaryDirectory(prefix='rd2556-') as d:
    src = os.path.join(d, 't.cpp')
    exe = os.path.join(d, 't')
    with open(src, 'w') as f:
        f.write(HARNESS)
    subprocess.run(['c++', '-std=c++14', '-w', '-O1', src, '-o', exe], check=True)
    print('sources: %s%s' % (REPO, ' @ ' + BASE_REF if os.environ.get('BASELINE') else ''), flush=True)
    sys.exit(subprocess.run([exe]).returncode)
