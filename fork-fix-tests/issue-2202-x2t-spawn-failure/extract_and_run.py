#!/usr/bin/env python3
"""
#2202 - "This file could not be saved or created" after a document has been open
for a few hours (3 to 12+, varying), on Fedora/Flatpak.  Related: #2417 (macOS,
hours of work lost silently), #1436 (Synology NAS).

WHAT THIS DOES AND DOES NOT CLAIM.  The trigger for #2202 is still unidentified -
nobody has reproduced it on demand.  What this test covers is a real defect on
the same save path, in the same family as #2081/#2056: a save that converted
NOTHING being reported to the editor as a completed save.

NSX2T::Convert (desktop-sdk/ChromiumBasedEditors/lib/src/x2t.h) runs x2t and
returns its exit status.  That int is the entire story the save path gets:
CASCFileConverterFromEditor::ThreadProc (fileconverter.h:1189+) treats 0 as "x2t
wrote the document", deletes the temp output, and OnFileConvertFromEditor(0)
marks the document clean.  On the POSIX branch, two failure modes returned 0:

  * fork() failed - `case -1: break;` left nReturnCode at 0.  fork fails with
    EAGAIN on the process/thread limit and ENOMEM when memory is short, both of
    which grow likelier the longer a session runs and the more renderer
    processes and threads CEF has accumulated.  This is the shape of a bug that
    appears "after a few hours" and at a varying time.

  * execve() failed - the child fell through to `exit(EXIT_SUCCESS)`, so the
    parent read exit status 0.  execve fails with EMFILE/ENFILE, ENOMEM,
    ETXTBSY, or a missing/non-executable x2t.

Two more on the same path, fixed with them:
  * `while (-1 == waitpid(pid, &status, 0));` retried on ANY error.  waitpid
    returns ECHILD immediately and forever, so that was an infinite busy loop
    holding the save thread - a save that never returns.  Only EINTR is a retry.
  * A child killed by a signal (the OOM killer) left WIFEXITED false and
    nReturnCode at its initial 0.

The env/arg strings are also now built BEFORE the fork.  This process is
multi-threaded (CEF) and only the forking thread survives into the child, so
those std::string concatenations - which allocate - ran in a context where the
allocator lock may have been held by another thread at the moment of the fork.
That deadlocks the child, with the parent blocked in waitpid forever.  Not
directly observable from a single-threaded harness; called out here because it
is part of the same change.

This extracts the real Convert() out of x2t.h by brace matching and runs it
against stubs, with REAL fork/execve failures on this host - no simulation of
the failure itself.

  BASELINE=1 re-reads x2t.h from git HEAD, where it must FAIL.

A detail worth expecting: under BASELINE the output above the failures appears
two and three times over.  That is not the harness misbehaving, it is the
exit(EXIT_SUCCESS) defect showing itself.  The forked child inherits the
parent's stdio buffer, execve fails, and exit() - unlike _exit() - flushes that
inherited buffer, so every failed exec reprints whatever the parent had not yet
written out.  In the real application the same flush replays whatever the
browser process had buffered.
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
REL = 'ChromiumBasedEditors/lib/src/x2t.h'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', 'f4b4f990^')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()

SIG = 'static int Convert(const std::wstring& sConverterPath, const std::wstring sXmlPath, CAscApplicationManager* pManager, bool bIsLoggingErrors = false)'
at = src.find(SIG)
if at == -1:
    raise SystemExit('NSX2T::Convert not found in %s - the extractor needs updating' % REL)
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
convert_fn = src[at:end + 1]

# Sanity: this is the spawning function, not something else with the same shape.
for needle in ('fork()', 'execve(', 'waitpid('):
    if needle not in convert_fn:
        raise SystemExit('extracted function is missing %r - wrong function?' % needle)

# The WIN32 arm is left in the text and dropped by the preprocessor, exactly as
# it is in the real build. _MAC is set to match the branch that ships on this host.
is_mac = platform.system() == 'Darwin'

harness = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <unistd.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>

/* ---- stubs: the surroundings Convert() compiles against ----------------- */
static std::string to_utf8(const std::wstring &w)
{
    std::string s;
    for (size_t i = 0; i < w.size(); ++i) s += (char)w[i];   /* ASCII paths only here */
    return s;
}
#define U_TO_UTF8(x) to_utf8(x)

struct Settings {
    std::string converter_application_name;
    std::string converter_application_company;
};
struct CAscApplicationManager {
    Settings m_oSettings;
    std::string GetLibraryPathVariable() { return "/usr/lib"; }
};

namespace NSFile {
    struct CFileBinary {
        static bool ReadAllTextUtf8A(const std::wstring &, std::string &out)
        { out = "<xml/>"; return true; }
    };
    static std::wstring GetDirectoryName(const std::wstring &p)
    {
        size_t at = p.find_last_of(L'/');
        return at == std::wstring::npos ? std::wstring(L".") : p.substr(0, at);
    }
}
namespace NSStringUtils {
    static void string_replaceA(std::string &s, const std::string &from, const std::string &to)
    {
        size_t at = 0;
        while (std::string::npos != (at = s.find(from, at))) { s.replace(at, from.size(), to); at += to.size(); }
    }
}

/* ---- the real NSX2T::Convert, lifted verbatim out of x2t.h ------------- */
namespace NSX2T
{
%(convert_fn)s
}

/* ------------------------------------------------------------------------ */
static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-66s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static CAscApplicationManager g_mgr;

static int runConvert(const char *program)
{
    std::wstring wp, wx(L"/tmp/x2t-params-does-not-matter.xml");
    for (const char *p = program; *p; ++p) wp += (wchar_t)*p;
    return NSX2T::Convert(wp, wx, &g_mgr, false);
}

/* Write an executable shell script and return its path. */
static std::string writeScript(const char *dir, const char *name, const char *body)
{
    std::string path = std::string(dir) + "/" + name;
    FILE *f = fopen(path.c_str(), "w");
    fprintf(f, "#!/bin/sh\n%%s\n", body);
    fclose(f);
    chmod(path.c_str(), 0755);
    return path;
}

int main(int argc, char **argv)
{
    char tmpl[] = "/tmp/x2t-spawn-XXXXXX";
    const char *dir = mkdtemp(tmpl);
    if (!dir) { printf("could not make a temp dir\n"); return 77; }

    /* A sub-run used for the fork-failure case: RLIMIT_NPROC is per-uid and
     * lowering it poisons the whole process, so it is done in a child. */
    if (argc > 1 && 0 == strcmp(argv[1], "--forkfail"))
    {
        struct rlimit rl;
        getrlimit(RLIMIT_NPROC, &rl);
        rl.rlim_cur = 1;
        if (0 != setrlimit(RLIMIT_NPROC, &rl))
            _exit(77);
        int rc = runConvert(argv[2]);
        /* 0 would mean "x2t converted the document" for a fork that never happened. */
        _exit(rc == 0 ? 1 : 0);
    }

    std::string ok0    = writeScript(dir, "x2t-ok",     "exit 0");
    std::string err90  = writeScript(dir, "x2t-err90",  "exit 90");
    std::string killed = writeScript(dir, "x2t-killed", "kill -9 $$");
    std::string noexec = std::string(dir) + "/x2t-not-executable";
    { FILE *f = fopen(noexec.c_str(), "w"); fprintf(f, "not a program\n"); fclose(f); }
    chmod(noexec.c_str(), 0644);
    std::string missing = std::string(dir) + "/x2t-does-not-exist";

    printf("a conversion that really happened must keep reporting its own code:\n");
    check(0  == runConvert(ok0.c_str()),   "x2t exits 0  -> Convert returns 0 (a good save)");
    check(90 == runConvert(err90.c_str()), "x2t exits 90 -> Convert returns 90 (code preserved)");

    printf("\na conversion that never happened must NOT report success:\n");
    {
        int rc = runConvert(missing.c_str());
        char buf[160];
        snprintf(buf, sizeof buf, "x2t is missing            -> Convert returns %%d", rc);
        check(rc != 0, buf);
    }
    {
        int rc = runConvert(noexec.c_str());
        char buf[160];
        snprintf(buf, sizeof buf, "x2t is not executable     -> Convert returns %%d", rc);
        check(rc != 0, buf);
    }
    {
        int rc = runConvert(killed.c_str());
        char buf[160];
        snprintf(buf, sizeof buf, "x2t killed by a signal    -> Convert returns %%d", rc);
        check(rc != 0, buf);
    }

    printf("\nfork() itself failing (RLIMIT_NPROC), in a sub-process:\n");
    {
        pid_t pid = fork();
        if (0 == pid)
        {
            execl(argv[0], argv[0], "--forkfail", ok0.c_str(), (char *)NULL);
            _exit(77);
        }
        int st = 0;
        while (-1 == waitpid(pid, &st, 0) && EINTR == errno) {}
        int code = WIFEXITED(st) ? WEXITSTATUS(st) : -1;
        if (77 == code)
            printf("  %%-66s %%s\n", "this host would not lower RLIMIT_NPROC - not exercised", "skip");
        else
            check(0 == code, "fork() fails            -> Convert does not return 0");
    }

    /* tidy up */
    unlink(ok0.c_str()); unlink(err90.c_str()); unlink(killed.c_str());
    unlink(noexec.c_str()); rmdir(dir);

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - a conversion that did not happen is never reported as a save");
    return failures ? 1 : 0;
}
''' % {'convert_fn': convert_fn}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    cmd = ['clang++', '-std=c++14', '-Wall', '-Wno-unused-variable', '-Wno-unused-function',
           '-DLINUX'] + (['-D_MAC'] if is_mac else []) + ['-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
