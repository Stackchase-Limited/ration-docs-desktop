#!/usr/bin/env python3
"""
#1362 - "Desktop Editors don't lock files for editing on samba shares, can corrupt
files."  Two users open the same document on a network share, neither is warned,
both save, and one of them loses the work.

The cooperative marker .~lock.<name># exists for exactly this, and #2383 already
made sure it is WRITTEN on a share even when the byte-range lock is refused.  What
this test is about is the other half: the marker, and the lock, being READ.

Three defects on that read path, all of them ending in "the file is free":

  1. CFileLockerFCNTL::IsLockedInternal probes the lock with a flock structure that
     has only been memset to zero.  F_GETLK takes the lock you WANT as input and
     overwrites it with the conflicting one; l_type == 0 is F_RDLCK on Linux - the
     wrong question, since we are about to write - and on macOS 0 is not a lock
     type at all, so fcntl fails with EINVAL and leaves the structure alone.  The
     return value was never checked, so the untouched structure was read as "no
     lock".  macOS ships this locker (filelocker.cpp:1030-1042 sends _MAC to
     CFileLockerFCNTL), so PART 1 below reproduces it for real on this host, with
     a real child process holding a real fcntl lock.

  2. The same function returned LockType::ltNone the moment open() failed.  On a
     samba share that is precisely the peer we needed to detect: CFileLockerWin
     opens the document with FILE_SHARE_READ, which denies writers, the server
     answers sharing violation, and the CIFS client surfaces it as EBUSY (SMB2),
     ETXTBSY (SMB1) or EACCES.  Worse, the early return jumped over the .~lock
     check below it, so #2383's marker was cancelled out in the one case it was
     written for.  PART 2, against stubbed syscalls - a CIFS mount cannot be
     exercised here.

  3. On a gvfs address (smb://server/share/...) the marker was write-only.
     CLockFileTemp::Save(1) creates it through GIO, which understands such an
     address; CheckLockFilePath asked NSFile::CFileBinary::Exists, which is fopen,
     and CLockFileTemp::Load read it with fopen too.  fopen cannot open
     "smb://..." under any permissions, so the answer was always "there is no
     marker" - every editor in turn decided the document was free.  PART 3 runs a
     real round trip through the real CLockFileTemp and the real CheckLockFilePath
     with the transport stubbed; the premise that fopen refuses the address is
     MEASURED on this host rather than asserted.

  BASELINE=1 re-reads both files from git HEAD, where all three must FAIL.

What is NOT claimed: no samba share, CIFS mount or gvfs backend was mounted.  Part
1 is executed for real; parts 2 and 3 drive the real shipped functions against
stubs that model the mount, and the stubs are described where they are defined.
"""
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
HDR = 'ChromiumBasedEditors/lib/src/filelocker.h'
# Pinned to a SHA, not to HEAD.  679ebd74 is the commit that landed this fix, so
# its parent 6cd9fdd6 is the last tree that still has all three defects.  Left on
# HEAD this baseline stopped differing the moment the fix was committed: BASELINE=1
# then re-reads the FIXED file, every assertion passes, and the run reports success
# while testing nothing at all.  Verified: with 'HEAD' this script exits 0 under
# BASELINE=1; with the SHA below it exits 1, as a baseline must.
BASE_REF = os.environ.get('BASE_REF', '6cd9fdd654706f281a00ac2f9036367dcd7ed5af')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


SRC = read(CPP)
HEAD = read(HDR)


def brace_match(text, start):
    """Return text[start:end] where end closes the first '{' at or after start."""
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
        raise SystemExit('%r not found in the source - the extractor needs updating'
                         % (what or anchor))
    body = brace_match(text, at)
    for n in needles:
        if n not in body:
            raise SystemExit('extracted %r is missing %r - wrong block?'
                             % (what or anchor, n))
    return body, at


# --------------------------------------------------------------------------
# The three blocks of real source this test compiles.
# --------------------------------------------------------------------------

# (a) CFileLockerFCNTL::IsLockedInternal - inside its own class, because three
#     other classes in this file define a function of the same name.
cls_fcntl, cls_at = extract(SRC, 'class CFileLockerFCNTL', ('F_SETLK',),
                            what='class CFileLockerFCNTL')
