#!/usr/bin/env python3
r"""
#1359, follow-up - the same encodings-table subscript, five more times, in TxtFile.

NSUnicodeConverter::Encodings has 54 entries.  af68137e07 guarded the three CSV
call sites that subscript it with the caller's <m_nCsvTxtEncoding>; five more
live in core/TxtFile.  They are not all the same, and this harness treats them
differently because they are not:

  File.cpp:89  transformToUnicode
  File.cpp:112 transformFromUnicode
  File.cpp:146 File::read(filename, code_page)

      genuinely unguarded - `NSUnicodeConverter::Encodings[code_page]` with no
      range check anywhere in front of it, exactly as CSVReader.cpp was.  Part 1
      below extracts the real subscript expression from each by bracket matching
      and checks it cannot leave the table.

  TxtFile.cpp:99  readUtf8Lines
  TxtFile.cpp:197 readUnicodeLines

      NOT out of bounds, contrary to the note left under af68137e07: each already
      stood inside `if (n >= 0 && n < UNICODE_CONVERTER_ENCODINGS_COUNT)`.  What
      they did instead was send every value outside 0..53 - which is where all
      the Windows code pages the editor API documents live - to a fallback that
      ignored the requested encoding.  readUtf8Lines fell back to
      toUnicode(..., 65001) and readUnicodeLines to toUnicode(..., 46), and 46 is
      this table's row number for UTF-8, not a code page, so that second fallback
      asked ICU for an encoding that does not exist.  Part 2 below extracts the
      whole real encoding-selection block from each and runs it against a stub
      converter to see which encoding it actually picks.

Nothing is re-typed: part 1 takes the text between the brackets of each real
`NSUnicodeConverter::Encodings[...]`, part 2 takes the whole enclosing `else`
block, and both compile against the real UnicodeConverter_Encodings.h.

  BASELINE=1 re-reads all of it from BASE_REF and must FAIL.

e2e.py beside this file drives the real x2t through the txt->docx path, which
reaches TxtFile.cpp:99 for real.  The three File.cpp sites have no caller inside
core at all - see the note at the end of e2e.py.
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
BASE_REF = os.environ.get('BASE_REF', 'af68137e075d3169e24d93590f3844290a9605ef')
BASELINE = bool(os.environ.get('BASELINE'))

HEADER = 'UnicodeConverter/UnicodeConverter_Encodings.h'
FILE_CPP = 'TxtFile/Source/TxtFormat/File.cpp'
TXTFILE_CPP = 'TxtFile/Source/TxtFormat/TxtFile.cpp'


def source(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, check=True)
        return r.stdout.decode('utf-8-sig')
    with open(os.path.join(CORE, rel), 'rb') as f:
        return f.read().decode('utf-8-sig')


def blank_noncode(text):
    """Same text with comments and literals blanked, for locating brackets only."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            while i < n and text[i] != '\n':
                out[i] = ' '
                i += 1
        elif c == '/' and i + 1 < n and text[i + 1] == '*':
            out[i] = out[i + 1] = ' '
            i += 2
            while i < n and not (text[i] == '*' and i + 1 < n and text[i + 1] == '/'):
                if text[i] != '\n':
                    out[i] = ' '
                i += 1
            if i < n:
                out[i] = out[i + 1] = ' '
                i += 2
        elif c in '"\'':
            q = c
            i += 1
            while i < n and text[i] != q:
                if text[i] == '\\':
                    out[i] = ' '
                    i += 1
                if i < n and text[i] != '\n':
                    out[i] = ' '
                i += 1
            if i < n:
                out[i] = ' '
                i += 1
        else:
            i += 1
    return ''.join(out)


def match(code, at, opener, closer):
    depth = 0
    for i in range(at, len(code)):
        if code[i] == opener:
            depth += 1
        elif code[i] == closer:
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced %s%s' % (opener, closer))


def subscripts(rel):
    """(position, expression-text) for every NSUnicodeConverter::Encodings[...]."""
    src = source(rel)
    code = blank_noncode(src)
    out = []
    for m in re.finditer(r'NSUnicodeConverter::Encodings\s*\[', code):
        ob = code.index('[', m.end() - 1)
        cb = match(code, ob, '[', ']')
        out.append((ob, ' '.join(src[ob + 1:cb].split())))
    return src, code, out


