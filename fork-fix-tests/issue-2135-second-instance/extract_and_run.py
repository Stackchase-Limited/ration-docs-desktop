#!/usr/bin/env python3
"""
#2135 - "Allow the edition of two instances of the same document."

The reporter wants two editable views of one document at the same time, so that a
long text can be looked at in two places without scrolling.  They point at the
Document Server, where two browser tabs on one document work.

This test does not fix anything.  It measures what the shipped lock actually
protects, so that the cost of granting the request is a number and not an opinion.
Everything below is the real code from desktop-sdk, extracted by brace matching -
CFileLockerFCNTL::Lock, CFileLockerFCNTL::Unlock, CFileLockerFCNTL::IsLockedInternal,
CFileLocker::CheckLockFilePath and the whole CLockFileTemp - run over the real
filesystem of this host with real open/fcntl and a real forked child.

Four things get measured:

  A  Nobody holds the file          -> ltNone.                       (sanity)
  B  ANOTHER PROCESS holds a real F_WRLCK -> ltLocked.
     This is the cross-process case, and it works.  Launching a second copy of
     the application is therefore already refused: the second one opens the
     document read-only.  It is also the #1362 regression guard - see the
     BASELINE note at the bottom.
  C  THIS PROCESS holds the lock, taken by the real CFileLockerFCNTL::Lock()
     (real fcntl F_WRLCK plus the real .~lock.<name># marker), and then asks
     the real IsLockedInternal      -> ltNone.
     A POSIX byte-range lock does not conflict with its owner, and the marker
     records user+host+app-data-dir, which a second view in the same process
     matches exactly.  So the locker sees nothing.  A second tab or window
     inside the running editor would be handed "free, go ahead and write" -
     and the desktop save path is Seek(0)/WriteFile/Truncate over the whole
     file, so the second save silently discards the first.  This is the number
     that says a same-process "just allow it" is a data-loss change.
  D  A .~lock left behind by ANOTHER user -> ltLocked, and a .~lock left behind
     by THIS user (crash residue) -> ltNone.  The cooperative marker is keyed to
     the person, not to the process, so it cannot separate two views of one user
     either - and, usefully, a stale marker of one's own does not wedge the file.
     (On a LOCAL path this half already worked before #1362; that fix was about
     the marker on a gvfs address.  D is here to characterise the marker, not as
     a regression guard.)

BASELINE: set BASELINE=1 to re-read filelocker.{h,cpp} from BASE_REF, which
defaults to the commit BEFORE #1362 landed (6cd9fdd6, the parent of 679ebd74).
There, B must FAIL - the pre-fix IsLockedInternal asks F_GETLK with a
memset-zeroed flock, which macOS rejects with EINVAL, and reports the file free
even while a real child process holds a real F_WRLCK.  That failure is what
proves this harness is running the shipped function and not a convenient copy of
it.  C and D are measurements, not guards, and read the same either way.  Never
point BASE_REF at HEAD: once a fix is committed HEAD stops differing and the
check silently passes forever while testing nothing.

Stubs, named honestly: NSFile::CFileBinary / NSFile::GetDirectoryName /
GetFileName / NSSystemUtils / NSStringUtils are thin wrappers over POSIX and are
reimplemented here over real POSIX calls - they are not the subject.
CHandlesMonitor is a bookkeeping set that no verdict reads.  open(), fcntl(),
fork() and the filesystem are real.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
HDR = 'ChromiumBasedEditors/lib/src/filelocker.h'

# Pinned to a SHA on purpose.  6cd9fdd6 is 679ebd74^ - the tree as it was the
# moment before the #1362 read-side fix landed.
BASE_REF = os.environ.get('BASE_REF', '6cd9fdd654706f281a00ac2f9036367dcd7ed5af')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


SRC = read(CPP)
HEAD = read(HDR)


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


def extract(text, anchor, needles=(), after=0, what=None):
    at = text.find(anchor, after)
    if at == -1:
        raise SystemExit('%r not found - the extractor needs updating' % (what or anchor))
    body = brace_match(text, at)
    for n in needles:
        if n not in body:
            raise SystemExit('extracted %r is missing %r - wrong block?' % (what or anchor, n))
    return body, at


# ---------------------------------------------------------------- extraction
cls_fcntl, _ = extract(SRC, 'class CFileLockerFCNTL', ('F_SETLK', 'F_GETLK'),
                       what='class CFileLockerFCNTL')
fn_lock, _ = extract(cls_fcntl, 'virtual bool Lock()',
                     ('CheckLockFilePath', 'F_WRLCK', 'open('),
                     what='CFileLockerFCNTL::Lock')
fn_unlock, _ = extract(cls_fcntl, 'virtual bool Unlock()', ('F_UNLCK',),
                       what='CFileLockerFCNTL::Unlock')
fn_isuse, _ = extract(cls_fcntl, 'static bool IsUseLockFile()', ('return',),
                      what='CFileLockerFCNTL::IsUseLockFile')
fn_islocked, _ = extract(cls_fcntl, 'static LockType IsLockedInternal',
                         ('access(', 'open(', 'F_GETLK', 'CheckLockFilePath'),
                         what='CFileLockerFCNTL::IsLockedInternal')

lock_decl, _ = extract(HEAD, 'class CLockFileTemp',
                       ('Generate', 'Save', 'Load', 'IsEqual'),
                       what='class CLockFileTemp (header)')
lock_decl += ';'

ns_at = SRC.index('namespace NSSystem')
lock_impl, _ = extract(SRC, 'namespace NSSystem',
                       ('CLockFileTemp::Save', 'CLockFileTemp::Load',
                        'CLockFileTemp::IsEqual', 'CLockFileTemp::Generate'),
                       after=ns_at, what='CLockFileTemp implementations')

check_path, _ = extract(SRC, 'CLockFileTemp CFileLocker::CheckLockFilePath',
                        ('.~lock.', 'IsEqual'), what='CFileLocker::CheckLockFilePath')

# Pre-#1362 revisions declare Load()/Save() without the type argument and have no
# IsLockFileExists helper.  Record which shape we got, so the expectations below
# can say what this revision is supposed to answer.
HAS_LOAD_TYPE = 'void CLockFileTemp::Load(int type)' in lock_impl
# The pre-fix text also mentions F_WRLCK - in the broken comparison
# `F_WRLCK == (_lock.l_type & F_WRLCK)` on a structure it never filled in.  What
# only the fixed text has is the ASSIGNMENT of F_WRLCK into the request, and the
# errno names a sharing violation arrives as.
HAS_GETLK_FIX = ('_lock.l_type   = F_WRLCK;' in fn_islocked) and ('ETXTBSY' in fn_islocked)
FIXED = HAS_GETLK_FIX

PROGRAM = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <set>
#include <map>
#include <sstream>
#include <iomanip>
#include <chrono>
#include <ctime>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <limits.h>
#include <sys/wait.h>
#include <sys/stat.h>

typedef unsigned char BYTE;
typedef unsigned long DWORD;
#ifndef HOST_NAME_MAX
#define HOST_NAME_MAX 255
#endif

static std::string to_utf8(const std::wstring &w)
{ std::string s; for (size_t i = 0; i < w.size(); ++i) s += (char)w[i]; return s; }
static std::wstring to_wide(const std::string &s)
{ std::wstring w; for (size_t i = 0; i < s.size(); ++i) w += (wchar_t)(unsigned char)s[i]; return w; }
#define U_TO_UTF8(x) to_utf8(x)
#define UTF8_TO_U(x) to_wide(x)

/* ---- what this process claims to be.  Overridable so that "another user"
        can be produced without another account on the machine. ---------- */
static std::string  g_user   = "alice";
static std::wstring g_appdir = L"/Users/alice/Library/Application Support/RationDocs";

namespace NSSystemUtils {
    static std::string  GetEnvVariableA(const std::wstring &) { return g_user; }
    static std::wstring GetAppDataDir() { return g_appdir; }
}
namespace NSStringUtils {
    static void string_replaceA(std::string &s, const std::string &from, const std::string &to)
    { size_t at = 0; while (std::string::npos != (at = s.find(from, at)))
        { s.replace(at, from.size(), to); at += to.size(); } }
    static void string_replace(std::wstring &s, const std::wstring &from, const std::wstring &to)
    { size_t at = 0; while (std::wstring::npos != (at = s.find(from, at)))
        { s.replace(at, from.size(), to); at += to.size(); } }
}

/* ---- NSFile, over the real filesystem ---------------------------------- */
namespace NSFile {
    struct CFileBinary {
        static bool Exists(const std::wstring &p)
        { struct stat st; return 0 == stat(to_utf8(p).c_str(), &st); }
        static bool Remove(const std::wstring &p)
        { return 0 == unlink(to_utf8(p).c_str()); }
        static bool ReadAllTextUtf8A(const std::wstring &p, std::string &out)
        {
            FILE *f = fopen(to_utf8(p).c_str(), "rb");
            if (!f) return false;
            char buf[8192]; size_t n = fread(buf, 1, sizeof(buf), f); fclose(f);
            out.assign(buf, n); return true;
        }
        bool CreateFile(const std::wstring &p)
        { m_f = fopen(to_utf8(p).c_str(), "wb"); return m_f != NULL; }
        bool WriteFile(BYTE *d, DWORD n)
        { return m_f && fwrite(d, 1, n, m_f) == n; }
        bool CloseFile() { if (m_f) fclose(m_f); m_f = NULL; return true; }
        FILE *m_f = NULL;
    };
    static std::wstring GetDirectoryName(const std::wstring &p)
    { size_t at = p.find_last_of(L'/'); return at == std::wstring::npos ? std::wstring(L".") : p.substr(0, at); }
    static std::wstring GetFileName(const std::wstring &p)
    { size_t at = p.find_last_of(L'/'); return at == std::wstring::npos ? p : p.substr(at + 1); }
}

/* ---- bookkeeping only; no verdict reads it ----------------------------- */
class CHandlesMonitor {
    std::set<std::wstring> m_h;
public:
    void Add(const std::wstring &f) { m_h.insert(f); }
    void Remove(const std::wstring &f) { m_h.erase(f); }
    bool IsExist(const std::wstring &f) { return m_h.count(f) != 0; }
    static CHandlesMonitor &Instance() { static CHandlesMonitor s; return s; }
};

namespace NSSystem
{
    enum class LockType { ltNone = 0x00, ltReadOnly = 0x01, ltLocked = 0x02, ltNosafe = 0x04 };

%(lock_decl)s
}

%(lock_impl)s

namespace NSSystem
{
    /* Stand-in for the two base classes.  Only the members the extracted
       functions touch, with the real DeleteLockFile. */
    class CFileLocker {
    public:
        std::wstring m_sFile;
        std::wstring m_sLockFilePath;
        int m_nDescriptor;
        CFileLocker(const std::wstring &f) : m_sFile(f), m_sLockFilePath(L""), m_nDescriptor(-1) {}
        virtual ~CFileLocker() {}
        static CLockFileTemp CheckLockFilePath(const std::wstring &file, const int &flags = 0);
        virtual void DeleteLockFile()
        {
            if (!m_sLockFilePath.empty())
                NSFile::CFileBinary::Remove(m_sLockFilePath);
            m_sLockFilePath = L"";
        }
    };

%(check_path)s

    /* The real CFileLockerFCNTL, its four functions lifted verbatim. */
    class CFileLockerFCNTL : public CFileLocker {
    public:
        CFileLockerFCNTL(const std::wstring &f) : CFileLocker(f) {}
        virtual ~CFileLockerFCNTL() { Unlock(); }

%(fn_lock)s

%(fn_unlock)s

    public:
%(fn_isuse)s

%(fn_islocked)s
    };
}

/* ======================================================================== */
using NSSystem::LockType;
using NSSystem::CFileLockerFCNTL;

static const char *name_of(LockType t)
{
    switch (t) {
    case LockType::ltNone:     return "ltNone (free - the editor will write)";
    case LockType::ltReadOnly: return "ltReadOnly";
    case LockType::ltLocked:   return "ltLocked";
    default:                   return "?";
    }
}

static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-66s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static pid_t spawn_lock_holder(const char *path, int *ready)
{
    int p[2];
    if (pipe(p) != 0) return -1;
    pid_t pid = fork();
    if (pid == 0) {
        close(p[0]);
        int fd = open(path, O_RDWR);
        struct flock l; memset(&l, 0, sizeof(l));
        l.l_type = F_WRLCK; l.l_whence = SEEK_SET; l.l_start = 0; l.l_len = 0;
        char c = (fd >= 0 && fcntl(fd, F_SETLK, &l) == 0) ? 'y' : 'n';
        ssize_t ig = write(p[1], &c, 1); (void)ig;
        for (;;) pause();
        _exit(0);
    }
    close(p[1]);
    char c = 'n';
    if (read(p[0], &c, 1) != 1) c = 'n';
    close(p[0]);
    *ready = (c == 'y');
    return pid;
}

static std::wstring marker_of(const std::wstring &doc)
{
    return NSFile::GetDirectoryName(doc) + L"/.~lock." + NSFile::GetFileName(doc) + L"#";
}

int main()
{
    const bool FIXED = %(fixed)s;

    printf("this host: F_RDLCK=%%d F_WRLCK=%%d F_UNLCK=%%d   revision under test: %%s\n",
           F_RDLCK, F_WRLCK, F_UNLCK, FIXED ? "current tree" : "BASELINE (pre-#1362)");

    char cpath[] = "/tmp/rd2135_XXXXXX";
    int fd = mkstemp(cpath);
    if (fd < 0) { printf("cannot make a temp file\n"); return 2; }
    ssize_t w = write(fd, "document body", 13); (void)w;
    close(fd);
    std::wstring doc = to_wide(cpath);
    unlink(to_utf8(marker_of(doc)).c_str());

    /* ---- A ----------------------------------------------------------- */
    printf("\nA - nobody holds the document\n");
    LockType a = CFileLockerFCNTL::IsLockedInternal(doc);
    printf("    verdict: %%s\n", name_of(a));
    check(a == LockType::ltNone, "an untouched document is free");

    /* ---- B ----------------------------------------------------------- */
    printf("\nB - ANOTHER PROCESS holds a real F_WRLCK (a second copy of the app)\n");
    int ready = 0;
    pid_t holder = spawn_lock_holder(cpath, &ready);
    if (holder <= 0 || !ready) {
        printf("  the child could not take the lock - cannot run this part\n");
        if (holder > 0) { kill(holder, SIGKILL); waitpid(holder, NULL, 0); }
        unlink(cpath);
        return 2;
    }
    LockType b = CFileLockerFCNTL::IsLockedInternal(doc);
    printf("    verdict: %%s\n", name_of(b));
    check(b == LockType::ltLocked,
          "a second process is refused - it opens read-only");
    kill(holder, SIGKILL);
    waitpid(holder, NULL, 0);

    /* ---- C ----------------------------------------------------------- */
    printf("\nC - THIS PROCESS holds it, via the real CFileLockerFCNTL::Lock()\n");
    {
        CFileLockerFCNTL owner(doc);
        bool locked = owner.Lock();
        bool marker = NSFile::CFileBinary::Exists(marker_of(doc));
        printf("    Lock() returned %%s; .~lock marker on disk: %%s\n",
               locked ? "true" : "false", marker ? "yes" : "no");
        check(marker, "the real Lock() did write the cooperative marker");

        LockType c = CFileLockerFCNTL::IsLockedInternal(doc);
        printf("    the SAME process now asks IsLocked: %%s\n", name_of(c));
        check(c == LockType::ltNone,
              "a second view in the same process is told the file is FREE");

        /* And the byte-range lock can be taken a second time from here. */
        int second = open(cpath, O_WRONLY);
        struct flock l2; memset(&l2, 0, sizeof(l2));
        l2.l_type = F_WRLCK; l2.l_whence = SEEK_SET; l2.l_start = 0; l2.l_len = 0;
        int took = fcntl(second, F_SETLK, &l2);
        printf("    and a second F_WRLCK from this process: %%s\n",
               took == 0 ? "granted" : "refused");
        check(took == 0,
              "POSIX grants the owner the lock again - no self-protection at all");
        close(second);
    }

    /* ---- D ----------------------------------------------------------- */
    printf("\nD - the cooperative .~lock marker is keyed to the person, not the process\n");
    {
        std::wstring mk = marker_of(doc);
        unlink(to_utf8(mk).c_str());

        /* Somebody else's marker, written by the real CLockFileTemp. */
        g_user = "bob";
        g_appdir = L"/Users/bob/Library/Application Support/RationDocs";
        NSSystem::CLockFileTemp foreign(mk);
        foreign.Generate();
        foreign.Save(%(save_arg)s);
        g_user = "alice";
        g_appdir = L"/Users/alice/Library/Application Support/RationDocs";

        LockType d1 = CFileLockerFCNTL::IsLockedInternal(doc);
        printf("    another user's marker is lying there: %%s\n", name_of(d1));
        check(d1 == LockType::ltLocked, "another user's marker blocks");

        /* Our own stale marker - crash residue. */
        unlink(to_utf8(mk).c_str());
        NSSystem::CLockFileTemp mine(mk);
        mine.Generate();
        mine.Save(%(save_arg)s);
        LockType d2 = CFileLockerFCNTL::IsLockedInternal(doc);
        printf("    OUR OWN stale marker is lying there:   %%s\n", name_of(d2));
        check(d2 == LockType::ltNone,
              "our own stale marker does not wedge the document");
        unlink(to_utf8(mk).c_str());
    }

    unlink(cpath);
    unlink(to_utf8(marker_of(doc)).c_str());

    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

src = PROGRAM % {
    'lock_decl': lock_decl,
    'lock_impl': lock_impl,
    'check_path': check_path,
    'fn_lock': fn_lock,
    'fn_unlock': fn_unlock,
    'fn_isuse': fn_isuse,
    'fn_islocked': fn_islocked,
    'fixed': 'true' if FIXED else 'false',
    'save_arg': '0' if HAS_LOAD_TYPE else '',
}

out = tempfile.mkdtemp(prefix='rd2135_')
cpp = os.path.join(out, 'main.cpp')
with open(cpp, 'w', encoding='utf-8') as f:
    f.write(src)

binp = os.path.join(out, 'run')
cc = subprocess.run(['c++', '-std=c++14', '-D_LINUX', '-D_MAC', '-o', binp, cpp],
                    capture_output=True, text=True)
if cc.returncode != 0:
    sys.stderr.write(cc.stdout + cc.stderr)
    sys.stderr.write('\ncompilation of the extracted source failed: %s\n' % cpp)
    raise SystemExit(2)

r = subprocess.run([binp])
print('\n(extracted source: %s)' % cpp)
raise SystemExit(r.returncode)