is_locked, _ = extract(cls_fcntl, 'static LockType IsLockedInternal',
                       ('access(', 'open(', 'F_GETLK', 'CheckLockFilePath'),
                       what='CFileLockerFCNTL::IsLockedInternal')

# (b) the CLockFileTemp class declaration and its whole implementation block.
lock_decl, _ = extract(HEAD, 'class CLockFileTemp', ('Generate', 'Save', 'Load', 'IsEqual'),
                       what='class CLockFileTemp (header)')
lock_decl += ';'
ns_at = SRC.index('namespace NSSystem')
lock_impl, _ = extract(SRC, 'namespace NSSystem', ('CLockFileTemp::Save', 'CLockFileTemp::Load',
                                                   'CLockFileTemp::IsEqual', 'CLockFileTemp::Generate'),
                       after=ns_at, what='CLockFileTemp implementations')

# (c) CheckLockFilePath, with the helper the fix introduced beside it.
check_path, _ = extract(SRC, 'CLockFileTemp CFileLocker::CheckLockFilePath',
                        ('.~lock.', 'IsEqual'), what='CFileLocker::CheckLockFilePath')
m = re.search(r'^\tstatic bool IsLockFileExists\(', SRC, re.M)
if m:
    exists_helper, _ = extract(SRC, SRC[m.start():m.end()], ('g_file_query_exists',),
                               what='IsLockFileExists')
    HAS_EXISTS_HELPER = True
    # It lives in the same namespace block as CLockFileTemp, which is already being
    # lifted whole - so emitting it a second time would redefine it.
    if exists_helper in lock_impl:
        exists_helper = '/* IsLockFileExists comes in with the CLockFileTemp block above */'
else:
    exists_helper = '/* this revision has no IsLockFileExists - see the docstring */'
    HAS_EXISTS_HELPER = False

# Which shape of the fix is present, for the harness to expect the right answers.
# The fix names the errno values a sharing violation arrives as; the old text had
# nothing at all between the failed open() and the flock structure.
HAS_OPEN_FAIL = 'ETXTBSY' in is_locked
HAS_GETLK_FIX = '_lock.l_type   = F_WRLCK;' in is_locked
HAS_LOAD_TYPE = 'void CLockFileTemp::Load(int type)' in lock_impl

# --------------------------------------------------------------------------
# PART 1 + 2 harness: IsLockedInternal, twice - once over the real syscalls of
# this host, once over fakes that model a CIFS mount.
# --------------------------------------------------------------------------
H12 = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdlib.h>
#include <signal.h>
#include <sys/wait.h>
#include <sys/stat.h>

enum class LockType { ltNone = 0x00, ltReadOnly = 0x01, ltLocked = 0x02, ltNosafe = 0x04 };

static const char *name_of(LockType t)
{
    switch (t) {
    case LockType::ltNone:     return "ltNone (free - the editor will write)";
    case LockType::ltReadOnly: return "ltReadOnly";
    case LockType::ltLocked:   return "ltLocked";
    default:                   return "?";
    }
}

static std::string to_utf8(const std::wstring &w)
{
    std::string s;
    for (size_t i = 0; i < w.size(); ++i) s += (char)w[i];   /* ASCII paths only here */
    return s;
}
#define U_TO_UTF8(x) to_utf8(x)

/* Only the marker's verdict matters to IsLockedInternal: an empty path means
   "somebody else's marker is lying there", a non-empty one means "free". */
struct CLockFileTemp {
    std::wstring m_p;
    CLockFileTemp(const std::wstring &p) : m_p(p) {}
    std::wstring GetPath() { return m_p; }
};

/* ======================= PART 1: the real syscalls ======================= */
namespace over_real_syscalls {
    static bool g_foreignMarker = false;
    static bool IsUseLockFile() { return true; }
    static CLockFileTemp CheckLockFilePath(const std::wstring &f)
    { return g_foreignMarker ? CLockFileTemp(L"") : CLockFileTemp(f + L".marker"); }

%(is_locked_1)s
}

