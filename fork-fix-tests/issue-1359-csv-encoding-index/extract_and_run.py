#!/usr/bin/env python3
r"""
#1359 - "'Something has gone wrong...' when opening a CSV file".

The CSV reader and writer subscript NSUnicodeConverter::Encodings - a 54-entry
table - with the code page the caller asked for:

    const NSUnicodeConverter::EncodindId& oEncodindId
        = NSUnicodeConverter::Encodings[nCodePage];
    ...
    oUnicodeConverter.toUnicode(..., oEncodindId.Name);

nCodePage is x2t's <m_nCsvTxtEncoding>.  The table wants its own Index column
(UTF-16LE is 48), but the editor API that fills that element in documents a
*Windows code page* - sdkjs/cell/api.js:1273 spells the example out as
"new Asc.asc_CTextOptions(1200, c_oAscCsvDelimiter.Comma)" - so values far
outside 0..53 reach the subscript.  Reading past the table produces an
EncodindId out of whatever bytes follow it and hands its Name to ICU.

Measured on the shipped x2t (desktop-apps/build/.../converter/x2t):

    m_nCsvTxtEncoding=65001  ->  SIGSEGV (exit 139), no output file at all
    m_nCsvTxtEncoding=65000  ->  SIGSEGV (exit 139), no output file at all
    m_nCsvTxtEncoding=1252   ->  exit 0, and an xlsx with ZERO cells
    1200 / 1201 / 1251 / 936 / 12000 / 28591 / 54 / 999  ->  same empty sheet

so the user either gets the generic failure dialog or a blank spreadsheet
where their file used to be.

This test does not re-type the guard.  It pulls the REAL
UnicodeConverter_Encodings.h into the harness and compiles it, and it pulls the
REAL index expressions out of CSVReader.cpp and CSVWriter.cpp by matching the
brackets of each `NSUnicodeConverter::Encodings[...]`.  Whatever those three
call sites actually compute is what gets range-checked here.

  BASELINE=1 re-reads all three files from BASE_REF, where the expression is a
  bare `nCodePage` and every out-of-range value must FAIL.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))

# Pinned, NOT HEAD: left on HEAD this stops differing the moment the fix is
# committed and then reports success forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', 'fd679c60c1976d00feadf7670a3edb48609c3e5e')

HEADER = 'UnicodeConverter/UnicodeConverter_Encodings.h'
SITES = [
    ('OOXML/Binary/Sheets/Reader/CSVReader.cpp', 2),   # open path: both subscripts
    ('OOXML/Binary/Sheets/Writer/CSVWriter.cpp', 1),   # save path
]
BASELINE = bool(os.environ.get('BASELINE'))


def source(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, check=True)
        return r.stdout.decode('utf-8-sig')
    with open(os.path.join(CORE, rel), 'rb') as f:
        return f.read().decode('utf-8-sig')


def match_brackets(text, open_at):
    """Index of the ']' closing the '[' at open_at."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced brackets')


# ---- the real index expressions, straight out of the real call sites --------
exprs = []          # (label, expression text)
for rel, expected in SITES:
    src = source(rel)
    found = []
    for m in re.finditer(r'NSUnicodeConverter::Encodings\s*\[', src):
        ob = src.index('[', m.end() - 1)
        expr = src[ob + 1:match_brackets(src, ob)].strip()
        # collapse the line breaks a wrapped call site may contain
        found.append(' '.join(expr.split()))
    if len(found) != expected:
        raise SystemExit('expected %d Encodings[] subscripts in %s, found %d - '
                         'the extractor needs updating' % (expected, rel, len(found)))
    for i, e in enumerate(found):
        exprs.append(('%s #%d' % (os.path.basename(rel), i + 1), e))

if not exprs:
    raise SystemExit('no call sites extracted')

# ---- the real table and, once fixed, the real guard ------------------------
header_src = source(HEADER)
if 'UNICODE_CONVERTER_ENCODINGS_COUNT' not in header_src:
    raise SystemExit('the encodings table was not found in %s' % HEADER)

