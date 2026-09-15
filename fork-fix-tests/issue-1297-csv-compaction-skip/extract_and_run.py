#!/usr/bin/env python3
r"""
#1297 - "Spreadsheet can't import CSVs with a few megabytes" (and the same
defect is one candidate behind #1359's "Something has gone wrong").

The reported symptom is memory exhaustion, and that part is real but separate
(see the report).  What this test pins down is a *silent data corruption* in
the same reader that fires on exactly the files the issue names: any CSV big
enough for the parse loop to compact its buffer, which is to say anything over
about 500000 characters.

CSVReader::Impl::Read scans the whole file as one wide string and, to stop
nStartCell growing without bound, periodically throws away the part it has
already consumed:

    sFileDataW.erase(0, nIndex + nDelimiterSize);
    nSize -= (nIndex + nDelimiterSize); nIndex = 0;
    pTemp = sFileDataW.c_str();

The erase moves a not-yet-examined character to index 0.  But this block sits
inside `for (size_t nIndex = 0; nIndex < nSize; ++nIndex)`, whose ++nIndex runs
the instant the block ends - so the parse resumed at index 1 and stepped
straight over index 0.  An ordinary letter there costs nothing, which is why
the bug hides.  A delimiter, a quote, a tab or a newline there loses its
meaning: the cell boundary disappears and the text on both sides of it is
merged into one cell, carrying the raw separator inside it.

Compaction happens once per 500000 characters, so a 5 MB file is corrupted
about ten times and an 85 MB file about a hundred and seventy.

There are TWO such blocks - one in the delimiter branch, one in the newline
branch - and they are independent code paths.  This test drives each of them
with its own input, so a fix to only one of them still fails.

The test extracts the REAL parse loop out of CSVReader.cpp by brace matching
and runs it against stubs.  Nothing is pasted in; if the loop is edited the
test follows it.  The 500000 threshold is the real one, so the inputs really
are half a megabyte.

  BASELINE=1 re-reads CSVReader.cpp from git HEAD, where it must FAIL.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'OOXML/Binary/Sheets/Reader/CSVReader.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '1f81e91eca^')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(CORE, REL), encoding='utf-8').read()


def match_braces(text, open_brace):
    """Index of the '}' closing the '{' at open_brace."""
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced braces')


# ---- the real parse loop --------------------------------------------------
# Select it by what it is, not by position: the one loop in the file that walks
# nIndex over nSize.
m = re.search(r'^\tfor \(size_t nIndex = 0; nIndex < nSize; \+\+nIndex\)\s*$',
              src, re.M)
if not m:
    raise SystemExit('the parse loop was not found in %s - the extractor needs '
                     'updating' % REL)
ob = src.index('{', m.end())
parse_loop = src[m.start():match_braces(src, ob) + 1]

# Sanity: we grabbed the whole loop, both compaction sites and all four of the
# branches whose characters the skip can swallow.
for needle in ('wcDelimiterLeading == wcCurrent',
               'wcNewLineN == wcCurrent',
               'wcQuote == wcCurrent',
               'wcTab == wcCurrent',
               'oDeleteChars.push(nIndex)',
               'AddCell(sCellText'):
    if needle not in parse_loop:
        raise SystemExit('extracted loop is missing %r - wrong block?' % needle)

n_compactions = parse_loop.count('sFileDataW.erase(0,')
if n_compactions != 2:
    raise SystemExit('expected exactly 2 compaction sites in the parse loop, '
                     'found %d - the extractor needs updating' % n_compactions)

harness = r'''
#include <stdio.h>
#include <string>
#include <stack>
#include <vector>

typedef int INT;
typedef wchar_t WCHAR;
#define _T(x) L##x

/* ---- just enough of Read()'s surroundings to run its parse loop ----------
 *
 * AddCell is reproduced from CSVReader::Impl::AddCell rather than extracted,
 * because the real one builds OOX::Spreadsheet::CCell objects and runs the
 * CellFormatController over them.  Only two things about it matter to the
 * loop, and both are kept exactly: it applies the pending oDeleteChars
 * (relative to nStartCell) and it declines to store an empty cell.  What this
 * test measures is which text the LOOP hands it, and at which column. */
struct Cell { int row; int col; std::wstring text; };
static std::vector<Cell> g_cells;

/* The loop allocates its rows itself, as OOX::Spreadsheet::CRow, and stamps
 * the 1-based row number into m_oR.  Stub just that shape. */
namespace OOX { namespace Spreadsheet {
    struct RowNumber { int value; void SetValue(int v) { value = v; } };
    struct NullableRowNumber {
        RowNumber n;
        void Init() { n.value = 0; }
        RowNumber *operator->() { return &n; }
    };
    struct CRow {
        NullableRowNumber m_oR;
        void storeXmlCache() {}
    };
} }
using OOX::Spreadsheet::CRow;

static int AddCell(std::wstring &sText, INT nStartCell, std::stack<INT> &oDeleteChars,
                   CRow &oRow, INT nRow, INT nCol, bool bIsWrap)
{
    (void)oRow; (void)bIsWrap;
    while (!oDeleteChars.empty())
    {
        INT nAt = oDeleteChars.top() - nStartCell;
        sText.erase(nAt, 1);
        oDeleteChars.pop();
    }
    if (sText.empty() || sText[0] == L'\0')
        return 0;                    /* CSVReader::Impl::AddCell: "Don't write empty" */
    Cell c; c.row = nRow; c.col = nCol; c.text = sText;
    g_cells.push_back(c);
    return 0;
}

struct SheetData {
    std::vector<CRow*> m_arrItems;
    void AddRowToCache(CRow &) {}
};
struct SheetDataHolder {
    SheetData sd;
    SheetData *operator->() { return &sd; }
};
struct Worksheet { SheetDataHolder m_oSheetData; };

/* Run the real parse loop over one buffer, exactly as Read() sets it up for a
 * single-character comma delimiter. */
static void runLoop(const std::wstring &input)
{
    g_cells.clear();

    std::wstring sFileDataW = input;
    size_t nSize = sFileDataW.length();

    Worksheet ws; Worksheet *pWorksheet = &ws;

    WCHAR wcDelimiterLeading  = L',';
    WCHAR wcDelimiterTrailing = L'\0';
    int   nDelimiterSize      = 1;

    const WCHAR wcNewLineN = _T('\n');
    const WCHAR wcNewLineR = _T('\r');
    const WCHAR wcQuote    = _T('"');
    const WCHAR wcTab      = _T('\t');

    bool bIsWrap = false;
    WCHAR wcCurrent;
    INT nStartCell = 0;
    std::stack<INT> oDeleteChars;

    bool bMsLimit     = false;
    bool bMsLimitCell = false;
    bool bInQuote     = false;
    bool readToCache  = false;

    INT nIndexRow = 0;
    INT nIndexCol = 0;
    CRow *pRow = new CRow();

    const WCHAR *pTemp = sFileDataW.c_str();

%(parse_loop)s

    (void)bMsLimit; (void)bMsLimitCell; (void)wcTab; (void)wcNewLineR;
    delete pRow;
    for (size_t i = 0; i < pWorksheet->m_oSheetData->m_arrItems.size(); ++i)
        delete pWorksheet->m_oSheetData->m_arrItems[i];
}

/* ------------------------------------------------------------------------ */
static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-72s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static std::wstring repeat(const std::wstring &unit, size_t times)
{
    std::wstring out;
    out.reserve(unit.size() * times);
    for (size_t i = 0; i < times; ++i) out += unit;
    return out;
}

static std::string narrow(const std::wstring &w)
{
    std::string s;
    for (size_t i = 0; i < w.size(); ++i)
    {
        wchar_t c = w[i];
        if (c == L'\n') { s += "\\n"; }
        else if (c < 128) s += (char)c;
        else s += '?';
    }
    return s;
}

/* Find the cells the loop produced for one row. */
static std::vector<Cell> rowCells(int row)
{
    std::vector<Cell> out;
    for (size_t i = 0; i < g_cells.size(); ++i)
        if (g_cells[i].row == row) out.push_back(g_cells[i]);
    return out;
}

static void describe(const char *label, int row)
{
    std::vector<Cell> r = rowCells(row);
    printf("     %%s row %%d ->", label, row);
    if (r.empty()) printf(" (no cells)");
    for (size_t i = 0; i < r.size(); ++i)
        printf(" [col %%d]=\"%%s\"", r[i].col, narrow(r[i].text).c_str());
    printf("\n");
}

int main()
{
    /* ---------------- 1. the compaction site in the DELIMITER branch -------
     *
     * Unit "a,,b\n" is 5 characters, so the specials sit at 5k+1, 5k+2, 5k+4.
     * The first one at or past 500000 is the comma at 500001, which trips
     * `nIndex + nDelimiterSize > 500000`.  The erase then puts the SECOND
     * comma of that row - index 500002 - at index 0 of the compacted buffer.
     *
     * Correct: that comma still closes an (empty) cell, so the row reads
     *   [col 0]="a"   (empty col 1 is not stored)   [col 2]="b"
     * Skipped: the comma is never seen, so "b" is glued to it and lands a
     * column early:
     *   [col 0]="a"   [col 1]=",b"
     */
    {
        const size_t rows = 200000;
        std::wstring input = repeat(L"a,,b\n", rows);
        const int hit = 100000;          /* the row that straddles index 500000 */

        printf("delimiter-branch compaction (unit \"a,,b\\n\", %%zu rows, "
               "%%zu chars):\n", rows, input.size());
        runLoop(input);
        describe("  ", hit);

        std::vector<Cell> r = rowCells(hit);
        check(r.size() == 2 && r[0].col == 0 && r[0].text == L"a"
                            && r[1].col == 2 && r[1].text == L"b",
              "the delimiter moved to index 0 still closes its cell");

        /* Every other row must be untouched - the fix must not disturb them. */
        bool othersOk = true;
        for (size_t row = 0; row < rows && othersOk; ++row)
        {
            if ((int)row == hit) continue;
            std::vector<Cell> o = rowCells((int)row);
            if (!(o.size() == 2 && o[0].col == 0 && o[0].text == L"a"
                                && o[1].col == 2 && o[1].text == L"b"))
                othersOk = false;
        }
        check(othersOk, "and every other row still reads a / (empty) / b");
    }

    /* ---------------- 2. the compaction site in the NEWLINE branch ---------
     *
     * A different block, so it needs its own input.  Unit "ab\n" has no
     * delimiter at all, which keeps the delimiter branch (and its compaction)
     * out of the way entirely.  Newlines sit at 3k+2; the first at or past
     * 500000 is exactly 500000, tripping `nIndex + 1 > 500000`.  The erase
     * puts index 500001 at index 0 - and we place a comma there.
     *
     * Correct: that comma opens the row with an empty first cell, so "Q"
     * belongs to column 1.
     * Skipped: the comma is swallowed into the cell text and "Q" lands in
     * column 0 as ",Q".
     */
    {
        const size_t lead = 166667;      /* 3 * 166667 = 500001 chars, last is \n */
        std::wstring input = repeat(L"ab\n", lead) + L",Q\n" + repeat(L"ab\n", 10);
        const int hit = (int)lead;       /* the row right after the compaction */

        printf("\nnewline-branch compaction (unit \"ab\\n\", %%zu chars):\n",
               input.size());
        runLoop(input);
        describe("  ", hit);

        std::vector<Cell> r = rowCells(hit);
        check(r.size() == 1 && r[0].col == 1 && r[0].text == L"Q",
              "the delimiter moved to index 0 still opens an empty first cell");

        std::vector<Cell> before = rowCells(hit - 1);
        std::vector<Cell> after  = rowCells(hit + 1);
        check(before.size() == 1 && before[0].col == 0 && before[0].text == L"ab",
              "the row before the compaction is intact");
        check(after.size() == 1 && after[0].col == 0 && after[0].text == L"ab",
              "the row after it is intact");
    }

    /* ---------------- 3. a quote at the boundary ---------------------------
     *
     * The skip is not specific to delimiters; index 0 is simply never
     * examined.  Here the character the erase moves to index 0 is the opening
     * quote of a quoted field that contains a comma.  If the quote is
     * swallowed, the comma inside the field splits it into two cells - the
     * classic "my CSV gained columns" corruption.
     *
     * Unit "ab\n" again, so the compaction is the newline one at index 500000
     * and index 500001 is the quote we plant.
     */
    {
        const size_t lead = 166667;
        std::wstring input = repeat(L"ab\n", lead) + L"\"x,y\"\n" + repeat(L"ab\n", 4);
        const int hit = (int)lead;

        printf("\nquote at the compaction boundary (%%zu chars):\n", input.size());
        runLoop(input);
        describe("  ", hit);

        std::vector<Cell> r = rowCells(hit);
        check(r.size() == 1 && r[0].col == 0 && r[0].text == L"x,y",
              "the quoted field survives as one cell containing its comma");
    }

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - compaction no longer swallows the character it shifts to index 0");
    return failures ? 1 : 0;
}
''' % {'parse_loop': parse_loop}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    cmd = ['clang++', '-std=c++14', '-O1', '-Wall',
           '-Wno-unused-variable', '-Wno-unused-but-set-variable',
           '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
