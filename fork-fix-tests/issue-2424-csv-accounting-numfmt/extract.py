#!/usr/bin/env python3
"""Extract the real numfmt_literal out of CSVWriter.cpp and wrap it in a harness.

Found while reproducing #2424 (Accounting-formatted cells). The CSV writer
builds its output by pasting the number format's literal run-in and run-out
around a boost::format directive, treating both as plain text. They are not:
`_c` reserves the width of c, `*c` repeats c to fill the column, `[Red]` /
`[<100]` / `[$-409]` are directives, and `\\c` is an escape. So the shipped x2t
writes an Accounting cell holding 8745 as

    _ * 8745.00_          (format `_ * #,##0.00_ ;...`)
    _ ¥* 8745.00_    (format `_ "¥"* #,##0.00_ ;...`)

instead of 8745.00 and ¥8745.00.

The harness shows the defect rather than asserting it: for every format code it
first prints the literal HEAD pasted in verbatim, then the cleaned one.

  BASELINE=1 re-reads CSVWriter.cpp from git HEAD, where numfmt_literal does
  not exist yet and the test must fail.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'OOXML/Binary/Sheets/Writer/CSVWriter.cpp'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()

SIG = 'static std::wstring numfmt_literal(const std::wstring & text)'
at = src.find(SIG)
if at == -1:
    sys.stderr.write(
        'numfmt_literal not found in %s - the CSV writer still pastes the number\n'
        "format's padding directives into the cell, so an Accounting cell is\n"
        'written as `_ * 8745.00_ ` instead of 8745.00\n' % REL)
    sys.exit(1)
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
fn = src[at:end + 1]

sys.stdout.write(r'''
#include <stdio.h>
#include <string>

%s

static int failures = 0;

/* What HEAD pasted into the output: the literal with its backslashes dropped
   and nothing else touched. Printed so the test shows the defect. */
static std::wstring as_head_did(const std::wstring &s)
{
    std::wstring r;
    for (size_t i = 0; i < s.length(); ++i)
        if (s[i] != L'\\') r += s[i];
    return r;
}

/* printf("%%ls") gives up on the first non-ASCII wide character under the C
   locale, so render everything as ASCII with \uXXXX for the rest. */
static std::string show(const std::wstring &s)
{
    std::string r;
    char buf[16];
    for (size_t i = 0; i < s.length(); ++i)
    {
        wchar_t c = s[i];
        if (c >= 0x20 && c < 0x7F) r += (char)c;
        else { snprintf(buf, sizeof(buf), "\\u%%04X", (unsigned)c); r += buf; }
    }
    return r;
}

static void expect(const wchar_t *literal, const wchar_t *want)
{
    std::wstring head = as_head_did(literal);
    std::wstring got  = numfmt_literal(literal);
    bool ok = (got == std::wstring(want));
    printf("  %%-14s HEAD wrote \"%%-12s\" now \"%%-10s\" (want \"%%s\") %%s\n",
           show(literal).c_str(), show(head).c_str(), show(got).c_str(),
           show(want).c_str(), ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main()
{
    printf("padding directives are not text and must not reach the cell:\n");
    expect(L"_ * ",        L"");        /* Accounting, no currency symbol */
    expect(L"_ ¥* ",  L"¥");  /* Accounting, CNY - keep the symbol */
    expect(L"_ ",          L"");
    expect(L"_ )",         L")");       /* only the reserved width goes */
    expect(L"* ",          L"");

    printf("\nbracketed directives are not text either:\n");
    expect(L"[Red]",       L"");
    expect(L"[$-409]",     L"");
    expect(L"[<100]$",     L"$");
    expect(L"[Red",        L"");        /* unterminated - swallow the rest */

    printf("\nescapes and ordinary literals must survive:\n");
    expect(L"\\-",         L"-");
    expect(L"\\_",         L"_");       /* an escaped underscore IS text */
    expect(L"\\*",         L"*");
    expect(L"$",           L"$");
    expect(L"€ ",     L"€ ");
    expect(L"(",           L"(");
    expect(L"",            L"");
    expect(L"\\",          L"");        /* dangling escape */
    expect(L"_",           L"");        /* dangling reserve */

    printf("\n%%s\n", failures
        ? "FAILED - a number format's padding directives still reach the CSV"
        : "ok - only real text is written, padding directives are dropped");
    return failures ? 1 : 0;
}
''' % fn)
