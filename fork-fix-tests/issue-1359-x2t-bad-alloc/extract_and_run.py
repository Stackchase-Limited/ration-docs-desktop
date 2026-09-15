#!/usr/bin/env python3
r"""
#1359, second half - x2t could not survive hitting its own memory cap.

X2tConverter/src/main.cpp applies X2T_MEMORY_LIMIT (4GiB by default) with
setrlimit(RLIMIT_DATA) - see Common/3dParty/misc/proclimits.h - and until this
change there was no try/catch and no set_new_handler anywhere in x2t.  So the
std::bad_alloc thrown when a file exhausted the cap ran off the top of main,
terminate() fired, and the process died on SIGABRT.  The editor has no exit code
to read in that case, only a dead converter, so it shows the generic "Something
has gone wrong..." - indistinguishable from a corrupt file.  The CSV reader
materialises the whole workbook at roughly 120x the input size, which is what
puts the #1359 reporter's 35.6MB CSV over a 4GiB cap that their 9.5MB one clears.

This harness does not re-type the handler.  It pulls the REAL
errorCodeForCurrentException() out of main.cpp by brace matching, the REAL
getReturnErrorCode() out of cextracttools.cpp the same way, compiles them
against the REAL Common/OfficeFileErrorDescription.h, and then throws real
exceptions at the real handler and reads back the real exit code.

It also checks, against the real sdkjs and web-apps sources, that the code the
handler returns is one the editor already turns into a truthful message, and
that the obvious alternative does not:

    AVS_FILEUTILS_ERROR_CONVERT_LIMITS     -> exit 93 -> sdkjs ConvertLIMITS
        -> c_oAscError.ID.ConvertationOpenLimitError -> SSE errorFileSizeExceed
    AVS_FILEUTILS_ERROR_CONVERT_CELLLIMITS -> exit 96 -> no sdkjs entry at all

  BASELINE=1 re-reads main.cpp from BASE_REF, where no handler exists at all and
  the harness must fail.

e2e.py beside this file runs the real x2t both ways and is the stronger proof:
it shows the shipped converter dying on a signal and the fixed one exiting 93.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
CORE = os.path.join(ROOT, 'core')

# Pinned, NOT HEAD: left on HEAD this stops differing the moment the fix is
# committed and then reports success forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', 'af68137e075d3169e24d93590f3844290a9605ef')
BASELINE = bool(os.environ.get('BASELINE'))

MAIN = 'X2tConverter/src/main.cpp'
TOOLS = 'X2tConverter/src/cextracttools.cpp'
ERRORS = 'Common/OfficeFileErrorDescription.h'


def source(rel):
    """The file as it is now, or as it was at BASE_REF."""
    if BASELINE:
        r = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, check=True)
        return r.stdout.decode('utf-8-sig')
    with open(os.path.join(CORE, rel), 'rb') as f:
        return f.read().decode('utf-8-sig')


def blank_noncode(text):
    """Same text, with comments and string/char literals turned into spaces.

    Only used to *locate* braces - what gets extracted is always the original
    text - so that a brace or quote inside a comment cannot move the boundary.
    """
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
            quote = c
            i += 1
            while i < n and text[i] != quote:
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


def match_braces(code, open_at):
    depth = 0
    for i in range(open_at, len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced braces')


def extract_function(rel, name):
    """The whole definition of `name`, from its return type to its closing brace."""
    src = source(rel)
    code = blank_noncode(src)
    m = re.search(r'\b%s\s*\(' % re.escape(name), code)
    if not m:
        return None
    # back up to the start of the line the signature begins on
    line_start = code.rfind('\n', 0, m.start()) + 1
    # a wrapped signature may start on an earlier line, but neither of ours does
    open_brace = code.index('{', m.end())
    close_brace = match_braces(code, open_brace)
    return src[line_start:close_brace + 1]


handler = extract_function(MAIN, 'errorCodeForCurrentException')
retcode = extract_function(TOOLS, 'getReturnErrorCode')
errors_h = source(ERRORS)

failures = []

if retcode is None:
    raise SystemExit('getReturnErrorCode not found in %s - the extractor needs updating' % TOOLS)

if handler is None:
    print('%s has no errorCodeForCurrentException().' % MAIN)
    print('Nothing in x2t catches anything, so a std::bad_alloc from the conversion')
    print('reaches terminate() and the process dies on a signal instead of returning')
    print('an error code the editor can turn into a message.')
    print('\nFAILED - #1359 (the memory cap half)')
    raise SystemExit(1)

# ---------------------------------------------------------------- C++ harness
harness = r'''
#include <stdio.h>
#include <string.h>
#include <exception>
#include <new>
#include <stdexcept>

typedef unsigned int _UINT32;

#include "OfficeFileErrorDescription.h"

/* The real handler, lifted whole out of X2tConverter/src/main.cpp. */
%(handler)s

/* The real exit-code arithmetic, lifted whole out of cextracttools.cpp. */
namespace NExtractTools {
%(retcode)s
}

static int failures = 0;

static void check(bool ok, const char *what, const char *detail)
{
    printf("  %%-3s %%-46s %%s\n", ok ? "ok" : "!!", what, detail);
    if (!ok) failures++;
}

/* Every call below goes through a real throw and a real catch(...), which is
 * exactly how main.cpp reaches the handler. */
template <typename T>
static _UINT32 raise_and_classify(const T &e)
{
    try { throw e; }
    catch (...) { return errorCodeForCurrentException(); }
}

static _UINT32 raise_non_exception()
{
    try { throw 42; }
    catch (...) { return errorCodeForCurrentException(); }
}

int main()
{
    char detail[200];

    /* 1. an allocation failure must come back as the limits code, not as death */
    _UINT32 got = raise_and_classify(std::bad_alloc());
    snprintf(detail, sizeof(detail), "[returned 0x%%08X, exit %%d]",
             got, NExtractTools::getReturnErrorCode(got));
    check(got == AVS_FILEUTILS_ERROR_CONVERT_LIMITS,
          "std::bad_alloc -> AVS_FILEUTILS_ERROR_CONVERT_LIMITS", detail);

    /* 2. and as the exit code sdkjs already knows how to talk about */
    int rc = NExtractTools::getReturnErrorCode(got);
    snprintf(detail, sizeof(detail), "[exit %%d]", rc);
    check(rc == 93, "which x2t exits with as 93 (sdkjs ConvertLIMITS)", detail);

    /* 3. it must not be mistaken for success anywhere up the stack */
    check(!SUCCEEDED_X2T_LIKE(got), "and is not one of the codes counted as success", "[]");

    /* 4. any other std::exception is still an error, not a crash */
    got = raise_and_classify(std::runtime_error("boom"));
    rc = NExtractTools::getReturnErrorCode(got);
    snprintf(detail, sizeof(detail), "[returned 0x%%08X, exit %%d]", got, rc);
    check(got == AVS_FILEUTILS_ERROR_CONVERT && rc == 80,
          "std::runtime_error -> AVS_FILEUTILS_ERROR_CONVERT (exit 80)", detail);

    /* 5. so is something that is not a std::exception at all */
    got = raise_non_exception();
    rc = NExtractTools::getReturnErrorCode(got);
    snprintf(detail, sizeof(detail), "[returned 0x%%08X, exit %%d]", got, rc);
    check(got == AVS_FILEUTILS_ERROR_CONVERT && rc == 80,
          "throw 42 -> AVS_FILEUTILS_ERROR_CONVERT (exit 80)", detail);

    /* 6. success is still success - the handler must not be reachable otherwise */
    check(NExtractTools::getReturnErrorCode(0) == 0, "0 still exits 0", "[]");

    printf("\n%%s\n", failures
           ? "FAILED - an exception escaping the conversion does not become an error code"
           : "ok - an exception escaping the conversion becomes a reportable error code");
    return failures ? 1 : 0;
}
'''

# SUCCEEDED_X2T lives in cextracttools.h, which drags in the whole converter;
# spell the same membership test with the real macro's real members instead.
prologue = ('#define SUCCEEDED_X2T_LIKE(n) (0 == (n) || '
            'AVS_FILEUTILS_ERROR_CONVERT_ROWLIMITS == (n) || '
            'AVS_FILEUTILS_ERROR_CONVERT_CELLLIMITS == (n))\n')

harness = harness % {'handler': handler, 'retcode': retcode}
harness = harness.replace('#include "OfficeFileErrorDescription.h"',
                          '#include "OfficeFileErrorDescription.h"\n' + prologue)

with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, 'OfficeFileErrorDescription.h'), 'w', encoding='utf-8') as f:
        f.write(errors_h)
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(harness)
    cmd = ['clang++', '-std=c++11', '-O1', '-Wall', '-Wno-unused-function',
           '-I', d, '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    print('Running the real errorCodeForCurrentException() from %s' % MAIN)
    print('(its own stderr messages appear first)\n')
    sys.stdout.flush()
    rc_cpp = subprocess.run([exe]).returncode

# ------------------------------------------------- the editor side of the code
# Prefer a code that already has a message over one that does not.  These are
# read out of the real sdkjs/web-apps sources, not asserted from memory.
print('\nWhat the editor does with the code the handler returns:')

def read(path):
    with open(path, 'rb') as f:
        return f.read().decode('utf-8-sig', 'replace')

js_failures = []


def note(ok, what, detail):
    print('  %-3s %-46s %s' % ('ok' if ok else '!!', what, detail))
    if not ok:
        js_failures.append(what)


ec = read(os.path.join(ROOT, 'sdkjs', 'common', 'editorscommon.js'))
m = re.search(r'ConvertLIMITS\s*:\s*(-?\d+)', ec)
note(bool(m) and m.group(1) == '-93', 'sdkjs c_oAscServerError.ConvertLIMITS is -93',
     '[%s]' % (m.group(1) if m else 'absent'))

m = re.search(r'case\s+c_oAscServerError\.ConvertLIMITS\s*:\s*\n\s*nRes\s*=\s*'
              r'Asc\.c_oAscError\.ID\.(\w+)\s*;', ec)
note(bool(m) and m.group(1) == 'ConvertationOpenLimitError',
     'which maps to c_oAscError.ID.ConvertationOpenLimitError',
     '[%s]' % (m.group(1) if m else 'not mapped'))

# nothing claims -96, which is what CELLLIMITS (0x60) would exit with
note(not re.search(r':\s*-96\s*,', ec), 'and -96 (CELLLIMITS) has no sdkjs entry',
     '[so it would fall through to Unknown]')

sse = read(os.path.join(ROOT, 'web-apps', 'apps', 'spreadsheeteditor', 'main',
                        'app', 'controller', 'Main.js'))
m = re.search(r'case\s+Asc\.c_oAscError\.ID\.ConvertationOpenLimitError\s*:\s*\n\s*'
              r'config\.msg\s*=\s*this\.(\w+)\s*;', sse)
note(bool(m), 'which the spreadsheet shell renders as a message',
     '[%s]' % (m.group(1) if m else 'not rendered'))

if m:
    loc = read(os.path.join(ROOT, 'web-apps', 'apps', 'spreadsheeteditor', 'main',
                            'locale', 'en.json'))
    key = '"SSE.Controllers.Main.%s"' % m.group(1)
    hit = re.search(re.escape(key) + r'\s*:\s*"([^"]{10,})', loc)
    note(bool(hit), 'whose en.json text says something true',
         '["%s..."]' % (hit.group(1)[:44] if hit else 'missing'))

print()
if rc_cpp or js_failures:
    print('FAILED')
    sys.exit(1)
print('ok - hitting the memory cap now reports AVS_FILEUTILS_ERROR_CONVERT_LIMITS,')
print('     which the editor already turns into "The file size exceeds the limitation".')
sys.exit(0)