cases = r'''
/* The values x2t is actually handed for <m_nCsvTxtEncoding>, and what a correct
 * reader must resolve them to.  -1 means "any in-range index will do"; the point
 * for those is only that the subscript stays inside the table. */
static const struct { long long cp; int want; const char *what; } kCases[] = {
    /* the Windows code pages the editor API documents callers to send */
    { 65001, 46, "65001 -> UTF-8        (crashed x2t before)" },
    { 65000, 47, "65000 -> UTF-7        (crashed x2t before)" },
    {  1200, 48, "1200  -> UTF-16LE     (the asc_CTextOptions example)" },
    {  1201, 49, "1201  -> UTF-16BE" },
    { 12000, 50, "12000 -> UTF-32LE" },
    {  1252, 44, "1252  -> windows-1252 (emptied the sheet before)" },
    {  1251, 14, "1251  -> windows-1251" },
    { 28591, 37, "28591 -> ISO-8859-1" },
    {   936, 18, "936   -> GBK" },
    {   932, 27, "932   -> Shift_JIS" },
    /* real table indices must be left exactly alone */
    {     0,  0, "index 0 passes through" },
    {    46, 46, "index 46 passes through" },
    {    48, 48, "index 48 passes through" },
    {    53, 53, "index 53 passes through" },
    /* junk: no correct answer, but it must not leave the table */
    {    54, -1, "index 54 (one past the end) stays in range" },
    {   999, -1, "999 stays in range" },
    {  1000, -1, "1000 (the reader's \"ansi\" sentinel) stays in range" },
    { 4294967295LL, -1, "(_UINT32)-1 stays in range" }
};
'''

harness = r'''
#include <stdio.h>
#include <string.h>

typedef unsigned int _UINT32;

#include "UnicodeConverter_Encodings.h"

%(cases)s

static int failures = 0;

static void check(bool ok, const char *site, const char *what)
{
    printf("  %%-26s %%-52s %%s\n", site, what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

/* One function per REAL call site, its body the expression extracted from that
 * site.  Nothing here was typed by hand. */
%(fns)s

struct Site { const char *label; long long (*idx)(_UINT32); };
static const Site kSites[] = { %(sites)s };

int main()
{
    const int count = UNICODE_CONVERTER_ENCODINGS_COUNT;
    printf("Encodings table has %%d entries (valid subscripts 0..%%d)\n\n", count, count - 1);

    for (size_t s = 0; s < sizeof(kSites)/sizeof(kSites[0]); ++s)
    {
        printf("%%s  -  expression: %%s\n", kSites[s].label, kExpr[s]);
        for (size_t i = 0; i < sizeof(kCases)/sizeof(kCases[0]); ++i)
        {
            long long got = kSites[s].idx((_UINT32)kCases[i].cp);
            bool inRange = (got >= 0 && got < count);
            bool ok = inRange;
            char what[160];
            if (!inRange)
                snprintf(what, sizeof(what), "%%s   [subscript %%lld is OUTSIDE the table]",
                         kCases[i].what, got);
            else if (kCases[i].want >= 0)
            {
                ok = (got == kCases[i].want);
                snprintf(what, sizeof(what), "%%s   [got %%lld -> \"%%s\"]", kCases[i].what,
                         got, NSUnicodeConverter::Encodings[got].Name);
            }
            else
                snprintf(what, sizeof(what), "%%s   [got %%lld -> \"%%s\"]", kCases[i].what,
                         got, NSUnicodeConverter::Encodings[got].Name);
            check(ok, kSites[s].label, what);
        }
        printf("\n");
    }

    printf("%%s\n", failures
           ? "FAILED - a code page the editor can send subscripts past the encodings table"
           : "ok - every call site keeps its subscript inside the encodings table");
    return failures ? 1 : 0;
}
'''

fns = []
site_inits = []
expr_literals = []
for i, (label, expr) in enumerate(exprs):
    fns.append('static long long site%d(_UINT32 nCodePage)\n{\n    return (long long)( %s );\n}'
               % (i, expr))
    site_inits.append('{ "%s", site%d }' % (label, i))
    expr_literals.append('"%s"' % expr.replace('\\', '\\\\').replace('"', '\\"'))

harness = harness % {
    'cases': cases,
    'fns': '\n'.join(fns) + '\nstatic const char *kExpr[] = { %s };' % ', '.join(expr_literals),
    'sites': ', '.join(site_inits),
}

with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, 'UnicodeConverter_Encodings.h'), 'w', encoding='utf-8') as f:
        f.write(header_src)
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(harness)
    cmd = ['clang++', '-std=c++14', '-O1', '-Wall', '-Wno-unused-variable',
           '-Wno-unused-const-variable', '-I', d, '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
