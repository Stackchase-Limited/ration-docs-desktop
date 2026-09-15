#!/usr/bin/env python3
r"""
#1359, follow-up - a tautology in CSVReader's "sep=" handling.

CSVReader.cpp took the second half of a surrogate-pair delimiter like this:

    if (2 == sizeof(wchar_t) && 0xD800 <= wcDelimiterLeading
        && wcDelimiterLeading <= 0xDBFF
        && ( sFileDataW[5] != L'\r' || sFileDataW[5] != L'\n'))

`x != '\r' || x != '\n'` is true for every possible x - one character cannot be
both - so that clause said nothing.  It was meant to say "and [5] is not a line
break", i.e. `&&`.

What it costs: a file that opens "sep=" with a LONE high surrogate followed by
CR or LF.  The tautology makes the reader swallow that CR/LF as the delimiter's
trailing half (nDelimiterSize 2, wcDelimiterTrailing = CR/LF), and line 379 then
splits a cell wherever that same pair appears in the data, skipping
nDelimiterSize characters - so a real row break gets eaten and two rows merge.
With `&&`, nDelimiterSize stays 1 and the CR/LF is consumed as the line break
ending the "sep=" line, which is what it is.

The whole branch is Windows-only: it is behind `2 == sizeof(wchar_t)`, and
wchar_t is 4 bytes on macOS and Linux.  So this harness runs the REAL code twice -
once natively, where the branch is dead and nothing may change, and once built
with -fshort-wchar, which is the 2-byte wchar_t the branch is written for.

Nothing is re-typed.  The three WCHAR declarations and the whole
if/else-if chain that follows them are lifted out of CSVReader.cpp by brace
matching and compiled as-is; the only things supplied are the two strings they
read (as a small container, because libc++'s std::wstring misbehaves under
-fshort-wchar - its char_traits calls a libc that still thinks wchar_t is 4
bytes) and the WCHAR typedef the product also uses.

  BASELINE=1 re-reads CSVReader.cpp from BASE_REF and must FAIL - under
  -fshort-wchar, on exactly the inputs listed below.
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

CSVREADER = 'OOXML/Binary/Sheets/Reader/CSVReader.cpp'
ANCHOR = 'WCHAR wcDelimiterLeading'


def source(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, check=True)
        return r.stdout.decode('utf-8-sig')
    with open(os.path.join(CORE, rel), 'rb') as f:
        return f.read().decode('utf-8-sig')


def blank_noncode(text):
    """Same text with comments and literals blanked, for locating braces only."""
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


def match_braces(code, at):
    depth = 0
    for i in range(at, len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced braces')


src = source(CSVREADER)
code = blank_noncode(src)

start = code.find(ANCHOR)
if start < 0:
    raise SystemExit('%r not found in %s - the extractor needs updating' % (ANCHOR, CSVREADER))

# Consume the if / else-if chain that follows the three declarations.
end = code.index('{', start)
end = match_braces(code, end)
while True:
    k = end + 1
    while k < len(code) and code[k].isspace():
        k += 1
    if code.startswith('else', k):
        b = code.index('{', k)
        end = match_braces(code, b)
    else:
        break
block = src[start:end + 1]

for needed in ('sep=', 'wcDelimiterTrailing', 'sDelimiter', 'sFileDataW.erase'):
    if needed not in block:
        raise SystemExit('the extracted block does not look right (%r missing):\n%s'
                         % (needed, block))

harness = r'''
#include <stdio.h>
#include <string.h>
#include <vector>
#include <string>

/* The product's own spelling, from core/DesktopEditor/common/Types.h. */
typedef wchar_t WCHAR;

/* std::wstring is unusable under -fshort-wchar on macOS: libc++'s
 * char_traits<wchar_t> calls wcslen/wmemcmp from a libc that still steps in
 * 4-byte units.  This holds exactly the operations the extracted block performs
 * on sFileDataW and sDelimiter, and nothing else. */
struct WStr
{
    std::vector<WCHAR> v;
    WStr() {}
    WStr(const WCHAR *s) { for (; *s; ++s) v.push_back(*s); }
    size_t size() const { return v.size(); }
    size_t length() const { return v.size(); }
    WCHAR operator[](size_t i) const { return i < v.size() ? v[i] : (WCHAR)0; }
    WStr substr(size_t pos, size_t n) const
    { WStr r; for (size_t i = pos; i < pos + n && i < v.size(); ++i) r.v.push_back(v[i]); return r; }
    void erase(size_t pos, size_t n)
    { if (pos <= v.size()) v.erase(v.begin() + pos, v.begin() + (pos + n > v.size() ? v.size() : pos + n)); }
};

static bool operator==(const WStr &a, const WCHAR *b)
{
    size_t i = 0;
    for (; b[i]; ++i) { if (i >= a.size() || a.v[i] != b[i]) return false; }
    return i == a.size();
}

struct Outcome
{
    int   nDelimiterSize;
    unsigned lead;
    unsigned trail;
    size_t nSize;
    WStr  rest;
};

/* The real CSVReader.cpp delimiter block, lifted whole. */
static Outcome run(WStr sFileDataW, WStr sDelimiter)
{
    size_t nSize = sFileDataW.length();
%(block)s
    Outcome o;
    o.nDelimiterSize = nDelimiterSize;
    o.lead  = (unsigned)(unsigned short)wcDelimiterLeading;
    o.trail = (unsigned)(unsigned short)wcDelimiterTrailing;
    o.nSize = nSize;
    o.rest  = sFileDataW;
    return o;
}

static int failures = 0;

static void show(const char *label, const Outcome &o)
{
    printf("      %%-34s size=%%d lead=U+%%04X trail=U+%%04X rest=\"",
           label, o.nDelimiterSize, o.lead, o.trail);
    for (size_t i = 0; i < o.rest.size() && i < 10; ++i)
    {
        unsigned c = (unsigned)(unsigned short)o.rest[i];
        if (c == 13) printf("\\r"); else if (c == 10) printf("\\n");
        else if (c >= 32 && c < 127) printf("%%c", (char)c);
        else printf("\\u%%04X", c);
    }
    printf("\"\n");
}

static void check(bool ok, const char *what)
{
    printf("  %%-3s %%s\n", ok ? "ok" : "!!", what);
    if (!ok) failures++;
}

/* The two characters that matter, spelled without a literal so that the
 * 4-byte and 2-byte builds agree on them. */
static const WCHAR CR = (WCHAR)13, LF = (WCHAR)10;

static WStr make(const WCHAR *prefix, WCHAR a, WCHAR b, const WCHAR *tail)
{
    WStr s(prefix);
    if (a) s.v.push_back(a);
    if (b) s.v.push_back(b);
    for (const WCHAR *p = tail; *p; ++p) s.v.push_back(*p);
    return s;
}

int main()
{
    printf("sizeof(wchar_t) = %%zu - the \"2 == sizeof(wchar_t)\" branch is %%s\n\n",
           sizeof(wchar_t), (2 == sizeof(wchar_t)) ? "LIVE (this is Windows)"
                                                   : "dead (macOS / Linux)");

    WStr none;

    /* 1. an ordinary single-character delimiter */
    Outcome o = run(WStr(L"sep=;\r\na,b,c\n"), none);
    show("sep=; CRLF", o);
    check(o.nDelimiterSize == 1 && o.lead == ';' && o.trail == 0
          && o.rest == L"a,b,c\n", "sep=; is one character and the CRLF is the line break");

    /* 2. a well-formed surrogate pair as the delimiter */
    o = run(make(L"sep=", (WCHAR)0xD83D, (WCHAR)0xDE00, L"\r\na,b,c\n"), none);
    show("sep=<D83D DE00> CRLF", o);
    if (2 == sizeof(wchar_t))
        check(o.nDelimiterSize == 2 && o.lead == 0xD83D && o.trail == 0xDE00
              && o.rest == L"a,b,c\n", "a real surrogate pair is still taken as two units");
    else
        /* On a 4-byte build the pair is two independent units: the delimiter is
         * the first, and the second is left at the head of the data.  Odd, but
         * long-standing and untouched by this change. */
        check(o.nDelimiterSize == 1 && o.lead == 0xD83D && o.trail == 0
              && o.rest[0] == (WCHAR)0xDE00 && o.rest[1] == CR,
              "a 4-byte build takes one unit and leaves the low half, unchanged");

    /* 3. THE CASE THE TAUTOLOGY BROKE: a lone high surrogate, then CR LF */
    o = run(make(L"sep=", (WCHAR)0xD83D, 0, L"\r\na,b,c\n"), none);
    show("sep=<D83D> CRLF", o);
    check(o.nDelimiterSize == 1 && o.trail == 0 && o.rest == L"a,b,c\n",
          "a lone high surrogate does not swallow the CR as its second half");

    /* 4. the same with a bare LF */
    o = run(make(L"sep=", (WCHAR)0xD83D, 0, L"\na,b,c\n"), none);
    show("sep=<D83D> LF", o);
    check(o.nDelimiterSize == 1 && o.trail == 0 && o.rest == L"a,b,c\n",
          "nor the LF");

    /* 5. a low surrogate first is not a pair either way */
    o = run(make(L"sep=", (WCHAR)0xDE00, 0, L"\r\na,b,c\n"), none);
    show("sep=<DE00> CRLF", o);
    check(o.nDelimiterSize == 1 && o.trail == 0 && o.rest == L"a,b,c\n",
          "a low surrogate is one unit");

    /* 6. no sep= line: the explicit delimiter path must be untouched */
    o = run(WStr(L"a,b,c\n1,2,3\n"), WStr(L";"));
    show("no sep=, delimiter ;", o);
    check(o.nDelimiterSize == 1 && o.lead == ';' && o.trail == 0
          && o.rest == L"a,b,c\n1,2,3\n", "the explicit-delimiter path is unchanged");

    /* 7. and a two-unit explicit delimiter, which has its own length test */
    o = run(WStr(L"a,b,c\n"), make(L"", (WCHAR)0xD83D, (WCHAR)0xDE00, L""));
    show("no sep=, delimiter <D83D DE00>", o);
    if (2 == sizeof(wchar_t))
        check(o.nDelimiterSize == 2 && o.trail == 0xDE00,
              "an explicit surrogate-pair delimiter still takes both units");
    else
        check(o.nDelimiterSize == 1 && o.trail == 0,
              "a 4-byte build takes one unit, unchanged");

    /* 8. too short to be a sep= line at all */
    o = run(WStr(L"sep=;\n"), none);
    show("sep=; (7 chars, under the size gate)", o);
    check(o.nDelimiterSize == 0 && o.rest == L"sep=;\n",
          "a file at or under 7 characters is not treated as sep= at all");

    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

harness = harness % {'block': block}

results = {}
with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(harness)
    for label, extra in (('native wchar_t (macOS / Linux)', []),
                         ('-fshort-wchar (the Windows layout)', ['-fshort-wchar'])):
        exe = os.path.join(d, 'harness_%d' % len(results))
        cmd = ['clang++', '-std=c++11', '-O1', '-Wall', '-Wno-unused-function',
               '-Wno-unused-variable'] + extra + ['-o', exe, cpp]
        c = subprocess.run(cmd, capture_output=True, text=True)
        if c.returncode != 0:
            sys.stderr.write(c.stdout + c.stderr)
            raise SystemExit('harness did not compile (%s)' % label)
        print('=== %s ===' % label)
        sys.stdout.flush()
        results[label] = subprocess.run([exe]).returncode
        print()

bad = [k for k, v in results.items() if v]
if bad:
    for k in bad:
        print('FAILED under %s' % k)
    sys.exit(1)
print('ok - the surrogate test is no longer a tautology, and nothing else moved')
sys.exit(0)