/* ====================== PART 2: a modelled CIFS mount ====================
   open() on a share whose file a Windows peer holds with FILE_SHARE_READ fails
   with a sharing violation; the kernel's CIFS client maps that to EBUSY on SMB2
   and ETXTBSY on SMB1, and some paths report EACCES.  F_GETLK on a mount with
   nobrl, or against a server without byte-range locking, fails outright - the
   flock structure comes back untouched, which is an absence of an answer and not
   an answer of "no lock".                                                    */
namespace over_cifs {
    static int  g_openErrno      = 0;      /* non-zero: open() refuses with this */
    static bool g_accessWritable = true;   /* what the permission bits say       */
    static bool g_accessReadable = true;   /* ditto, for reading                 */
    static bool g_foreignMarker  = false;  /* somebody else's .~lock is there    */
    static int  g_getlkErrno     = 0;      /* non-zero: F_GETLK fails with this  */
    static int  g_conflict       = 0;      /* 0 none, else the conflicting type  */
    static bool g_getlkWasAsked  = false;
    static bool g_markerWasAsked = false;

    static bool IsUseLockFile() { return true; }
    static CLockFileTemp CheckLockFilePath(const std::wstring &f)
    {
        g_markerWasAsked = true;
        return g_foreignMarker ? CLockFileTemp(L"") : CLockFileTemp(f + L".marker");
    }

    static int fake_access(const char *, int mode)
    {
        if (mode == W_OK) return g_accessWritable ? 0 : -1;
        if (mode == R_OK) return g_accessReadable ? 0 : -1;
        return 0;
    }
    static int fake_open(const char *, int)
    {
        if (g_openErrno) { errno = g_openErrno; return -1; }
        return 77;                                 /* a descriptor we never use */
    }
    static int fake_fcntl(int, int cmd, struct flock *l)
    {
        g_getlkWasAsked = true;
        if (cmd != F_GETLK) { errno = EINVAL; return -1; }
        /* A real kernel rejects a request whose l_type is not a lock type - which
           is what a memset-zeroed structure hands it on this host - and does not
           touch the caller's structure.  Measured, see PART 1. */
        if (l->l_type != F_RDLCK && l->l_type != F_WRLCK) { errno = EINVAL; return -1; }
        if (g_getlkErrno) { errno = g_getlkErrno; return -1; }
        l->l_type = g_conflict ? g_conflict : F_UNLCK;
        return 0;
    }
    static int fake_close(int) { return 0; }

    #define access fake_access
    #define open   fake_open
    #define fcntl  fake_fcntl
    #define close  fake_close

%(is_locked_2)s

    #undef access
    #undef open
    #undef fcntl
    #undef close
}

/* ======================================================================== */
static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-64s %%s\n", what, ok ? "ok" : "FAILED");
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
        char c = (fcntl(fd, F_SETLK, &l) == 0) ? 'y' : 'n';
        ssize_t ignored = write(p[1], &c, 1); (void)ignored;
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

