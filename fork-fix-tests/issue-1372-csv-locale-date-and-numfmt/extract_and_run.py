#!/usr/bin/env python3
r"""
#1372 - "Date formats in English: Onlyoffice does not respect OS locale settings".

The symptom the reporter describes - comment timestamps in a text document
showing US month/day order - is produced by the editor UI, which is not in
core.  What IS in core is the CSV writer's own locale date path, and the brief
was to check whether it carries the same class of defect.  It carries two, and
the second one loses data on export.

BOTH live in the machinery CSVWriter uses to honour the locale, so a fix for
one does not fix the other; they are tested separately.

1. THE TWO-DIGIT YEAR IS WRITTEN WITH FOUR DIGITS.

   convert_date_time builds the date from the locale's ShortDatePattern, whose
   digits mean 0=d 1=dd 2=m 3=mm 4=yy 5=yyyy.  The '4' arm did this:

       auto sringYear = std::to_wstring(currentTime->tm_year);
       auto lastTwoChars = sringYear.substr(sringYear.length() - 2);
       date_str += sringYear;               // <- appends the FULL year

   The two digits are computed and thrown away.  Every locale whose short date
   asks for a two-digit year got a four-digit one.

2. EVERY NUMBER FORMAT IS DISCARDED ON CSV EXPORT.

   To make a date come out in the locale's format, the writer deliberately
   clears the built-in format code so convert_date_time falls through to the
   locale branch.  The flag guarding that was:

       auto formatTypeIsDateTime = format_type && (*format_type == celltypeDate ||
           *format_type == celltypeDateTime ||  SimpleTypes::Spreadsheet::celltypeTime);

   The third test lost its `*format_type ==`.  celltypeTime is 10, a non-zero
   constant, so the parenthesis was always true and the flag meant nothing more
   than "this cell has a format type" - which numbers, percentages, currencies,
   fractions and scientific values all do.  Their format code was cleared too,
   and ConvertValueCellToString's default arm returns the raw value when the
   format code is empty.

   Confirmed end to end against our own shipped x2t, on a workbook that uses
   only built-in numFmtIds (so it has no <numFmts> element, which is the branch
   that clears the code).  Exporting it to CSV gave:

       0.5,1234.5,3/15/2023,0.1234

   where 0.5 has numFmtId 9 ("0%") and should be 50%, 1234.5 has numFmtId 4
   ("#,##0.00") and should be 1,234.50, and 0.1234 has numFmtId 10 ("0.00%")
   and should be 12.34%.  The date beside them, numFmtId 14, came out right -
   which is what pins the fault on the flag over-firing rather than on the
   locale path itself.

Both the date block and the flag expression are extracted from the real
CSVWriter.cpp; the locale table they are exercised against is parsed out of the
real LocalInfo.cpp, so the patterns under test are the shipped ones.

  BASELINE=1 re-reads CSVWriter.cpp from git HEAD, where it must FAIL.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'OOXML/Binary/Sheets/Writer/CSVWriter.cpp'
LOCALE_REL = 'OOXML/Binary/Sheets/Reader/CellFormatController/LocalInfo.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '39a34e13b3^')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(CORE, REL), encoding='utf-8').read()

# The locale table is data, not the thing under test: always read it as it ships.
locale_src = open(os.path.join(CORE, LOCALE_REL), encoding='utf-8').read()


def match_braces(text, open_brace):
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced braces')


# ---- 1. the real locale date-building block -------------------------------
# Anchor on the loop that walks the locale's ShortDatePattern - there is only
# one - then take the whole section from where it seeds the tm struct, so the
# harness cannot quietly seed it differently from production.
m = re.search(r'^\s*for\(auto part: locInf\.ShortDatePattern\)\s*$', src, re.M)
if not m:
    raise SystemExit('the ShortDatePattern loop was not found in %s - the '
                     'extractor needs updating' % REL)
loop_end = match_braces(src, src.index('{', m.end()))

seed = src.rfind('std::time_t now = std::time(nullptr);', 0, m.start())
if seed == -1:
    raise SystemExit('the tm seed before the ShortDatePattern loop was not '
                     'found - the extractor needs updating')
date_block = src[seed:loop_end + 1]

for needle in ("case L'4':", "case L'5':", 'locInf.DateSeparator',
               'currentTime->tm_year = date_.year()'):
    if needle not in date_block:
        raise SystemExit('extracted date block is missing %r - wrong block?' % needle)

# ---- 2. the real formatTypeIsDateTime expression --------------------------
m2 = re.search(r'auto formatTypeIsDateTime\s*=\s*(.*?);', src, re.S)
if not m2:
    raise SystemExit('formatTypeIsDateTime was not found in %s - the extractor '
                     'needs updating' % REL)
flag_expr = m2.group(1)
if 'format_type' not in flag_expr or 'celltypeTime' not in flag_expr:
    raise SystemExit('extracted flag expression looks wrong: %r' % flag_expr)

# It must be the only one; the value is used by two separate `format_code = L""`
# sites and both depend on it.
if len(re.findall(r'auto formatTypeIsDateTime\s*=', src)) != 1:
    raise SystemExit('expected exactly one formatTypeIsDateTime definition')
if len(re.findall(r'formatTypeIsDateTime\)', src)) != 2:
    raise SystemExit('expected formatTypeIsDateTime to guard exactly two sites '
                     '- the extractor needs updating')

# ---- the shipped locale table --------------------------------------------
rows = re.findall(r'\{\s*(-?\d+),\s*LocalInfo\{\s*-?\d+,\s*L"([^"]+)",\s*L"([^"]*)",'
                  r'\s*L"(\d+)",\s*(\d+),\s*(\d+)\}\}', locale_src)
if len(rows) < 100:
    raise SystemExit('parsed only %d locale rows - the parser needs updating'
                     % len(rows))
# lcid -> (name, separator, pattern); duplicates keep the first, as std::map does.
table = []
seen = set()
for lcid, name, sep, pat, _mi, _ab in rows:
    if lcid in seen:
        continue
    seen.add(lcid)
    table.append((name, sep, pat))

two_digit = [t for t in table if '4' in t[2]]
four_digit = [t for t in table if '5' in t[2]]
if not two_digit:
    raise SystemExit('no shipped locale uses a two-digit year - nothing to test')


def centry(name, sep, pat):
    return '    { "%s", L"%s", L"%s" },' % (name, sep, pat)


cases = '\n'.join(centry(*t) for t in two_digit + four_digit)

harness = r'''
#include <stdio.h>
#include <ctime>
#include <string>
#include <vector>

/* ---- the locale record, as LocalInfo.h declares the fields this code uses -- */
namespace lcInfo
{
    struct LocalInfo
    {
        std::wstring DateSeparator;
        std::wstring ShortDatePattern;
    };
    static LocalInfo g_info;
    LocalInfo getLocalInfo(int) { return g_info; }
}

/* ---- the date value, as boost::gregorian::date presents it ---------------
 * year() is the full year and month() and day() are 1-based, which is what the
 * extracted block assigns straight into the tm struct and then prints back out
 * without adjusting - so the harness must present them the same way. */
struct StubDate
{
    int y, m, d;
    int year()  const { return y; }
    int month() const { return m; }
    int day()   const { return d; }
};

static std::wstring buildDate(const StubDate &date_, const wchar_t *sep,
                              const wchar_t *pattern, int m_nLcid)
{
    lcInfo::g_info.DateSeparator   = sep;
    lcInfo::g_info.ShortDatePattern = pattern;

    std::wstring date_str;

/* ---- the real locale date block, lifted out of CSVWriter.cpp ---- */
%(date_block)s

    return date_str;
}

/* ---- the flag, evaluated exactly as written in CSVWriter.cpp ------------- */
namespace SimpleTypes { namespace Spreadsheet {
    enum ECellTypeType
    {
        celltypeBool = 0, celltypeDate = 1, celltypeError = 2,
        celltypeInlineStr = 3, celltypeNumber = 4, celltypeSharedString = 5,
        celltypeStr = 6, celltypePercentage = 7, celltypeScientific = 8,
        celltypeFraction = 9, celltypeTime = 10, celltypeCurrency = 11,
        celltypeDateTime = 12
    };
} }

/* Stands in for boost::optional<int>, which is all the expression needs. */
struct OptInt
{
    bool has; int v;
    explicit operator bool() const { return has; }
    int operator*() const { return v; }
};

static bool evalFlag(OptInt format_type)
{
    auto formatTypeIsDateTime = %(flag_expr)s;
    return (bool)formatTypeIsDateTime;
}

/* ------------------------------------------------------------------------ */
static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-72s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static std::string narrow(const std::wstring &w)
{
    std::string s;
    for (size_t i = 0; i < w.size(); ++i) s += (char)(w[i] < 128 ? w[i] : '?');
    return s;
}

struct LocaleCase { const char *name; const wchar_t *sep; const wchar_t *pattern; };

static const LocaleCase g_locales[] = {
%(cases)s
};

/* Count the run of digits that carries the year: the year is the only field
 * that can exceed two digits, so compare the longest numeric run. */
static size_t longestDigitRun(const std::wstring &s)
{
    size_t best = 0, run = 0;
    for (size_t i = 0; i < s.size(); ++i)
    {
        if (s[i] >= L'0' && s[i] <= L'9') { run++; if (run > best) best = run; }
        else run = 0;
    }
    return best;
}

int main()
{
    const StubDate d = { 2023, 3, 15 };   /* 15 March 2023 */

    /* ---- 1. the year width the locale actually asked for ---------------- */
    printf("the locale short-date pattern decides the year width "
           "(0=d 1=dd 2=m 3=mm 4=yy 5=yyyy):\n");

    /* Two worked examples first, so the expected strings are visible. */
    {
        std::wstring us = buildDate(d, L"/", L"205", 1033);
        printf("     en-US  pattern 205 -> \"%%s\"\n", narrow(us).c_str());
        check(us == L"3/15/2023", "a four-digit-year locale is unchanged (en-US)");

        std::wstring ar = buildDate(d, L"/", L"134", 1025);
        printf("     ar-SA  pattern 134 -> \"%%s\"\n", narrow(ar).c_str());
        check(ar == L"15/03/23", "a two-digit-year locale gets two digits (ar-SA)");
    }

    /* Then every shipped locale, so this cannot pass by picking a lucky one. */
    {
        int nTwo = 0, nFour = 0;
        bool twoOk = true, fourOk = true;
        std::string firstBad;
        const size_t n = sizeof(g_locales) / sizeof(g_locales[0]);
        for (size_t i = 0; i < n; ++i)
        {
            std::wstring pat(g_locales[i].pattern);
            std::wstring out = buildDate(d, g_locales[i].sep,
                                         g_locales[i].pattern, 0);
            size_t run = longestDigitRun(out);
            if (pat.find(L'4') != std::wstring::npos)
            {
                nTwo++;
                if (run != 2)
                {
                    if (twoOk) firstBad = std::string(g_locales[i].name) + " -> " + narrow(out);
                    twoOk = false;
                }
            }
            else
            {
                nFour++;
                if (run != 4)
                {
                    if (fourOk) firstBad = std::string(g_locales[i].name) + " -> " + narrow(out);
                    fourOk = false;
                }
            }
        }
        char buf[220];
        snprintf(buf, sizeof buf,
                 "all %%d shipped locales asking for yy get two digits%%s%%s",
                 nTwo, twoOk ? "" : " (first bad: ", twoOk ? "" : firstBad.c_str());
        check(twoOk, buf);
        snprintf(buf, sizeof buf,
                 "all %%d shipped locales asking for yyyy still get four", nFour);
        check(fourOk, buf);
    }

    /* ---- 2. the flag that clears the format code ------------------------ */
    printf("\nonly a date/time format may have its format code cleared:\n");
    {
        struct { int type; const char *name; bool want; } t[] = {
            { SimpleTypes::Spreadsheet::celltypeDate,       "Date",       true  },
            { SimpleTypes::Spreadsheet::celltypeDateTime,   "DateTime",   true  },
            { SimpleTypes::Spreadsheet::celltypeTime,       "Time",       true  },
            { SimpleTypes::Spreadsheet::celltypeNumber,     "Number",     false },
            { SimpleTypes::Spreadsheet::celltypePercentage, "Percentage", false },
            { SimpleTypes::Spreadsheet::celltypeCurrency,   "Currency",   false },
            { SimpleTypes::Spreadsheet::celltypeFraction,   "Fraction",   false },
            { SimpleTypes::Spreadsheet::celltypeScientific, "Scientific", false },
            { SimpleTypes::Spreadsheet::celltypeStr,        "Str",        false },
        };
        for (size_t i = 0; i < sizeof(t) / sizeof(t[0]); ++i)
        {
            OptInt ft; ft.has = true; ft.v = t[i].type;
            bool got = evalFlag(ft);
            char buf[160];
            snprintf(buf, sizeof buf, "%%-10s -> %%-5s (want %%s)",
                     t[i].name, got ? "true" : "false",
                     t[i].want ? "true" : "false");
            check(got == t[i].want, buf);
        }
        OptInt none; none.has = false; none.v = 0;
        check(evalFlag(none) == false, "a cell with no format type at all -> false");
    }

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - locale year width honoured, and only dates lose their format code");
    return failures ? 1 : 0;
}
''' % {'date_block': date_block, 'flag_expr': flag_expr, 'cases': cases}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    cmd = ['clang++', '-std=c++14', '-Wall', '-Wno-unused-variable',
           '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
