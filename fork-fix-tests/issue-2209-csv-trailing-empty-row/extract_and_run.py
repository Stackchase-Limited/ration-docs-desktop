#!/usr/bin/env python3
"""
#2209 - "TXT/CSV import creates extra lines".

The reporter blames a line break inside a quoted field.  That part does NOT
reproduce: the shipped x2t converts

    "aaa","b\\nbb","ccc"\\nzzz,yyy,xxx\\n

into B1 = "b&#xA;bb" as one cell, on two data rows.  What it ALSO produces is a
third, completely empty <row r="3"/> - an extra line, on every CSV or TXT file
that ends with a newline, which is to say on essentially every well-formed file
(RFC 4180 lets the last record end with a line break).  Files that happen to end
without a trailing newline import with the right number of rows.  That is the
real core defect behind the title.

Mechanism, both halves of which this test compiles from the real source:

1. CSVReader::Impl::utf8_2_unicode sizes the destination string in BYTES
   (`wStr.resize(data_size + 1)`) and never trims it to the number of wchar_t
   the conversion actually wrote.  For pure ASCII the string therefore reports
   data_size + 1 characters with one trailing L'\\0'; for multibyte UTF-8 the
   overshoot is larger.  CSVReader::Impl::Read takes that inflated value as
   `nSize = sFileDataW.length()`.

2. Read's end-of-data block is guarded by `nStartCell != nSize`.  After the
   final newline the parse loop has already flushed the last row and set
   nStartCell to the true character count, so with an honest length the guard is
   false and the freshly-allocated empty row is released.  With the inflated
   length the guard is true, the block strips the NUL padding, builds an EMPTY
   cell text, AddCell declines to add a cell - and the block then pushes the
   empty row anyway.

The block must NOT simply be taught to skip empty trailing text: a file whose
last line is ",," is a genuine row of empty cells and must still be emitted.
The fix is therefore in utf8_2_unicode, which is where the length is wrong.

This test extracts BOTH the real utf8_2_unicode and the real end-of-data block
out of CSVReader.cpp by brace matching, links them against the real
OOXML/Base/unicode_util.cpp, and checks:
  - utf8_2_unicode reports the true character count, and
  - the real end-of-data block, fed that count, emits no empty final row for a
    file ending in a newline while still emitting the last row for a file that
    does not.

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
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

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


# ---- 1. the real utf8_2_unicode ------------------------------------------
SIG = 'void utf8_2_unicode(const unsigned char* data, DWORD data_size, std::wstring &wStr)'
at = src.find(SIG)
if at == -1:
    raise SystemExit('utf8_2_unicode not found in %s - the extractor needs updating' % REL)
ob = src.index('{', at + len(SIG) - 1)
utf8_fn = src[at:match_braces(src, ob) + 1]

# ---- 2. the real end-of-data block ---------------------------------------
# Select it by what it does, not by position: it is the only `if` in the file
# guarded on `nStartCell != nSize && !bMsLimit`.  Take its `else` too, since
# that is the branch that releases the surplus row.
m = re.search(r'^\tif \(nStartCell != nSize && !bMsLimit\)\s*$', src, re.M)
if not m:
    raise SystemExit('the `nStartCell != nSize && !bMsLimit` block was not found '
                     '- the extractor needs updating')
ob = src.index('{', m.end())
end_if = match_braces(src, ob)
m_else = re.compile(r'\s*else\s*\{').match(src, end_if + 1)
if not m_else:
    raise SystemExit('the end-of-data block has no `else` - the extractor needs updating')
tail_block = src[m.start():match_braces(src, src.index('{', end_if + 1)) + 1]

# Sanity: we grabbed the right thing.
for needle in ('while (nSize > 0)', 'AddCell(sCellText', 'RELEASEOBJECT(pRow)'):
    if needle not in tail_block:
        raise SystemExit('extracted block is missing %r - wrong block?' % needle)

harness = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <stack>
#include <vector>
#include "unicode_util.h"

typedef unsigned int DWORD;
typedef int INT;
typedef wchar_t WCHAR;

/* ---- the real utf8_2_unicode, lifted verbatim out of CSVReader.cpp ---- */
%(utf8_fn)s

/* ---- just enough of Read()'s surroundings to run its end-of-data block ----
 * AddCell keeps CSVReader's own "don't write empty" contract so the block sees
 * the same return value it sees in production. */
struct CRow { int r; void storeXmlCache() {} };
static std::vector<std::wstring>  g_cells;   /* text AddCell was asked to store */
static std::vector<CRow*>         g_pushed;  /* rows that reached the sheet */
static bool                       g_released = false;

static int AddCell(std::wstring &sText, INT nStartCell, std::stack<INT> &oDeleteChars,
                   CRow &oRow, INT nRow, INT nCol, bool bIsWrap)
{
    (void)nStartCell; (void)oDeleteChars; (void)oRow; (void)nRow; (void)nCol; (void)bIsWrap;
    if (sText.empty() || sText[0] == L'\0')
        return 0;                       /* CSVReader::Impl::AddCell: "Don't write empty" */
    g_cells.push_back(sText);
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

#define RELEASEOBJECT(p) do { g_released = true; delete (p); (p) = NULL; } while (0)

/* Run the real end-of-data block against one converted buffer. */
struct Outcome { size_t rows; bool released; std::vector<std::wstring> cells; };

static Outcome runTail(const std::wstring &data, size_t nStartCellIn, size_t nSizeIn)
{
    g_cells.clear(); g_pushed.clear(); g_released = false;

    Worksheet ws; Worksheet *pWorksheet = &ws;
    const WCHAR *pTemp = data.c_str();
    size_t nSize      = nSizeIn;
    INT nStartCell    = (INT)nStartCellIn;
    bool bMsLimit     = false;
    bool bMsLimitCell = false;
    bool bIsWrap      = false;
    bool readToCache  = false;
    INT nIndexRow = 1, nIndexCol = 0;
    std::stack<INT> oDeleteChars;
    CRow *pRow = new CRow();

%(tail_block)s

    (void)bMsLimitCell;
    Outcome o;
    o.rows = pWorksheet->m_oSheetData->m_arrItems.size();
    o.released = g_released;
    o.cells = g_cells;
    for (size_t i = 0; i < pWorksheet->m_oSheetData->m_arrItems.size(); ++i)
        delete pWorksheet->m_oSheetData->m_arrItems[i];
    return o;
}

/* ------------------------------------------------------------------------ */
static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-64s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

/* nStartCell as CSVReader's parse loop leaves it: one past the last delimiter
 * or newline it consumed.  For these unquoted-tail inputs that is exactly what
 * the loop computes. */
static size_t startCellOf(const std::wstring &s)
{
    size_t at = s.find_last_of(L",\n");
    return at == std::wstring::npos ? 0 : at + 1;
}

/* endsWithNewline == -1: excluded from the end-of-data check, because Read
 * flushes that row from a different branch (see the regression guard). */
struct Case { const char *name; const char *utf8; size_t chars; int endsWithNewline; };

int main()
{
    static const Case cases[] = {
        /* name                       bytes                                        chars  ends \n */
        { "ascii, trailing newline",  "a,b\nc,d\n",                                   8,  1  },
        { "ascii, no trailing nl",    "a,b\nc,d",                                     7,  0  },
        /* h\xc3\xa9llo,w\xc3\xb6rld - 11 chars from 13 bytes */
        { "utf-8 multibyte, nl",      "h\xc3\xa9llo,w\xc3\xb6rld\nfoo,bar\n",        20,  1  },
        { "utf-8 multibyte, no nl",   "h\xc3\xa9llo,w\xc3\xb6rld\nfoo,bar",          19,  0  },
        { "the #2209 file",           "\"aaa\",\"b\nbb\",\"ccc\"\nzzz,yyy,xxx\n",    31,  1  },
        { "last line is empty cells", "a,b\n,,",                                      6, -1  },
    };
    const size_t nCases = sizeof(cases) / sizeof(cases[0]);

    printf("utf8_2_unicode must report the number of characters, not of bytes:\n");
    for (size_t i = 0; i < nCases; ++i)
    {
        std::wstring w;
        size_t bytes = strlen(cases[i].utf8);
        utf8_2_unicode((const unsigned char *)cases[i].utf8, (DWORD)bytes, w);
        char buf[160];
        snprintf(buf, sizeof buf, "%%s: length()=%%zu (bytes=%%zu, chars=%%zu)",
                 cases[i].name, w.length(), bytes, cases[i].chars);
        check(w.length() == cases[i].chars, buf);
    }

    printf("\nthe real end-of-data block, given that length:\n");
    for (size_t i = 0; i < nCases; ++i)
    {
        if (cases[i].endsWithNewline < 0)
            continue;
        std::wstring w;
        utf8_2_unicode((const unsigned char *)cases[i].utf8,
                       (DWORD)strlen(cases[i].utf8), w);
        /* Read() uses the string's own length as nSize. */
        Outcome o = runTail(w, startCellOf(w), w.length());

        char buf[160];
        if (cases[i].endsWithNewline)
        {
            snprintf(buf, sizeof buf,
                     "%%s: emits no extra row (rows=%%zu, cells=%%zu)",
                     cases[i].name, o.rows, o.cells.size());
            check(o.rows == 0 && o.cells.empty() && o.released, buf);
        }
        else
        {
            snprintf(buf, sizeof buf,
                     "%%s: still emits the final row (rows=%%zu)",
                     cases[i].name, o.rows);
            check(o.rows == 1, buf);
        }
    }

    /* A last line of ",," is a real row of empty cells and must survive, even
     * though its trailing text is empty.  That is why the fix belongs in
     * utf8_2_unicode rather than in a "skip an empty tail" guard on the
     * end-of-data block - such a guard would silently drop this row.
     *
     * Read does not reach the end-of-data block for this input at all: the file
     * ends ON the delimiter, so the delimiter branch's own end-of-file test
     * (`nIndex + nDelimiterSize == nSize`) flushes the row first and leaves
     * nStartCell == nSize.  With the honest length that test lands exactly on
     * the last character; with the byte-sized length it missed by the padding
     * and the row was flushed by the end-of-data block instead.  Either way the
     * row is emitted - what the fix must not do is make it vanish. */
    printf("\nregression guard:\n");
    {
        std::wstring w;
        const char *s = "a,b\n,,";
        utf8_2_unicode((const unsigned char *)s, (DWORD)strlen(s), w);
        bool endsOnDelimiter = !w.empty() && w[w.length() - 1] == L',';
        check(endsOnDelimiter,
              "a final line of \",,\" ends on the delimiter, so Read's own "
              "end-of-file");
        check(w.length() == 6,
              "  test (nIndex + 1 == nSize) flushes that row before the "
              "end-of-data block");

        /* And the end-of-data block is then correctly a no-op. */
        Outcome o = runTail(w, w.length(), w.length());
        check(o.rows == 0 && o.released,
              "  leaving the end-of-data block nothing to do");
    }

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - no spurious trailing row, and real last rows are kept");
    return failures ? 1 : 0;
}
''' % {'utf8_fn': utf8_fn, 'tail_block': tail_block}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    cmd = ['clang++', '-std=c++14', '-Wall', '-Wno-unused-variable',
           '-I', os.path.join(CORE, 'OOXML', 'Base'),
           '-o', exe, cpp, os.path.join(CORE, 'OOXML', 'Base', 'unicode_util.cpp')]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
