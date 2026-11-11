#!/usr/bin/env python3
"""
#2000 - "Open/save from network share (samba/nfs/cloud)" - the save half: a
save to a share (or any volume) that fails part-way destroys the document.

Bug: on macOS and on Linux local paths (which includes kernel SMB/CIFS and NFS
mounts, /Volumes/<share> on macOS, FUSE volumes and gvfs's own FUSE paths
/run/user/<uid>/gvfs/...) CLocalFileLocker::SaveFile wrote the new document
over the old one in place, through the descriptor the locker holds: seek 0,
write, truncate, fsync.  Anything that breaks in between - share or quota full,
connection to the server dropped, file-size limit - leaves the old content
already overwritten and the new content incomplete; the user is told the save
failed, and the file on the share is neither version.  Measured by hand with
the real code (cp-tmp in the round's notes): a 4 MB HFS+ disk image, a macOS
smbfs mount and a Linux kernel CIFS mount of a 4 MB samba share - a 5 MB save
over a 1.5 MB document left the first 2-4 MB of the new file (on smbfs with
SaveFile reporting SUCCESS, because smbfs reports ENOSPC only in close(), which
the save never called; the server file had 800 KB of zeros).  A second defect
on Linux only: CFileLockerFCNTL took the kernel lock with F_SETLKW, which waits
for as long as another process (LibreOffice, a CIFS client elsewhere) holds a
lock - "Save as" over such a file, or opening it in that race, hung for ever.

Fix (desktop-sdk filelocker.cpp): StartWrite() opens a new hidden sibling
".~<name>.<8 hex>.tmp" (O_EXCL) next to the real file (symlinks resolved);
the save is written there; Truncate() commits: ftruncate, fsync, the
document's mode/owner (and xattrs/ACL on macOS) onto the temp, close() WITH
its error checked, size verified, the document's descriptor released, rename()
over the document, the document reopened and re-locked.  Any failure before
the rename deletes the temp and leaves the document untouched; Flush() then
reports the save failed.  rename() failing with EXDEV (union file systems such
as mergerfs) falls back to copy + fsync + close + byte-for-byte verify; the
temp is deleted only if the copy verified, otherwise kept and its path logged.
A folder where files cannot be created (EACCES/EPERM) keeps the old in-place
write, but its close() error is now checked too.  The kernel lock uses F_SETLK
on Linux as it already did on macOS; a refused lock does not stop the save.

What runs here: the WHOLE real filelocker.cpp/.h and the real CLocalFileLocker
class (cut out of applicationmanager_p.h by brace matching), compiled with the
real core/DesktopEditor/common sources; nothing of the logic is copied.
Faults are real where possible:
  A  RLIMIT_FSIZE (a real kernel write limit, EFBIG) stops a save part-way:
     the document must keep its old content and SaveFile must answer false.
  B  close() of the written file reports ENOSPC, as smbfs does (injected by
     wrapping close() in filelocker.cpp; the real close runs first): the save
     must be reported failed and the document must be the old one.
  C  Linux only: another process holds an fcntl write lock on the document;
     opening it with CLocalFileLocker must not hang (5 s limit) and a save
     must still land.
  Guards (pass on baseline unless noted): normal saves; mode 0640 kept; after
  a save the document is locked again (another process's CFileLocker::IsLocked
  says ltLocked - this one FAILS on baseline too: WriteFile's
  CFileBinary::Exists() fopen/fclose'd the document, and closing any
  descriptor drops the process's fcntl locks); a symlinked document stays a symlink and its target gets the
  content; rename() refused with EXDEV -> copied, verified, no temp left;
  rename() refused with EIO -> document untouched, save false (FAILS on
  baseline too: it writes in place, there is no rename to refuse); read-only
  document refused; a document held by another user's .~lock marker refused;
  folder without create rights -> in-place save still works; no ".~*.tmp"
  is ever left behind by these saves.

BASELINE=1 reads the three sources from BASE_REF (the parent of the fix
commit); A and B (and C on Linux) must FAIL there.  The integrator re-pins
BASE_REF after cherry-picking.  RD_REPO = desktop-sdk checkout (default
../../desktop-sdk), RD_CORE = core checkout (default ../../core).

NOT claimed / not verified: Windows (CFileLockerWin is untouched and still
writes in place, with CopyFileW as its fallback); the GVFS smb:// / sftp://
URI path (CFileLockerGIO, #2480 - unchanged); the Flatpak document portal
(/run/user/<uid>/doc/...) - xdg-document-portal was not available to test
whether it lets a sibling temp be created and renamed (if it refuses with
EACCES the in-place fallback is used); the Flatpak dialog not listing gvfs
mounts (the issue's own report) is a sandbox permission of the flathub
manifest, not in our tree.  A replace needs free space for both copies: a
save that fitted in place on an almost full share now fails (and says so).
The document becomes a new file: hard links to it are broken, and its owner
becomes the saver when chown is not permitted (mode and group are kept).
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk')))
CORE = os.path.abspath(os.environ.get('RD_CORE', os.path.join(HERE, '..', '..', 'core')))
CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
HDR = 'ChromiumBasedEditors/lib/src/filelocker.h'
APP = 'ChromiumBasedEditors/lib/src/applicationmanager_p.h'
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '5eaf9b64^')
BASELINE = bool(os.environ.get('BASELINE'))

COMMON = ['File.cpp', 'Directory.cpp', 'SystemUtils.cpp', 'StringBuilder.cpp',
          'StringExt.cpp', 'Path.cpp', 'Base64.cpp']


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


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


def extract(text, anchor, needles=()):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    body = brace_match(text, at)
    for n in needles:
        if n not in body:
            raise SystemExit('extracted %r is missing %r - wrong block?' % (anchor, n))
    return body


# Force-included into filelocker.cpp only, after the system headers: the calls the
# locker makes to close() and rename() go through the test's wrappers.
INJECT = r'''
#include <stdio.h>
#include <cstdio>   // libstdc++'s <cstdio> #undefs rename: include it before the #define
#include <unistd.h>
#include <sys/stat.h>
#ifdef __cplusplus
extern "C" {
#endif
int rd_close(int fd);
int rd_rename(const char* a, const char* b);
#ifdef __cplusplus
}
#endif
#define close rd_close
#define rename rd_rename
'''

HARNESS = r'''
#include "sdk/ChromiumBasedEditors/lib/src/filelocker.h"
#include "core/DesktopEditor/common/File.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <limits.h>

namespace NSSystem {
LOCAL_FILE_LOCKER
}
using namespace NSSystem;

/* ---- fault injection (see INJECT) ---- */
static std::string g_closeFailDir;      // fail the next close() of a non-empty file here
static int g_renameErrno = 0;           // rename() of a temp onto a document fails with this
static std::string fd_path(int fd)
{
    char buf[PATH_MAX + 1] = {0};
#ifdef __APPLE__
    if (-1 == fcntl(fd, F_GETPATH, buf)) return "";
#else
    char link[64]; snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
    ssize_t n = readlink(link, buf, PATH_MAX); if (n <= 0) return ""; buf[n] = 0;
#endif
    return buf;
}
extern "C" int rd_close(int fd)
{
    std::string path;
    struct stat st;
    if (!g_closeFailDir.empty() && 0 == fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_size > 0)
        path = fd_path(fd);
    int r = close(fd);
    if (!path.empty() && 0 == path.compare(0, g_closeFailDir.size(), g_closeFailDir) &&
        std::string::npos == path.find(".~lock.")) {
        g_closeFailDir.clear();
        errno = ENOSPC;            // what smbfs answers at close() on a full share
        return -1;
    }
    return r;
}
extern "C" int rd_rename(const char* a, const char* b)
{
    if (g_renameErrno && strstr(a, "/.~")) { errno = g_renameErrno; return -1; }
    return rename(a, b);
}

static int failures = 0;
static void check(bool ok, const char* what)
{
    printf("    %-70s %s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}
static std::wstring W(const std::string& s) { return UTF8_TO_U(s); }
static void put(const std::string& p, const std::string& s)
{ FILE* f = fopen(p.c_str(), "wb"); fwrite(s.data(), 1, s.size(), f); fclose(f); }
static std::string get(const std::string& p)
{ std::string s; FILE* f = fopen(p.c_str(), "rb"); if (!f) return "<missing>";
  char b[4096]; size_t n; while ((n = fread(b, 1, sizeof b, f)) > 0) s.append(b, n); fclose(f); return s; }
static std::vector<std::string> temps(const std::string& dir)
{
    std::vector<std::string> r; DIR* d = opendir(dir.c_str()); if (!d) return r;
    while (struct dirent* e = readdir(d)) {
        std::string n = e->d_name;
        if (n.size() > 4 && n.compare(0, 2, ".~") == 0 && n.compare(n.size() - 4, 4, ".tmp") == 0) r.push_back(n);
    }
    closedir(d); return r;
}
static std::string fresh(const std::string& root, const char* name)
{ std::string d = root + "/" + name; mkdir(d.c_str(), 0755); return d; }

static const std::string OLDV(1000, 'O');
static const std::string NEWV(3000, 'N');

static int islocked_in_child(const std::string& p)
{
    pid_t pid = fork();
    if (pid == 0) _exit((int)CFileLocker::IsLocked(W(p)));
    int st = 0; waitpid(pid, &st, 0);
    return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}

int main(int argc, char** argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    signal(SIGXFSZ, SIG_IGN);
    char rootReal[PATH_MAX];
    std::string root = realpath(argv[1], rootReal) ? rootReal : argv[1];   // F_GETPATH answers /private/var/...
    std::string src = root + "/new.bin";
    put(src, NEWV);

    {
        printf("  A  a save stopped part-way by a real write limit (RLIMIT_FSIZE, EFBIG)\n");
        std::string dir = fresh(root, "a"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        bool r;
        {
            CLocalFileLocker l(W(doc));
            struct rlimit old, lim; getrlimit(RLIMIT_FSIZE, &old);
            lim = old; lim.rlim_cur = 2000;
            setrlimit(RLIMIT_FSIZE, &lim);
            r = l.SaveFile(W(src));
            setrlimit(RLIMIT_FSIZE, &old);
        }
        std::string now = get(doc);
        printf("    info  SaveFile: %s; document: %zu bytes, %s\n", r ? "true" : "false", now.size(),
               now == OLDV ? "the old content" : now == NEWV ? "the new content" : "NEITHER version");
        check(!r, "the save is reported failed");
        check(now == OLDV, "the document still holds its old content");
        check(temps(dir).empty(), "no temp file left");
    }
    {
        printf("  B  close() reports ENOSPC after the write, as smbfs does on a full share\n");
        std::string dir = fresh(root, "b"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        bool r;
        {
            CLocalFileLocker l(W(doc));
            g_closeFailDir = dir + "/";
            r = l.SaveFile(W(src));
            g_closeFailDir.clear();
        }
        std::string now = get(doc);
        printf("    info  SaveFile: %s; document: %s\n", r ? "true" : "false",
               now == OLDV ? "old" : now == NEWV ? "new" : "OTHER");
        check(!r, "a save the file system rejected is not reported as saved");
        check(now == OLDV, "the document still holds its old content");
        check(temps(dir).empty(), "no temp file left");
    }
#ifndef __APPLE__
    {
        printf("  C  another process holds an fcntl write lock on the document (Linux)\n");
        std::string dir = fresh(root, "c"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        int p[2]; if (pipe(p)) {}
        pid_t holder = fork();
        if (holder == 0) {
            int fd = open(doc.c_str(), O_RDWR);
            struct flock fl; memset(&fl, 0, sizeof fl); fl.l_type = F_WRLCK; fl.l_whence = SEEK_SET;
            fcntl(fd, F_SETLK, &fl);
            if (write(p[1], "x", 1)) {}
            pause();
            _exit(0);
        }
        char c; if (read(p[0], &c, 1)) {}
        pid_t opener = fork();
        if (opener == 0) {
            alarm(5);
            CLocalFileLocker l(W(doc));
            _exit(l.SaveFile(W(src)) ? 0 : 1);
        }
        int st = 0; waitpid(opener, &st, 0);
        kill(holder, SIGKILL); waitpid(holder, NULL, 0);
        bool hung = WIFSIGNALED(st) && WTERMSIG(st) == SIGALRM;
        printf("    info  %s\n", hung ? "open hung (killed after 5 s)" : "open returned");
        check(!hung, "opening the document does not wait for the other process's lock");
        check(!hung && WIFEXITED(st) && WEXITSTATUS(st) == 0 && get(doc) == NEWV, "and a save still lands");
        unlink((dir + "/.~lock.Report.docx#").c_str());
    }
#endif
    printf("  guards\n");
    {
        std::string dir = fresh(root, "g1"), doc = dir + "/Report.docx";
        put(doc, OLDV); chmod(doc.c_str(), 0640);
        CLocalFileLocker l(W(doc));
        bool r1 = l.SaveFile(W(src));
        put(root + "/small.bin", "small");
        bool r2 = l.SaveFile(W(root + "/small.bin"));
        // asked before this process opens the document itself: closing any descriptor of
        // a file drops the process's fcntl locks on it (POSIX), so get() would unlock it
        int locked = islocked_in_child(doc);
        struct stat st; stat(doc.c_str(), &st);
        check(r1 && r2 && get(doc) == "small", "two saves in a row land");
        check((st.st_mode & 07777) == 0640, "the document's mode 0640 is kept");
        check(locked == (int)LockType::ltLocked, "after a save the document is still locked for other processes");
        check(temps(dir).empty(), "no temp file left");
    }
    {
        std::string dir = fresh(root, "g2"), real = fresh(root, "g2real") + "/Real.docx", link = dir + "/Report.docx";
        put(real, OLDV); symlink(real.c_str(), link.c_str());
        bool r;
        { CLocalFileLocker l(W(link)); r = l.SaveFile(W(src)); }
        struct stat st; lstat(link.c_str(), &st);
        check(r && S_ISLNK(st.st_mode) && get(real) == NEWV, "a symlinked document stays a link; its target gets the content");
        check(temps(dir).empty() && temps(root + "/g2real").empty(), "no temp file left");
    }
    {
        std::string dir = fresh(root, "g3"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        bool r;
        { CLocalFileLocker l(W(doc)); g_renameErrno = EXDEV; r = l.SaveFile(W(src)); g_renameErrno = 0; }
        check(r && get(doc) == NEWV && temps(dir).empty(), "rename refused with EXDEV: copied over, verified, temp removed");
    }
    {
        std::string dir = fresh(root, "g4"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        bool r;
        { CLocalFileLocker l(W(doc)); g_renameErrno = EIO; r = l.SaveFile(W(src)); g_renameErrno = 0; }
        check(!r && get(doc) == OLDV && temps(dir).empty(), "rename refused with EIO: save false, document untouched");
    }
    {
        std::string dir = fresh(root, "g5"), doc = dir + "/Report.docx";
        put(doc, OLDV); chmod(doc.c_str(), 0444);
        bool r;
        { CLocalFileLocker l(W(doc)); r = l.SaveFile(W(src)); }
        check(!r && get(doc) == OLDV && temps(dir).empty(), "a read-only document is not replaced");
        chmod(doc.c_str(), 0644);
    }
    {
        std::string dir = fresh(root, "g6"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        put(dir + "/.~lock.Report.docx#", ",someone-else,otherhost,01.01.2026 10:00,/home/someone-else;");
        bool r;
        { CLocalFileLocker l(W(doc)); r = l.SaveFile(W(src)); }
        check(!r && get(doc) == OLDV && temps(dir).empty(), "a document held by another user's .~lock marker is not replaced");
    }
    {
        std::string dir = fresh(root, "g7"), doc = dir + "/Report.docx";
        put(doc, OLDV);
        bool r;
        {
            CLocalFileLocker l(W(doc));
            chmod(dir.c_str(), 0555);
            r = l.SaveFile(W(src));
            chmod(dir.c_str(), 0755);
        }
        check(geteuid() == 0 || (r && get(doc) == NEWV), "a folder without create rights: the in-place save still works");
    }
    printf("%s\n", failures ? "FAILED" : "ok - a failed save leaves the document as it was and says so; a held lock does not block");
    return failures ? 1 : 0;
}
'''


def main():
    system = platform.system()
    if system not in ('Darwin', 'Linux'):
        print('skipped: macOS/Linux only (CFileLockerWin is not changed)')
        return 0
    d = tempfile.mkdtemp(prefix='rd2000_')
    try:
        src_dir = os.path.join(d, 'sdk', 'ChromiumBasedEditors', 'lib', 'src')
        os.makedirs(src_dir)
        # filelocker.cpp reaches core as ../../../../core relative to its own directory
        os.symlink(CORE, os.path.join(d, 'core'))
        for rel in (CPP, HDR):
            with open(os.path.join(d, 'sdk', rel), 'w', encoding='utf-8') as f:
                f.write(read(rel))
        cls = extract(read(APP), 'class CLocalFileLocker', ('bool SaveFile(const std::wstring& sFile)', 'StartWrite')) + ';'
        with open(os.path.join(d, 'harness.cpp'), 'w') as f:
            f.write(HARNESS.replace('LOCAL_FILE_LOCKER', cls))
        with open(os.path.join(d, 'inject.h'), 'w') as f:
            f.write(INJECT)
        common = os.path.join(CORE, 'DesktopEditor', 'common')
        if system == 'Darwin':
            defs, libs = ['-D_LINUX', '-D_MAC', '-DLINUX'], ['-framework', 'CoreFoundation']
        else:
            try:
                gio = subprocess.run(['pkg-config', '--cflags', '--libs', 'gio-2.0', 'gio-unix-2.0'],
                                     capture_output=True, text=True, check=True).stdout.split()
            except (OSError, subprocess.CalledProcessError):
                print('skipped: Linux needs pkg-config gio-2.0 gio-unix-2.0 (filelocker.cpp includes GIO)')
                return 0
            defs, libs = ['-D_LINUX', '-DLINUX'], gio
        cxx = os.environ.get('CXX', 'c++')
        base = [cxx, '-std=c++14', '-w', '-c', '-include', 'sys/stat.h', '-include', 'unistd.h', '-I', d] + defs
        objs = []
        units = [(os.path.join(d, 'harness.cpp'), [])] + \
                [(os.path.join(d, 'sdk', CPP), ['-include', os.path.join(d, 'inject.h')])] + \
                [(os.path.join(common, c), []) for c in COMMON]
        for i, (unit, extra) in enumerate(units):
            obj = os.path.join(d, 'u%d.o' % i)
            c = subprocess.run(base + extra + [unit, '-o', obj] + [x for x in libs if x.startswith('-I')],
                               capture_output=True, text=True)
            if c.returncode != 0:
                sys.stderr.write(c.stdout + c.stderr)
                raise SystemExit('harness did not compile: %s' % unit)
            objs.append(obj)
        exe = os.path.join(d, 'harness')
        c = subprocess.run([cxx] + objs + [x for x in libs if not x.startswith('-I')] + ['-o', exe],
                           capture_output=True, text=True)
        if c.returncode != 0:
            sys.stderr.write(c.stdout + c.stderr)
            raise SystemExit('harness did not link')
        print('#2000 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO), flush=True)
        work = os.path.join(d, 'work')
        os.makedirs(work)
        return subprocess.run([exe, work]).returncode
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