def enclosing_else_block(code, src, pos):
    """The smallest block containing pos whose `{` is preceded by the word `else`.

    Before the fix each TxtFile subscript sat in the `if` half of an inner
    `if (in range) {...} else {...}`; after it there is no inner if at all.
    Anchoring on the `else` of the isUtf8/isUtf16LE/isUtf16BE chain - the block
    that decides the encoding either way - picks out the same region in both.
    """
    at = pos
    for _ in range(8):
        depth = 0
        start = None
        for i in range(at - 1, -1, -1):
            if code[i] == '}':
                depth += 1
            elif code[i] == '{':
                if depth == 0:
                    start = i
                    break
                depth -= 1
        if start is None:
            raise SystemExit('no enclosing block found')
        j = start - 1
        while j >= 0 and code[j].isspace():
            j -= 1
        if code[max(0, j - 3):j + 1] == 'else':
            return src[start:match(code, start, '{', '}') + 1]
        at = start
    raise SystemExit('no enclosing else block found - the extractor needs updating')


# --------------------------------------------------------------------- part 1
src, code, file_hits = subscripts(FILE_CPP)
if len(file_hits) != 3:
    raise SystemExit('expected 3 Encodings[] subscripts in %s, found %d - '
                     'the extractor needs updating' % (FILE_CPP, len(file_hits)))
file_exprs = [e for _, e in file_hits]

# --------------------------------------------------------------------- part 2
src2, code2, txt_hits = subscripts(TXTFILE_CPP)
if len(txt_hits) != 2:
    raise SystemExit('expected 2 Encodings[] subscripts in %s, found %d - '
                     'the extractor needs updating' % (TXTFILE_CPP, len(txt_hits)))
blocks = [enclosing_else_block(code2, src2, pos) for pos, _ in txt_hits]
for i, b in enumerate(blocks):
    if 'conv.toUnicode' not in b or 'read_size' not in b:
        raise SystemExit('block %d does not look like the encoding selection:\n%s' % (i, b))

header_src = source(HEADER)

