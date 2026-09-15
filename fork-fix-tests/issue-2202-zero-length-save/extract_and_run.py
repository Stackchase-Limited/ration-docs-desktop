#!/usr/bin/env python3
"""
#2202, the residual hole - a save that wrote nothing, over a locker that never
locked, still reported success.

The x2t half of #2202 is fixed: a conversion that never ran no longer returns 0.
What was left behind sits one step further down, in CLocalFileLocker::SaveFile
(desktop-sdk/ChromiumBasedEditors/lib/src/applicationmanager_p.h).  SaveFile
already guards the case the comment beside it describes - "an empty (nFileSize ==
0) document would be considered successfully saved even though opening the file
for writing failed" - by asking the locker StartWrite().  But StartWrite() cannot
answer that question:

  * CFileLocker::StartWrite() returns true unconditionally, and that is the one
    the FCNTL/Empty lockers inherit - the lockers used on macOS and for every
    local path on Linux, a CIFS mount included.
  * CFileLockerGIO::StartWrite() returns true when m_bIsReplace is false, which
    is what it is when Lock() gave up before it ever created m_pFile - i.e. when
    CheckLockFilePath found somebody else's .~lock on the share.

So a locker holding no descriptor still says "started".  With a zero-length
conversion result the write loop then does not execute even once, nothing
notices, bRes stays true - and the editor is told the document was saved.  That
is the #2081/#2056 failure again: the user is told their work is safe when
nothing whatsoever was written.

The fix adds CFileLocker::IsWriteReady(), overridden by each shipped locker, and
SaveFile asks it after StartWrite().

THIS TEST IS EXECUTED, not simulated.  The real, unmodified filelocker.cpp is
compiled and linked against the real core file/directory/system utilities, and
the real CLocalFileLocker is lifted verbatim out of applicationmanager_p.h.  The
lockers run real open(), write(), fcntl() and fsync() against real files in a
real temporary directory.  The locker with no descriptor is produced the way the
platform produces one - a target the process may not open for writing - rather
than by a stub pretending to be one.

  ./extract_and_run.py              -> passes
  BASELINE=1 ./extract_and_run.py   -> fails, at git HEAD
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))
SDK = os.path.join(REPO, 'desktop-sdk')
CORE = os.path.join(REPO, 'core')
APPMGR = 'ChromiumBasedEditors/lib/src/applicationmanager_p.h'
LOCKER_CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
LOCKER_H = 'ChromiumBasedEditors/lib/src/filelocker.h'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', SDK, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(SDK, rel), encoding='utf-8').read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces from offset %d' % start)


# --- the real CLocalFileLocker, lifted whole ------------------------------
appmgr = read(APPMGR)
at = appmgr.find('class CLocalFileLocker')
if at == -1:
    raise SystemExit('CLocalFileLocker not found in %s' % APPMGR)
local_locker = brace_match(appmgr, at) + ';'
for needle in ('bool SaveFile(', 'StartWrite()', 'Truncate(nFileSize)', 'Flush()'):
    if needle not in local_locker:
        raise SystemExit('extracted CLocalFileLocker is missing %r - wrong class?' % needle)

HAS_GATE = 'IsWriteReady()' in local_locker
HAS_NULL_GUARD = re.search(r'm_pLocker = NULL;\s*\n\s*\n\s*if \(sFile\.empty\(\)\)', local_locker) is not None

HARNESS = r'''
#include "filelocker.h"
#include "../../../../core/DesktopEditor/common/File.h"
#include "../../../../core/DesktopEditor/common/Directory.h"
#include "../../../../core/DesktopEditor/common/Types.h"

#include <stdio.h>
#include <string.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

using namespace NSSystem;

/* ====== the real CLocalFileLocker, lifted verbatim out of applicationmanager_p.h */
namespace NSSystem
{
%(local_locker)s
}

/* ======================================================================== */
static int failures = 0;
static std::string g_dir;

static void check(bool ok, const char *what)
{
    printf("    %%-58s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static std::wstring W(const std::string &s)
{ std::wstring w; for (size_t i = 0; i < s.size(); ++i) w += (wchar_t)(unsigned char)s[i]; return w; }

static void put(const std::string &path, const std::string &body)
{
    FILE *f = fopen(path.c_str(), "wb");
    if (f) { if (!body.empty()) fwrite(body.data(), 1, body.size(), f); fclose(f); }
}
static std::string get(const std::string &path)
{
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) return "<missing>";
    char b[4096]; size_t n = fread(b, 1, sizeof(b), f); fclose(f);
    return std::string(b, n);
}
/* One scenario: a target document, a converter result, and what SaveFile says. */
static void scenario(const char *title,
                     const std::string &target, const std::string &original, mode_t mode,
                     const std::string &converted,
                     bool removeTarget,
                     bool wantReported, const char *wantContent)
{
    printf("\n  %%s\n", title);

    std::string src = g_dir + "/x2t-output.bin";
    put(src, converted);

    put(target, original);
    chmod(target.c_str(), mode);

    /* The locker takes the document exactly as the editor does. */
    CLocalFileLocker *pLocker = new CLocalFileLocker(W(target));

    if (removeTarget)
        unlink(target.c_str());

    bool reported = pLocker->SaveFile(W(src));
    delete pLocker;

    chmod(target.c_str(), 0600);
    std::string after = get(target);

    printf("      converter wrote %%zu byte(s); SaveFile reports %%s; the document is now %%s\n",
           converted.size(), reported ? "SAVED" : "not saved",
           after == "<missing>" ? "<missing>" : ("\"" + after + "\"").c_str());

    check(reported == wantReported,
          wantReported ? "the save is reported successful" : "the save is NOT reported successful");
    if (wantContent)
        check(after == wantContent, "the document on disk is what it should be");

    unlink(target.c_str());
    unlink(src.c_str());
}

int main()
{
    char tmpl[] = "/tmp/rd2202_XXXXXX";
    char *d = mkdtemp(tmpl);
    if (!d) { printf("cannot make a temp directory\n"); return 2; }
    g_dir = d;

    const std::string doc = g_dir + "/budget.xlsx";

    printf("  locker in use for a local path on this host: %%s\n",
           "CFileLockerFCNTL (filelocker.cpp CFileLocker::Create)");

    /* ---- the hole ---------------------------------------------------------
       A document the process cannot open for writing.  Lock() writes its .~lock
       marker, then open(O_WRONLY|O_EXCL) is refused and it returns without a
       descriptor - the same state Lock() ends in on a share when the byte-range
       lock or the open is refused.  The converter then produces nothing. */
    scenario("a locker with no descriptor, and a zero-length converter result",
             doc, "ORIGINAL DOCUMENT", 0444, "", false,
             false, "ORIGINAL DOCUMENT");

    /* ---- the same locker, with bytes to write: already caught by the loop -- */
    scenario("the same locker, with a real converter result",
             doc, "ORIGINAL DOCUMENT", 0444, "NEW CONTENT", false,
             false, "ORIGINAL DOCUMENT");

    /* ---- behaviour that must not change ----------------------------------- */
    scenario("a healthy locker and a real converter result",
             doc, "ORIGINAL DOCUMENT", 0644, "NEW CONTENT", false,
             true, "NEW CONTENT");

    scenario("a healthy locker and a genuinely empty document",
             doc, "ORIGINAL DOCUMENT", 0644, "", false,
             true, "");

    /* WriteFile() re-creates a document that vanished from under the editor and
       takes its descriptor there; IsWriteReady() must not cut that off. */
    scenario("the document was deleted from under the editor",
             doc, "ORIGINAL DOCUMENT", 0644, "RECOVERED", true,
             true, "RECOVERED");

    /* ---- an empty path must not crash -------------------------------------- */
    printf("\n  a locker over an empty path\n");
    if (%(null_guard)s) {
        CLocalFileLocker *pEmpty = new CLocalFileLocker(L"");
        bool ok = !pEmpty->SaveFile(W(g_dir + "/nothing"));
        delete pEmpty;                       /* this is where it used to crash */
        check(ok, "no locker, so nothing is reported saved");
    } else {
        printf("      skipped: this revision leaves m_pLocker uninitialised, and\n"
               "      exercising it would be undefined behaviour, not a test\n");
    }

    rmdir(g_dir.c_str());
    printf("\n  %%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''


def sdk_source(rel, into):
    """Materialise a desktop-sdk source at the revision under test."""
    body = read(rel)
    path = os.path.join(into, os.path.basename(rel))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


print('#2202 (residual) - a zero-length save over a locker that never locked')
print('source: %s' % ('git %s (BASELINE)' % BASE_REF if BASELINE else 'working tree'))
print('=' * 74)
sys.stdout.flush()

d = tempfile.mkdtemp(prefix='rd2202_build_')
# filelocker.cpp/.h go in side by side, and keep their "../../../../core/..."
# includes working, so the build directory mirrors the tree's depth.
# src/ sits four directories under the repository root, and the sources reach
# core with "../../../../core/..." - so mirror that depth exactly.
deep = os.path.join(d, 'desktop-sdk', 'ChromiumBasedEditors', 'lib', 'src')
os.makedirs(deep)
os.symlink(CORE, os.path.join(d, 'core'))
locker_cpp = sdk_source(LOCKER_CPP, deep)
sdk_source(LOCKER_H, deep)

main_cpp = os.path.join(deep, 'harness.cpp')
with open(main_cpp, 'w') as f:
    f.write(HARNESS % {'local_locker': local_locker,
                       'null_guard': 'true' if HAS_NULL_GUARD else 'false'})

exe = os.path.join(d, 'harness')
cmd = ['clang++', '-std=c++14', '-D_MAC', '-D_LINUX',
       # Directory.cpp/File.cpp assume a Linux toolchain's transitive includes
       # under _LINUX; supply the two headers it leans on rather than edit core.
       '-include', 'sys/stat.h', '-include', 'stdlib.h', '-include', 'unistd.h',
       '-Wno-writable-strings', '-Wno-deprecated-declarations',
       '-I', deep, '-o', exe, main_cpp, locker_cpp,
       os.path.join(CORE, 'DesktopEditor/common/File.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/Directory.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/SystemUtils.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/StringBuilder.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/Base64.cpp')]
c = subprocess.run(cmd, capture_output=True, text=True)
if c.returncode != 0:
    sys.stderr.write(c.stdout + c.stderr)
    raise SystemExit('the harness did not build (sources kept in %s)' % d)

sys.stdout.flush()
rc = subprocess.run([exe]).returncode

print('=' * 74)
if rc:
    if not HAS_GATE:
        sys.stderr.write(
            '\nSaveFile asks the locker only StartWrite(), which the base locker answers\n'
            'true unconditionally, so a locker holding no descriptor reports a save it\n'
            'never performed whenever the converter result is zero-length (#2202).\n')
    print('FAILED')
else:
    print('ok - a save is only reported once a locker that can write has written')
sys.exit(1 if rc else 0)
