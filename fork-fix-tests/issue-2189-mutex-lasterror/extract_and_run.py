#!/usr/bin/env python3
"""
#2189 - "OnlyOffice closes itself on startup", every time, with no message.

SingleApplication decides it is the only instance with

    m_hMutex = CreateMutex(NULL, FALSE, TEXT(APP_MUTEX_NAME));
    if (GetLastError() != ERROR_ALREADY_EXISTS) { ... primary ... }

GetLastError() is thread-local and sticky.  CreateMutex *sets*
ERROR_ALREADY_EXISTS when the mutex was already there, but it does not clear the
value when it creates the mutex fresh - so the check reads whatever last failed on
this thread.  ERROR_ALREADY_EXISTS is the likeliest thing to be sitting there: it
is what CreateDirectory leaves for a directory that already exists, and Qt touches
its settings and cache directories while QApplication is constructed, which happens
in the initialiser list immediately above this code.

When that happens, the only running instance decides it is a second one, spends
five seconds looking for a receiver window that does not exist, and returns 0 from
main - the app "closes itself on startup", with nothing printed.

This extracts the real constructor body out of singleapplication.cpp by brace
matching and runs it against a fake Win32 layer, so the sticky-error behaviour can
be reproduced on any host.  BASELINE=1 runs it against HEAD, where it must fail.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/platform_win/singleapplication.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', 'cba281172d^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()

m = re.search(r'SingleApplication::SingleApplication\s*\([^)]*\)\s*:.*?\n\{', source, re.S)
if not m:
    raise SystemExit('constructor not found - the extractor needs updating')
open_brace = source.index('{', m.end() - 1)
depth = 0
end = None
for i in range(open_brace, len(source)):
    if source[i] == '{':
        depth += 1
    elif source[i] == '}':
        depth -= 1
        if depth == 0:
            end = i
            break
if end is None:
    raise SystemExit('unbalanced braces in the constructor')
body = source[open_brace + 1:end]
if 'CreateMutex' not in body:
    raise SystemExit('extracted the wrong block')

harness = r'''
#include <stdio.h>
#include <string.h>

/* --- a fake Win32, just enough for the extracted block --- */
typedef unsigned long DWORD;
typedef void*         HANDLE;
#define NULL_HANDLE ((HANDLE)0)
#define TEXT(x) x
#define FALSE false
#define APP_MUTEX_NAME "asc:editors"
static const DWORD ERROR_SUCCESS        = 0;
static const DWORD ERROR_ALREADY_EXISTS = 183;
static const DWORD ERROR_ACCESS_DENIED  = 5;

static DWORD  g_lastError   = ERROR_SUCCESS;
static bool   g_mutexExists = false;   /* another instance already holds it */
static bool   g_mutexFails  = false;   /* CreateMutex fails outright */

static void  SetLastError(DWORD e) { g_lastError = e; }
static DWORD GetLastError()        { return g_lastError; }

static HANDLE CreateMutex(void*, bool, const char*) {
    if (g_mutexFails) { g_lastError = ERROR_ACCESS_DENIED; return (HANDLE)0; }
    if (g_mutexExists) { g_lastError = ERROR_ALREADY_EXISTS; return (HANDLE)0x1234; }
    /* Fresh creation: Windows does NOT clear the thread's last error here. */
    return (HANDLE)0x1234;
}

/* --- the object under test --- */
struct SingleApplication {
    HANDLE m_hMutex = (HANDLE)0;
    bool   m_isPrimary = false;
    bool   m_startedPrimary = false;
    void startPrimary() { m_startedPrimary = true; }
    void construct();
};

void SingleApplication::construct() {
%(body)s
}

static int failures = 0;
static void scenario(const char *name, DWORD stale, bool exists, bool fails,
                     bool wantPrimary) {
    g_lastError   = stale;
    g_mutexExists = exists;
    g_mutexFails  = fails;

    SingleApplication app;
    app.construct();

    bool ok = (app.m_isPrimary == wantPrimary) &&
              (app.m_startedPrimary == wantPrimary);
    printf("  %%-56s %%s\n", name, ok ? "ok" : "FAILED");
    if (!ok) {
        printf("      wanted isPrimary=%%s, got isPrimary=%%s\n",
               wantPrimary ? "true" : "false", app.m_isPrimary ? "true" : "false");
        failures++;
    }
}

int main() {
    /* The defect: a sole instance, with ERROR_ALREADY_EXISTS left on the thread by
       something earlier - which is what CreateDirectory leaves for a directory that
       already exists, and Qt touches its config directories during construction. */
    scenario("sole instance, stale ERROR_ALREADY_EXISTS on the thread",
             ERROR_ALREADY_EXISTS, false, false, true);

    /* Any other stale value must not change the answer either. */
    scenario("sole instance, stale ERROR_ACCESS_DENIED on the thread",
             ERROR_ACCESS_DENIED, false, false, true);

    /* The ordinary cases must keep working. */
    scenario("sole instance, clean thread error",
             ERROR_SUCCESS, false, false, true);
    scenario("a second instance: the mutex really does exist",
             ERROR_SUCCESS, true, false, false);
    scenario("a second instance, with a stale error as well",
             ERROR_ACCESS_DENIED, true, false, false);

    /* If CreateMutex fails we cannot know - start, rather than vanish. */
    scenario("CreateMutex fails outright: start anyway",
             ERROR_SUCCESS, false, true, true);

    printf("%%s\n", failures ? "FAILED" : "ok - primacy depends on the mutex, not on a stale thread error");
    return failures ? 1 : 0;
}
''' % {'body': body}

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-std=c++11', '-Wall', '-Wno-unused-const-variable',
                        '-o', exe, src], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