harness = r'''
#include <stdio.h>
#include <string.h>
#include <memory>
#include <string>

typedef unsigned int _UINT32;

#include "UnicodeConverter_Encodings.h"

/* ---- what the block under test ended up asking for --------------------- */
static std::string g_name;
static long long   g_codePage;
static void reset() { g_name = "(nothing)"; g_codePage = -777; }

namespace NSUnicodeConverter
{
    /* Stub with the real signatures, so the real call in the real block picks
     * the same overload it picks in the product. */
    struct CUnicodeConverter
    {
        std::wstring toUnicode(const char*, const unsigned int&, const char* name,
                               bool = false)
        { g_name = name ? name : "(null)"; return std::wstring(L"x"); }
        std::wstring toUnicode(const char*, const unsigned int&, int cp, bool = false)
        { g_codePage = cp; g_name = "(asked ICU for code page)"; return std::wstring(L"x"); }
        std::string fromUnicode(const std::wstring&, const char*)
        { return std::string("x"); }
    };
}

/* ---- the real TxtFile.cpp encoding-selection blocks, lifted whole ------- */
static std::string site_readUtf8Lines(int IdxEncoding)
{
    reset();
    NSUnicodeConverter::CUnicodeConverter conv;
    std::unique_ptr<char[]> file_data(new char[16]);
    unsigned int read_size = 16;
    std::string utf8_content;
%(blockA)s
    (void)utf8_content;
    return g_name;
}

static std::string site_readUnicodeLines(int CodePage)
{
    reset();
    char* file_data = new char[16];
    unsigned int read_size = 16;
    std::wstring content;
%(blockB)s
    delete[] file_data;
    (void)content;
    return g_name;
}

/* ---- the real File.cpp index expressions, lifted whole ----------------- */
%(fns)s

static const char *kFileExpr[] = { %(exprlits)s };
static long long (*kFileFn[])(int) = { %(fnnames)s };
static const char *kFileSite[] = { %(sitelits)s };

static int failures = 0;

static void check(bool ok, const char *what, const char *detail)
{
    printf("    %%-3s %%-44s %%s\n", ok ? "ok" : "!!", what, detail);
    if (!ok) failures++;
}

/* The numbers x2t is handed for <m_nCsvTxtEncoding>, and the row each must
 * resolve to.  -1 means "anything in range will do". */
static const struct { int n; int want; const char *what; } kCases[] = {
    {     0,  0, "0     -> ISO-8859-6   (a real row)" },
    {    44, 44, "44    -> windows-1252 (a real row)" },
    {    46, 46, "46    -> UTF-8        (a real row)" },
    {    53, 53, "53    -> GB18030      (the last row)" },
    {  1252, 44, "1252  -> windows-1252 (a Windows code page)" },
    {  1251, 14, "1251  -> windows-1251" },
    { 65001, 46, "65001 -> UTF-8        (the documented UTF-8 value)" },
    {  1200, 48, "1200  -> UTF-16LE     (the asc_CTextOptions example)" },
    {   932, 27, "932   -> Shift_JIS" },
    {    54, -1, "54    (one past the end) stays in range" },
    {   999, -1, "999   stays in range" }
};

int main()
{
    const int count = UNICODE_CONVERTER_ENCODINGS_COUNT;
    printf("Encodings table has %%d entries (valid subscripts 0..%%d)\n", count, count - 1);

    printf("\nPart 1 - File.cpp, where the subscript has no range check at all\n");
    for (size_t s = 0; s < sizeof(kFileFn)/sizeof(kFileFn[0]); ++s)
    {
        printf("  %%s   subscript: %%s\n", kFileSite[s], kFileExpr[s]);
        for (size_t i = 0; i < sizeof(kCases)/sizeof(kCases[0]); ++i)
        {
            long long got = kFileFn[s](kCases[i].n);
            bool inRange = (got >= 0 && got < count);
            char detail[200];
            bool ok = inRange;
            if (!inRange)
                snprintf(detail, sizeof(detail), "[subscript %%lld is OUTSIDE the table]", got);
            else
            {
                if (kCases[i].want >= 0) ok = (got == kCases[i].want);
                snprintf(detail, sizeof(detail), "[%%lld -> \"%%s\"]", got,
                         NSUnicodeConverter::Encodings[got].Name);
            }
            check(ok, kCases[i].what, detail);
        }
    }

    printf("\nPart 2 - TxtFile.cpp, where the subscript was in range but the\n");
    printf("         out-of-range fallback ignored the encoding that was asked for\n");
    struct { const char *label; std::string (*fn)(int); } sites[] = {
        { "TxtFile.cpp readUtf8Lines  ", site_readUtf8Lines },
        { "TxtFile.cpp readUnicodeLines", site_readUnicodeLines }
    };
    for (size_t s = 0; s < sizeof(sites)/sizeof(sites[0]); ++s)
    {
        printf("  %%s\n", sites[s].label);
        for (size_t i = 0; i < sizeof(kCases)/sizeof(kCases[0]); ++i)
        {
            std::string got = sites[s].fn(kCases[i].n);
            const char *want = (kCases[i].want >= 0)
                ? NSUnicodeConverter::Encodings[kCases[i].want].Name
                : NSUnicodeConverter::Encodings[NSUnicodeConverter::UNICODE_CONVERTER_ENCODING_UTF8].Name;
            bool ok = (got == want);
            char detail[200];
            snprintf(detail, sizeof(detail), "[decoded as \"%%s\"%%s]", got.c_str(),
                     ok ? "" : (std::string(", wanted \"") + want + "\"").c_str());
            check(ok, kCases[i].what, detail);
        }
    }

    printf("\n%%s\n", failures
           ? "FAILED - a number the editor can send still leaves the table or picks the wrong encoding"
           : "ok - all five TxtFile sites stay in the table and honour the encoding asked for");
    return failures ? 1 : 0;
}
'''

fns, fnnames, exprlits, sitelits = [], [], [], []
for i, expr in enumerate(file_exprs):
    fns.append('static long long file_site%d(int code_page)\n{\n    return (long long)( %s );\n}'
               % (i, expr))
    fnnames.append('file_site%d' % i)
    exprlits.append('"%s"' % expr.replace('\\', '\\\\').replace('"', '\\"'))
    sitelits.append('"File.cpp #%d"' % (i + 1))

harness = harness % {
    'blockA': blocks[0],
    'blockB': blocks[1],
    'fns': '\n'.join(fns),
    'fnnames': ', '.join(fnnames),
    'exprlits': ', '.join(exprlits),
    'sitelits': ', '.join(sitelits),
}

with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, 'UnicodeConverter_Encodings.h'), 'w', encoding='utf-8') as f:
        f.write(header_src)
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(harness)
    cmd = ['clang++', '-std=c++11', '-O1', '-Wall', '-Wno-unused-variable',
           '-Wno-unused-const-variable', '-Wno-unused-function', '-I', d, '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        # Before the fix UNICODE_CONVERTER_ENCODING_UTF8 may not exist yet; that is
        # a real difference, not a broken test, so say which it is.
        sys.stderr.write(c.stdout + c.stderr)
        if BASELINE:
            print('\nFAILED - %s at %s does not even define the guard '
                  '(no GetEncodingIndex / UNICODE_CONVERTER_ENCODING_UTF8)'
                  % (HEADER, BASE_REF[:10]))
            raise SystemExit(1)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
