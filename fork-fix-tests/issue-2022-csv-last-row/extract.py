#!/usr/bin/env python3
"""Extract the real CSVWriter::Impl::WriteRowEnd and wrap it in a harness.

#2022 - saving a spreadsheet as CSV drops the trailing delimiters of the LAST
row.  Every other short row is padded out to the width of the used range, so a
reader that counts fields per line loses the final row's last columns.

CSheetData::fromXLSB calls fromXLSBToXmlRowEnd(..., true) on rt_EndSheetData
(core/OOXML/XlsxFormat/Worksheets/SheetData.cpp:5002), which reaches
WriteRowEnd with bLast = true, and the `&& !bLast` in its padding loop skips
the delimiters.

The function is taken verbatim out of CSVWriter.cpp by brace matching; only the
`CSVWriter::Impl::` qualifier is rewritten, so the body under test is the real
one.  BASELINE=1 reads the file back from git HEAD, where it must fail.
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'OOXML/Binary/Sheets/Writer/CSVWriter.cpp'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()

SIG = 'void CSVWriter::Impl::WriteRowEnd(OOX::Spreadsheet::CRow* pWorksheet, bool bLast)'
at = src.find(SIG)
if at == -1:
    sys.stderr.write('CSVWriter::Impl::WriteRowEnd not found in %s\n' % REL)
    sys.exit(2)
ob = src.index('{', at + len(SIG) - 1)
depth = 0
for i in range(ob, len(src)):
    if src[i] == '{':
        depth += 1
    elif src[i] == '}':
        depth -= 1
        if depth == 0:
            end = i
            break
fn = src[at:end + 1].replace('CSVWriter::Impl::', 'Impl::', 1)

sys.stdout.write(r'''
#include <stdio.h>
#include <string>
#include <vector>

/* --- stubs: just enough of CSVWriter.cpp's surroundings to compile the real
   WriteRowEnd and watch what it emits. --------------------------------- */
namespace OOX { namespace Spreadsheet { struct CRow {}; } }

static std::wstring g_sEndJson = L"]";
struct FileStub {};
static std::wstring g_out;   /* everything WriteRowEnd wrote */

static void WriteFile(FileStub *, wchar_t **, int &, const std::wstring &s,
                      unsigned int &, bool = false) { g_out += s; }

struct Impl {
    bool          m_bJSON;
    FileStub      m_oFile;
    wchar_t      *m_pWriteBuffer;
    int           m_nCurrentIndex;
    unsigned int  m_nCodePage;
    int           m_nColDimension;
    int           m_nColCurrent;
    std::wstring  m_sDelimiter;
    bool          m_bIsWriteCell;
    void WriteRowEnd(OOX::Spreadsheet::CRow *pWorksheet, bool bLast);
};

%s

/* --------------------------------------------------------------------- */
static int failures = 0;

/* One row: `used` columns in the sheet's used range, `written` cells actually
   present in this row. Returns what the row's tail looks like in the CSV. */
static std::wstring tail(int used, int written, bool bLast)
{
    Impl im;
    im.m_bJSON = false;
    im.m_pWriteBuffer = 0;
    im.m_nCurrentIndex = 0;
    im.m_nCodePage = 46;
    im.m_nColDimension = used;
    im.m_nColCurrent = written;
    im.m_sDelimiter = L",";
    im.m_bIsWriteCell = true;
    g_out.clear();
    OOX::Spreadsheet::CRow row;
    im.WriteRowEnd(&row, bLast);
    return g_out;
}

static void expect(const char *what, int used, int written, bool bLast,
                   const wchar_t *want)
{
    std::wstring got = tail(used, written, bLast);
    bool ok = (got == std::wstring(want));
    printf("  %%-46s used=%%d written=%%d last=%%-3s -> \"%%ls\" (want \"%%ls\") %%s\n",
           what, used, written, bLast ? "yes" : "no",
           got.c_str(), want, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main()
{
    printf("a short row in a 5-column sheet must be padded to 5 fields:\n");
    /* the reporter's case: the last row stops 2 columns early */
    expect("last row, 2 columns missing",  5, 3, true,  L",,");
    expect("last row, 1 column missing",   5, 4, true,  L",");
    expect("last row, 4 columns missing",  5, 1, true,  L",,,,");
    printf("\nrows that were already right must not change:\n");
    expect("interior row, 2 missing",      5, 3, false, L",,");
    expect("last row, already full",       5, 5, true,  L"");
    expect("interior row, already full",   5, 5, false, L"");
    expect("single-column sheet, last",    1, 1, true,  L"");
    expect("row wider than seen so far",   3, 4, true,  L"");

    printf("\n%%s\n", failures
        ? "FAILED - the final row of a CSV still loses its trailing delimiters (#2022)"
        : "ok - every row is padded to the width of the used range");
    return failures ? 1 : 0;
}
''' % fn)
