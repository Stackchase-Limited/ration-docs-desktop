#!/usr/bin/env python3
r"""
#2546 - "garbled characters when open .csv".

The reported file (an HWiNFO sensor log) starts with a UTF-8 BOM and its header
row is valid UTF-8 Chinese ("提交虚拟内存 [MB]" ...), but the data rows carry two
values written in the ANSI code page (GBK "是"/"否" = CA C7 / B7 F1).  sdkjs
sees the BOM and asks for UTF-8 (46), which is the right call for this file.

CSVReader::Impl::utf8_2_unicode (core/OOXML/Binary/Sheets/Reader/CSVReader.cpp)
decodes the whole buffer strictly; on the FIRST malformed sequence anywhere in
the file it used to throw the decode away and do

    std::string inp((char*)data, data_size);
    wStr = std::wstring(inp.begin(), inp.end());

i.e. widen every byte through a SIGNED char.  So every non-ASCII byte in the
file - the valid UTF-8 header included - became 0xFFxx (Windows, 16-bit
wchar_t: halfwidth/fullwidth junk, which is what the reporter's video shows) or
0xFFFFFFxx (mac/Linux: not a code point at all, written out as blanks).
Measured with the shipped 9.4 x2t on the reporter's file, enc=46: header cell
C1 comes out as "                   [MB]" - 18 bytes of Chinese turned into blanks.

The fix decodes piecewise: valid UTF-8 sequences as UTF-8, and only bytes that
are not part of one widened - unsigned, i.e. Latin-1, which is what the old
fallback meant to do for a legacy-codepage file opened as UTF-8.

This test extracts the REAL utf8_2_unicode (and, when present, the helper it now
calls) from CSVReader.cpp by brace matching, compiles it against the REAL
OOXML/Base/unicode_util.cpp, and feeds it byte strings shaped like the report.

Claimed: valid UTF-8 survives a file that also contains invalid bytes; the
invalid bytes become their Latin-1 characters (not sign-extended junk); the
separators around them are untouched; a fully valid file is unchanged.
NOT claimed: that GBK "是/否" are shown as Chinese - the file says UTF-8 and
they are not UTF-8; Excel and LibreOffice also show them as replacement junk.
The 16-bit wchar_t (Windows) branch is not exercised here (macOS wchar_t is 32
bits); the surrogate-pair code in the helper is only read, not run.

  RD_REPO   core checkout to test (default ../../core)
  BASELINE=1  read sources via `git show $BASE_REF:<path>`; must FAIL there.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '47c38a34cd^')
BASELINE = bool(os.environ.get('BASELINE'))

READER = 'OOXML/Binary/Sheets/Reader/CSVReader.cpp'
UTIL_CPP = 'OOXML/Base/unicode_util.cpp'
UTIL_H = 'OOXML/Base/unicode_util.h'


def source(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, check=True)
        return r.stdout.decode('utf-8-sig')
    with open(os.path.join(CORE, rel), 'rb') as f:
        return f.read().decode('utf-8-sig')


def extract(src, signature):
    at = src.find(signature)
    if at == -1:
        return None
    ob = src.index('{', at)
    depth = 0
    for i in range(ob, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces after %r' % signature)


reader = source(READER)
main_fn = extract(reader, 'void utf8_2_unicode(const unsigned char* data, DWORD data_size, std::wstring &wStr)')
if main_fn is None:
    raise SystemExit('utf8_2_unicode not found in %s - extractor needs updating' % READER)
helper = extract(reader, 'std::wstring utf8_2_unicode_lenient(') or ''

harness = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
typedef unsigned int DWORD;
#include "unicode_util.h"

struct Impl {
%s
%s
};

static int failures = 0;

static std::wstring decode(const char *bytes, size_t n)
{
    Impl impl; std::wstring w;
    impl.utf8_2_unicode((const unsigned char*)bytes, (DWORD)n, w);
    return w;
}

static void show(const std::wstring &w)
{
    printf("      got:");
    for (size_t i = 0; i < w.size(); ++i) printf(" %%X", (unsigned)w[i]);
    printf("\n");
}

static void expect(const char *what, const char *bytes, size_t n, const std::wstring &want)
{
    std::wstring got = decode(bytes, n);
    bool ok = (got == want);
    printf("  %%-64s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) { show(got); failures++; }
}

#define B(s) s, sizeof(s) - 1

int main()
{
    /* the report's shape: UTF-8 header, then a row with GBK yes/no values */
    expect("UTF-8 header kept when a later row has GBK bytes (the report)",
           B("Date,\"\xe6\x8f\x90\xe4\xba\xa4 [MB]\"\n31.10.2026,\xca\xc7,\xb7\xf1,1.5\n"),
           L"Date,\"提交 [MB]\"\n31.10.2026,ÊÇ,·ñ,1.5\n");

    /* B7 F1: F1 is a 4-byte lead; the comma after it must not be swallowed */
    expect("bad 4-byte lead does not eat the following separator",
           B("\xb7\xf1,x"), L"·ñ,x");

    expect("legacy code page file opened as UTF-8 reads as Latin-1",
           B("caf\xe9;na\xefve"), L"café;naïve");

    expect("truncated sequence at end of file",
           B("ok,\xe6\x8f"), L"ok,æ\u008f");

    expect("emoji (4-byte UTF-8) next to a bad byte",
           B("\xf0\x9f\x93\x81\xff"), std::wstring(1, (wchar_t)0x1F4C1) + L"ÿ");

    expect("fully valid UTF-8 is unchanged",
           B("\xe6\x98\xaf,\xe5\x90\xa6\n"), L"是,否\n");

    expect("plain ASCII is unchanged", B("a,b,c\n1,2,3\n"), L"a,b,c\n1,2,3\n");

    printf("\n%%s\n", failures
           ? "FAILED - one bad byte still garbles the UTF-8 text of the whole CSV"
           : "ok - invalid bytes are widened one by one, valid UTF-8 is kept");
    return failures ? 1 : 0;
}
''' % (helper, main_fn)

with tempfile.TemporaryDirectory() as work:
    for rel in (UTIL_CPP, UTIL_H):
        with open(os.path.join(work, os.path.basename(rel)), 'w', encoding='utf-8') as f:
            f.write(source(rel))
    with open(os.path.join(work, 'harness.cpp'), 'w', encoding='utf-8') as f:
        f.write(harness)
    exe = os.path.join(work, 'harness')
    cc = subprocess.run(['c++', '-std=c++14', '-w', '-I', work, '-o', exe,
                         os.path.join(work, 'harness.cpp'), os.path.join(work, 'unicode_util.cpp')],
                        capture_output=True, text=True)
    if cc.returncode != 0:
        sys.stderr.write(cc.stderr)
        raise SystemExit('compile failed')
    print('%s (%s)' % (CORE, ('BASELINE ' + BASE_REF) if BASELINE else 'working tree'), flush=True)
    sys.exit(subprocess.run([exe]).returncode)
