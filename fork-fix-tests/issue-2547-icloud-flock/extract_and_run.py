#!/usr/bin/env python3
"""
#2547 - "DOCX saves to iCloud-synced Documents stall uploads with
itemIsFlockedCanNotPropagate" (macOS).

Bug: a document saved into an iCloud-synced folder never leaves the Mac.  Finder
sits on "Uploading 1 item" and fileproviderd records itemIsFlockedCanNotPropagate
against the file.

Cause: on macOS CFileLocker::Create hands every local document to
CFileLockerFCNTL, whose Lock() keeps fcntl(F_SETLK, F_WRLCK) on the whole file for
as long as it is open in the editor.  On macOS an fcntl lock and a flock() lock
are the same lock: any other process that asks flock(LOCK_SH|LOCK_NB), or opens
with O_SHLOCK|O_NONBLOCK, is refused with EWOULDBLOCK.  That is what File Provider
sees as "flocked", and the save path writes through that very descriptor, so every
save lands while the lock is held.

Fix: for a document that File Provider syncs (a path under ~/Library/Mobile
Documents or ~/Library/CloudStorage, or one macOS reports as ubiquitous through
kCFURLIsUbiquitousItemKey) Create() returns CFileLockerFileProvider: the .~lock
marker and the write descriptor, but no kernel lock.  Every other path keeps
CFileLockerFCNTL exactly as before.

What runs here: the WHOLE real filelocker.cpp/.h from desktop-sdk, compiled with
the real core/DesktopEditor/common sources (File, Directory, SystemUtils, ...) and
CoreFoundation, the same way the macOS build does - nothing is extracted or
copied.  The only build-level help is `-include sys/stat.h -include unistd.h`,
which the real build gets transitively and core's Directory.cpp does not include
itself.  Locks, flock(), fork() and the filesystem are all real.

Measured:
  A  iCloud Drive path (".../Library/Mobile Documents/com~apple~CloudDocs/"):
     after Create()+Lock(), ANOTHER process's flock(LOCK_SH|LOCK_NB) succeeds
     (File Provider no longer sees a flock); the .~lock marker is still written;
     a save through the locker (SeekFile/WriteFile/Truncate/Flush) still lands.
  B  Third-party File Provider path (".../Library/CloudStorage/..."): same flock
     check.
  C  An ordinary path: another process's flock is still refused, and the real
     CFileLocker::IsLocked in another process still answers ltLocked - the
     #1362/#2135 cross-process guard is unchanged.
  D  iCloud path, a different user's process (USER changed in the child): the
     real CFileLocker::IsLocked still answers ltLocked through the marker.
  E  (measurement, not a guard) iCloud path, SAME user, another process:
     IsLocked answers ltNone.  This is the protection the fix gives up, and only
     for File Provider folders: two processes of one user, sharing one
     app-data dir, on one document.  On macOS that needs `open -n`.

BASELINE=1 reads filelocker.{cpp,h} from BASE_REF (default: the parent of the
commit that landed this fix); A and B must FAIL there.  The integrator re-pins
BASE_REF after cherry-picking.  Never point it at HEAD.

NOT verified: that kCFURLIsUbiquitousItemKey answers true for ~/Documents with
iCloud "Desktop & Documents" on (iCloud is not signed in on the test host: the
call is exercised, it answers no), and that fileproviderd then uploads - that
needs a GUI check on a Mac with iCloud Drive.  Only macOS runs this test.
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk')))
CORE = os.path.abspath(os.environ.get('RD_CORE', os.path.join(HERE, '..', '..', 'core')))
CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
HDR = 'ChromiumBasedEditors/lib/src/filelocker.h'
BASE_REF = os.environ.get('BASE_REF', '47cbfdfb00^')
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


HARNESS = r'''
#include "sdk/ChromiumBasedEditors/lib/src/filelocker.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>

using namespace NSSystem;

static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("    %-66s %s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}
static std::wstring W(const std::string &s) { return std::wstring(s.begin(), s.end()); }
static void mkdirs(const std::string &p)
{
    for (size_t i = 1; i <= p.size(); ++i)
        if (i == p.size() || p[i] == '/') mkdir(p.substr(0, i).c_str(), 0755);
}
static void put(const std::string &p, const std::string &s)
{ FILE *f = fopen(p.c_str(), "wb"); fwrite(s.data(), 1, s.size(), f); fclose(f); }
static std::string get(const std::string &p)
{ std::string s; FILE *f = fopen(p.c_str(), "rb"); if (!f) return "<missing>";
  char b[256]; size_t n; while ((n = fread(b, 1, sizeof b, f)) > 0) s.append(b, n); fclose(f); return s; }

/* What File Provider asks: can somebody else take a shared flock right now? */
static bool other_process_can_flock(const std::string &p)
{
    pid_t pid = fork();
    if (pid == 0) {
        int fd = open(p.c_str(), O_RDONLY);
        if (fd < 0) _exit(2);
        _exit(flock(fd, LOCK_SH | LOCK_NB) == 0 ? 0 : 1);
    }
    int st = 0; waitpid(pid, &st, 0);
    return WIFEXITED(st) && WEXITSTATUS(st) == 0;
}
/* The real CFileLocker::IsLocked, asked from another process, optionally as another user. */
static int other_process_islocked(const std::string &p, const char *user)
{
    pid_t pid = fork();
    if (pid == 0) {
        if (user) setenv("USER", user, 1);
        _exit((int)CFileLocker::IsLocked(W(p)));
    }
    int st = 0; waitpid(pid, &st, 0);
    return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}
static std::string marker(const std::string &p)
{
    size_t s = p.rfind('/');
    return p.substr(0, s + 1) + ".~lock." + p.substr(s + 1) + "#";
}

int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    std::string root = argv[1];
    const std::string icloud = root + "/home/Library/Mobile Documents/com~apple~CloudDocs/Report.docx";
    const std::string cloudstorage = root + "/home/Library/CloudStorage/Dropbox/Report.docx";
    const std::string plain = root + "/home/Downloads/Report.docx";

    /* ---- A ---- */
    printf("  A  iCloud Drive path, the document open in the editor\n");
    mkdirs(icloud.substr(0, icloud.rfind('/')));
    put(icloud, "ORIGINAL");
    CFileLocker *a = CFileLocker::Create(W(icloud));
    a->Lock();
    check(other_process_can_flock(icloud), "another process can take flock(LOCK_SH|LOCK_NB) (no itemIsFlocked)");
    check(get(marker(icloud)) != "<missing>", "the .~lock marker is still written");
    {
        const char saved[] = "SAVED BY THE EDITOR";
        DWORD wrote = 0;
        bool ok = a->StartWrite() && a->IsWriteReady() && a->SeekFile(0) &&
                  a->WriteFile(saved, (DWORD)strlen(saved), wrote) && wrote == strlen(saved) &&
                  a->Truncate((DWORD)strlen(saved)) && a->Flush();
        check(ok && get(icloud) == saved, "a save through the locker still lands on disk");
    }
    a->Unlock();
    delete a;
    check(get(marker(icloud)) == "<missing>", "closing the document removes the marker");

    /* ---- B ---- */
    printf("  B  ~/Library/CloudStorage path\n");
    mkdirs(cloudstorage.substr(0, cloudstorage.rfind('/')));
    put(cloudstorage, "ORIGINAL");
    CFileLocker *b = CFileLocker::Create(W(cloudstorage));
    b->Lock();
    check(other_process_can_flock(cloudstorage), "another process can take flock(LOCK_SH|LOCK_NB)");
    delete b;

    /* ---- C ---- */
    printf("  C  an ordinary path keeps the kernel lock (#1362 / #2135 guard)\n");
    mkdirs(plain.substr(0, plain.rfind('/')));
    put(plain, "ORIGINAL");
    CFileLocker *c = CFileLocker::Create(W(plain));
    c->Lock();
    check(!other_process_can_flock(plain), "another process is still refused a flock");
    check(other_process_islocked(plain, NULL) == (int)LockType::ltLocked,
          "CFileLocker::IsLocked in another process answers ltLocked");
    delete c;

    /* ---- D / E ---- */
    printf("  D  iCloud path, another user's process\n");
    CFileLocker *d = CFileLocker::Create(W(icloud));
    d->Lock();
    check(other_process_islocked(icloud, "someone-else") == (int)LockType::ltLocked,
          "CFileLocker::IsLocked answers ltLocked through the marker");
    int same = other_process_islocked(icloud, NULL);
    printf("  E  (measurement) iCloud path, same user, another process: IsLocked = %s\n",
           same == (int)LockType::ltNone ? "ltNone - the guard given up for File Provider folders"
                                         : "ltLocked");
    delete d;

    printf("%s\n", failures ? "FAILED" : "ok - File Provider documents are not flocked; other paths keep the lock");
    return failures ? 1 : 0;
}
'''


def main():
    if platform.system() != 'Darwin':
        print('skipped: macOS-only (fcntl/flock equivalence and CoreFoundation)')
        return 0
    with tempfile.TemporaryDirectory(prefix='rd2547_') as d:
        src_dir = os.path.join(d, 'sdk', 'ChromiumBasedEditors', 'lib', 'src')
        os.makedirs(src_dir)
        # filelocker.cpp reaches core as ../../../../core relative to its own directory
        os.symlink(CORE, os.path.join(d, 'core'))
        for rel in (CPP, HDR):
            with open(os.path.join(d, 'sdk', rel), 'w', encoding='utf-8') as f:
                f.write(read(rel))
        with open(os.path.join(d, 'harness.cpp'), 'w') as f:
            f.write(HARNESS)
        exe = os.path.join(d, 'harness')
        common = os.path.join(CORE, 'DesktopEditor', 'common')
        cmd = ['clang++', '-std=c++14', '-w', '-D_LINUX', '-D_MAC', '-DLINUX',
               '-include', 'sys/stat.h', '-include', 'unistd.h', '-I', d,
               os.path.join(d, 'harness.cpp'), os.path.join(d, 'sdk', CPP)] + \
              [os.path.join(common, c) for c in COMMON] + \
              ['-framework', 'CoreFoundation', '-o', exe]
        c = subprocess.run(cmd, capture_output=True, text=True)
        if c.returncode != 0:
            sys.stderr.write(c.stdout + c.stderr)
            raise SystemExit('harness did not compile')
        print('#2547 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO), flush=True)
        work = os.path.join(d, 'work')
        os.makedirs(work)
        return subprocess.run([exe, work]).returncode


if __name__ == '__main__':
    sys.exit(main())