int main()
{
    const bool GETLK_FIXED = %(getlk_fixed)s;

    printf("this host: F_RDLCK=%%d F_WRLCK=%%d F_UNLCK=%%d\n", F_RDLCK, F_WRLCK, F_UNLCK);

    /* ---------------- PART 1: real lock, real child, real fcntl ---------- */
    printf("\nPART 1 - a real fcntl write lock held by another process (executed here)\n");
    char path[] = "/tmp/rd1362_XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0) { printf("  cannot make a temp file\n"); return 2; }
    ssize_t w = write(fd, "document", 8); (void)w;
    close(fd);

    int ready = 0;
    pid_t holder = spawn_lock_holder(path, &ready);
    if (holder <= 0 || !ready) {
        printf("  the child could not take the lock - cannot run this part\n");
        if (holder > 0) { kill(holder, SIGKILL); waitpid(holder, NULL, 0); }
        unlink(path);
        return 2;
    }

    std::wstring wpath;
    for (const char *q = path; *q; ++q) wpath += (wchar_t)*q;

    over_real_syscalls::g_foreignMarker = false;     /* marker absent: fcntl decides */
    LockType got = over_real_syscalls::IsLockedInternal(wpath);
    printf("    another process holds F_WRLCK on the whole file; we report: %%s\n", name_of(got));
    check(got == LockType::ltLocked,
          "a write lock held by another process is seen");

    kill(holder, SIGKILL);
    waitpid(holder, NULL, 0);

    over_real_syscalls::g_foreignMarker = false;
    got = over_real_syscalls::IsLockedInternal(wpath);
    printf("    nobody holds it now;                        we report: %%s\n", name_of(got));
    check(got == LockType::ltNone, "an unlocked file is still reported free");
    unlink(path);

    if (!GETLK_FIXED)
        printf("\n  F_GETLK is asked with a memset-zeroed flock.  l_type 0 is not a lock\n"
               "  type on this host, so fcntl answers EINVAL, leaves the structure alone,\n"
               "  and the untouched structure is read as 'no lock' (#1362).\n");

    /* ---------------- PART 2: the samba peer ----------------------------- */
    printf("\nPART 2 - a peer on a samba share, over modelled CIFS syscalls\n");

    struct Case {
        const char *why;
        int openErrno; bool accessWritable; bool foreignMarker; int getlkErrno; int conflict;
        LockType want;
        bool wantMarkerAsked;
    };
    /* What every one of these must never be is ltNone: that is the editor being
       told it may write over somebody else's open document. */
    const LockType L = LockType::ltLocked;
    Case cases[] = {
      { "SMB2 peer holds it (open EBUSY), no marker",       EBUSY,   true,  false, 0, 0, L, false },
      { "SMB1 peer holds it (open ETXTBSY), no marker",     ETXTBSY, true,  false, 0, 0, L, false },
      { "peer holds it (open EACCES), no marker",           EACCES,  true,  false, 0, 0, L, false },
      { "open EBUSY and somebody's .~lock is there",        EBUSY,   true,  true,  0, 0, L, false },
      { "nobrl mount: F_GETLK fails, .~lock is there",      0,       true,  true,  ENOLCK, 0, L, true },
      { "no locking at all: F_GETLK ENOTSUP, .~lock there", 0,       true,  true,  ENOTSUP, 0, L, true },
      { "peer's byte-range lock is visible",                0,       true,  false, 0, F_WRLCK, L, false },
    };

    for (size_t i = 0; i < sizeof(cases)/sizeof(cases[0]); ++i) {
        over_cifs::g_openErrno      = cases[i].openErrno;
        over_cifs::g_accessWritable = cases[i].accessWritable;
        over_cifs::g_foreignMarker  = cases[i].foreignMarker;
        over_cifs::g_getlkErrno     = cases[i].getlkErrno;
        over_cifs::g_conflict       = cases[i].conflict;
        over_cifs::g_getlkWasAsked  = false;
        over_cifs::g_markerWasAsked = false;

        LockType r = over_cifs::IsLockedInternal(L"/mnt/share/doc.docx");
        bool ok = (r == cases[i].want);
        printf("  %%-52s -> %%-40s %%s\n", cases[i].why, name_of(r), ok ? "ok" : "FAILED");
        if (!ok) failures++;
    }

    /* The marker is the whole point of #2383 and must not be skipped just because
       open() failed for a reason that is not itself a verdict. */
    over_cifs::g_openErrno = ENOENT; over_cifs::g_accessWritable = true;
    over_cifs::g_foreignMarker = true; over_cifs::g_getlkErrno = 0; over_cifs::g_conflict = 0;
    over_cifs::g_markerWasAsked = false;
    (void)over_cifs::IsLockedInternal(L"/mnt/share/doc.docx");
    check(over_cifs::g_markerWasAsked,
          "a failed open does not skip the .~lock check");

    /* Behaviour that must not change. */
    printf("\nunchanged behaviour\n");
    over_cifs::g_openErrno = 0; over_cifs::g_accessWritable = true;
    over_cifs::g_foreignMarker = false; over_cifs::g_getlkErrno = 0; over_cifs::g_conflict = 0;
    check(over_cifs::IsLockedInternal(L"/mnt/share/doc.docx") == LockType::ltNone,
          "a free file on a healthy mount is free");

    over_cifs::g_accessWritable = false;     /* readable, not writable */
    check(over_cifs::IsLockedInternal(L"/mnt/share/doc.docx") == LockType::ltReadOnly,
          "a read-only file is still ltReadOnly");

    /* Neither readable nor writable slips past the guard above and reaches open(),
       which is refused with EACCES - but that is our permissions, not a peer. */
    over_cifs::g_accessReadable = false;
    over_cifs::g_openErrno = EACCES;
    check(over_cifs::IsLockedInternal(L"/mnt/share/doc.docx") != LockType::ltLocked,
          "a file we may not touch at all is not called 'held by a peer'");
    over_cifs::g_accessReadable = true;
    over_cifs::g_openErrno = 0;
    over_cifs::g_accessWritable = true;

    over_cifs::g_openErrno = ENOENT;
    over_cifs::g_foreignMarker = true;
    check(over_cifs::IsLockedInternal(L"/mnt/share/gone.docx") == LockType::ltLocked,
          "a missing file still consults the marker");
    over_cifs::g_foreignMarker = false;
    check(over_cifs::IsLockedInternal(L"/mnt/share/gone.docx") == LockType::ltNone,
          "a missing file with no marker is free");

    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''

# --------------------------------------------------------------------------
# PART 3 harness: the marker round trip on a gvfs address.
# --------------------------------------------------------------------------
H3 = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <map>
#include <set>
#include <chrono>
#include <sstream>
#include <iomanip>
#include <ctime>
#include <unistd.h>
#include <limits.h>

typedef unsigned char BYTE;
typedef unsigned long DWORD;
#ifndef HOST_NAME_MAX
#define HOST_NAME_MAX 1000
#endif

static std::string to_utf8(const std::wstring &w)
{ std::string s; for (size_t i = 0; i < w.size(); ++i) s += (char)w[i]; return s; }
static std::wstring to_wide(const std::string &s)
{ std::wstring w; for (size_t i = 0; i < s.size(); ++i) w += (wchar_t)(unsigned char)s[i]; return w; }
#define U_TO_UTF8(x) to_utf8(x)
#define UTF8_TO_U(x) to_wide(x)

/* ---- what the process running this test really is ---------------------- */
static std::string g_user    = "alice";
static std::wstring g_appdir = L"/home/alice/.local/share/rationdocs";

namespace NSSystemUtils {
    static std::string  GetEnvVariableA(const std::wstring &) { return g_user; }
    static std::wstring GetAppDataDir() { return g_appdir; }
}
namespace NSStringUtils {
    static void string_replaceA(std::string &s, const std::string &from, const std::string &to)
    { size_t at = 0; while (std::string::npos != (at = s.find(from, at)))
        { s.replace(at, from.size(), to); at += to.size(); } }
}

/* ---- the share, as the two transports each see it ----------------------
   Left half: what really exists on the server, keyed by gvfs address.  The GIO
   calls below see it, because GIO speaks smb://.  fopen does not - and that is
   not modelled, it is MEASURED at the top of main() by calling the real fopen on
   a real smb:// address and showing it comes back NULL.                    */
static std::map<std::string, std::string> g_share;

namespace NSFile {
    struct CFileBinary {
        /* fopen.  A gvfs address is not a filesystem path, so it never opens one. */
        static bool Exists(const std::wstring &p)
        {
            std::string a = to_utf8(p);
            FILE *f = fopen(a.c_str(), "rb");
            if (!f) return false;
            fclose(f); return true;
        }
        static bool ReadAllTextUtf8A(const std::wstring &p, std::string &out)
        {
            std::string a = to_utf8(p);
            FILE *f = fopen(a.c_str(), "rb");
            if (!f) return false;
            char buf[4096]; size_t n = fread(buf, 1, sizeof(buf), f); fclose(f);
            out.assign(buf, n); return true;
        }
        bool CreateFile(const std::wstring &p) { m_p = to_utf8(p); m_open = true; return true; }
        bool WriteFile(BYTE *d, DWORD n) { if (!m_open) return false;
            g_share[m_p].assign((const char *)d, n); return true; }
        bool CloseFile() { m_open = false; return true; }
        std::string m_p; bool m_open = false;
    };
    static std::wstring GetDirectoryName(const std::wstring &p)
    { size_t at = p.find_last_of(L'/'); return at == std::wstring::npos ? std::wstring(L".") : p.substr(0, at); }
    static std::wstring GetFileName(const std::wstring &p)
    { size_t at = p.find_last_of(L'/'); return at == std::wstring::npos ? p : p.substr(at + 1); }
}

/* ---- GIO, reduced to the four calls this code makes --------------------
   A GFile here is just the address; g_file_* read and write g_share.  What is
   being tested is not GIO, it is whether the marker is read back through the
   same transport it was written through.                                   */
#define LOCKER_USE_GIO 1
typedef int gboolean;
typedef char gchar;
typedef size_t gsize;
#define TRUE 1
#define FALSE 0
#define G_FILE_CREATE_NONE 0
struct GError { int code; };
struct GFile { std::string uri; };
struct GOutputStream { std::string uri; };
typedef GOutputStream GFileOutputStream;
#define G_OUTPUT_STREAM(x) (x)
#define G_FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME "standard::display-name"
#define G_FILE_ATTRIBUTE_STANDARD_NAME "standard::name"
#define G_FILE_QUERY_INFO_NONE 0
struct GFileInfo { std::string name; };

static GFile *g_file_new_for_commandline_arg(const char *a) { GFile *f = new GFile; f->uri = a; return f; }
static void   g_object_unref(void *p) { (void)p; }
static void   g_error_free(GError *e) { delete e; }
static void   g_free(void *p) { free(p); }
static gboolean g_file_query_exists(GFile *f, void *) { return g_share.count(f->uri) ? TRUE : FALSE; }
static GFileOutputStream *g_file_create(GFile *f, int, void *, GError **err)
{
    if (g_share.count(f->uri)) { *err = new GError; (*err)->code = 1; return NULL; }   /* G_IO_ERROR_EXISTS */
    GOutputStream *s = new GOutputStream; s->uri = f->uri; g_share[f->uri] = ""; return s;
}
static gboolean g_output_stream_write_all(GOutputStream *s, const char *d, size_t n,
                                          gsize *written, void *, GError **)
{ g_share[s->uri].assign(d, n); *written = n; return TRUE; }
static gboolean g_output_stream_close(GOutputStream *, void *, void *) { return TRUE; }
static gboolean g_file_load_contents(GFile *f, void *, gchar **out, gsize *len, void *, GError **err)
{
    std::map<std::string, std::string>::iterator it = g_share.find(f->uri);
    if (it == g_share.end()) { *err = new GError; (*err)->code = 2; return FALSE; }
    *len = it->second.size();
    *out = (gchar *)malloc(*len + 1);
    memcpy(*out, it->second.data(), *len); (*out)[*len] = 0;
    return TRUE;
}
static GFileInfo *g_file_query_info(GFile *f, const char *, int, void *, GError **)
{ GFileInfo *i = new GFileInfo; size_t at = f->uri.find_last_of('/');
  i->name = at == std::string::npos ? f->uri : f->uri.substr(at + 1); return i; }
static const char *g_file_info_get_display_name(GFileInfo *i) { return i->name.c_str(); }
static GFile *g_file_new_for_path(const char *a) { return g_file_new_for_commandline_arg(a); }

/* ---- the real CLockFileTemp, declaration and implementation ------------ */
namespace NSSystem {
%(lock_decl)s
}
%(lock_impl)s

/* ---- the real CheckLockFilePath, on a stand-in for its class ----------- */
namespace NSSystem {
    class CFileLocker {
    public:
        std::wstring m_sFile;
        std::wstring m_sLockFilePath;
        static CLockFileTemp CheckLockFilePath(const std::wstring &file, const int &flags = 0);
    };

%(exists_helper)s

%(check_path)s
}

/* ======================================================================== */
static int failures = 0;
static void check(bool ok, const char *what)
{ printf("  %%-64s %%s\n", what, ok ? "ok" : "FAILED"); if (!ok) failures++; }

int main()
{
    const char *SHARE = "smb://fileserver/finance";
    const char *DOC   = "smb://fileserver/finance/budget.xlsx";
    (void)SHARE;

    /* The premise, measured rather than asserted. */
    FILE *probe = fopen("smb://fileserver/finance/.~lock.budget.xlsx#", "rb");
    printf("measured on this host: fopen(\"smb://fileserver/finance/.~lock.budget.xlsx#\")"
           " -> %%s\n", probe ? "opened" : "NULL");
    if (probe) { fclose(probe); printf("  premise broken - fopen opened a gvfs address\n"); return 2; }
    printf("  so any reader built on fopen cannot see a marker on a gvfs address.\n");

    /* --- user A, on her machine, opens the document ------------------- */
    g_user = "alice"; g_appdir = L"/home/alice/.local/share/rationdocs";
    NSSystem::CLockFileTemp a = NSSystem::CFileLocker::CheckLockFilePath(to_wide(DOC), 1);
    check(!a.GetPath().empty(), "user A finds the document free");
    a.Save(1);                                   /* the marker CFileLockerGIO writes */
    check(g_share.count(to_utf8(a.GetPath())) != 0,
          "user A's .~lock marker is on the share");
    printf("    marker at %%s\n      contents: %%s\n",
           to_utf8(a.GetPath()).c_str(), g_share[to_utf8(a.GetPath())].c_str());

    /* --- user B, another machine, opens the same document ------------- */
    g_user = "bob"; g_appdir = L"/home/bob/.local/share/rationdocs";
    NSSystem::CLockFileTemp b = NSSystem::CFileLocker::CheckLockFilePath(to_wide(DOC), 1);
    printf("    user B asks, and is told the document is %%s\n",
           b.GetPath().empty() ? "HELD by somebody else" : "free");
    check(b.GetPath().empty(),
          "user B is told somebody else holds it");

    /* --- and the same user in a second window is not locked out ------- */
    g_user = "alice"; g_appdir = L"/home/alice/.local/share/rationdocs";
    NSSystem::CLockFileTemp a2 = NSSystem::CFileLocker::CheckLockFilePath(to_wide(DOC), 1);
    check(!a2.GetPath().empty(), "user A's own marker does not lock user A out");

    /* --- a local path is unaffected by any of this -------------------- */
    g_share.clear();
    NSSystem::CLockFileTemp c = NSSystem::CFileLocker::CheckLockFilePath(L"/home/alice/doc.docx", 0);
    check(!c.GetPath().empty(), "a local path with no marker is still free");

    printf("\n%%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
'''


def build_and_run(name, source, keep=None):
    d = tempfile.mkdtemp(prefix='rd1362_')
    src = os.path.join(d, name + '.cpp')
    exe = os.path.join(d, name)
    with open(src, 'w') as f:
        f.write(source)
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-Wno-unused-function',
                        '-Wno-writable-strings', '-o', exe, src],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('%s did not compile (source kept at %s)' % (name, src))
    sys.stdout.flush()
    return subprocess.run([exe]).returncode


print('#1362 - locking a document on a samba share')
print('source: %s' % ('git %s (BASELINE)' % BASE_REF if BASELINE else 'working tree'))
print('host:   %s %s' % (platform.system(), platform.machine()))
print('=' * 74)

rc = 0

h12 = H12 % {
    'is_locked_1': is_locked,
    'is_locked_2': is_locked,
    'getlk_fixed': 'true' if HAS_GETLK_FIX else 'false',
}
rc |= build_and_run('islocked', h12)

print('\n' + '=' * 74)
print('PART 3 - the .~lock marker on a gvfs address (smb://)\n')
h3 = H3 % {
    'lock_decl': lock_decl,
    'lock_impl': lock_impl,
    'exists_helper': exists_helper,
    'check_path': check_path,
}
rc |= build_and_run('marker', h3)

print('\n' + '=' * 74)
if rc:
    if not HAS_GETLK_FIX:
        sys.stderr.write(
            'F_GETLK is asked with an uninitialised lock type, and its return value is\n'
            'ignored, so a lock held by another process is not seen (#1362).\n')
    if not HAS_OPEN_FAIL:
        sys.stderr.write(
            'IsLockedInternal returns ltNone as soon as open() fails, which is exactly\n'
            'what a samba peer holding the document looks like - and that early return\n'
            'also skips the .~lock check (#1362, defeating #2383).\n')
    if not HAS_EXISTS_HELPER or not HAS_LOAD_TYPE:
        sys.stderr.write(
            'The .~lock marker on a gvfs address is written through GIO and read with\n'
            'fopen, which cannot open such an address, so it is never read (#1362).\n')
    print('FAILED')
else:
    print('ok - a document held by somebody else on a share is reported held')
sys.exit(1 if rc else 0)
