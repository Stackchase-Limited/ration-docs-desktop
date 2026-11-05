#!/usr/bin/env python3
"""
#2480 (follow-up to issue-2480-gio-save-overwrite) - what a GIO save leaves
behind when the commit goes wrong half-way, and what an interrupted save
leaves behind at all.

The save writes a hidden sibling ".~<name>.<8 hex>.tmp" and Truncate() moves it
over the document with g_file_move(OVERWRITE | NO_FALLBACK_FOR_MOVE). gvfs-sftp
(REMOVE then RENAME) and libsmbclient (rename refused -> unlink -> rename)
replace in two steps. Before this change:
  (a) when the rename step failed after the remove (connection dropped), the
      document was gone and the new content was only in the hidden temp: the
      save reported failure, nothing retried the rename, nothing told anyone
      where the content was, and SaveFile's Unlock()/Lock() then ran
      g_file_append_to() on the missing document - creating an EMPTY document
      in its place, so the next retry by hand could not even rename over it.
  (b) temps left by a crash or kill mid-save were never removed.

Now: after a failed move, if the document is not there (or cannot be seen) the
rename is retried once without OVERWRITE (it cannot replace anything). If that
fails too the temp is kept, its path goes to the log (g_warning), Lock() does
not create an empty document, and Lock(), the next successful save and closing
the document each try to put it back (again without OVERWRITE). After the
first successful commit per document, our own stale temps are removed: exact
name ".~<doc name>.<8 lowercase hex>.tmp" (never for the shared empty-name form
used for names over 200 bytes), regular file (not a link or dir), modified at
least 7 days before the document's own mtime (both server clocks).

This compiles the real CFileLockerGIO class (filelocker.cpp) and the real
CLocalFileLocker::SaveFile (applicationmanager_p.h) against GLib and saves over
real files. Move faults are injected by wrapping the g_file_move the locker
calls: "remove target then fail" once (transient) or every time (persistent).

Real-fault mode (Linux container, see RD_DROP_TRIGGER): the server process is
killed between its remove and its rename - a real dropped connection - by an
LD_PRELOAD shim in sftp-server / smbd; the test checks no content is lost.

Modes:
  default            file:// URIs under a temp dir.
  RD_URI_PREFIX=...  gvfs mode, as in issue-2480-gio-save-overwrite
                     (RD_WORKDIR, RD_LOCAL_ROOT, GIO_USE_VFS=gvfs, mounted).
  RD_DROP_TRIGGER    path the server-side shim watches: the test creates it
                     before a save; the shim kills the server process on the
                     rename of our temp onto the document and removes it.
  RD_REMOUNT         shell command run after the drop (re-mounts the share).
  RD_REPO            desktop-sdk checkout (default ../../desktop-sdk).
  BASELINE=1         reads both files from BASE_REF (the parent of this fix);
                     must FAIL: transient fault loses the document, an empty
                     document is created, stale temps stay.

What is NOT claimed: telling the user in the UI (the path is logged and the
save reports failure; the editor still holds the content); recovery while the
share stays unreachable for the whole session (the temp stays on the server,
logged); gvfs backends other than sftp/smb.
Needs pkg-config gio-2.0 (Homebrew glib on macOS, libglib2.0-dev on Linux).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
APP = 'ChromiumBasedEditors/lib/src/applicationmanager_p.h'
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '4c58fffa^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel, from_git):
    if from_git:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
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


locker = extract(read(CPP, BASELINE), 'class CFileLockerGIO', ('g_file_append_to', 'StartWrite', 'g_file_move')) + ';'
save = extract(read(APP, BASELINE), 'bool SaveFile(const std::wstring& sFile)', ('StartWrite', 'Truncate'))

PRELUDE = r'''
#include <gio/gio.h>
#include <gio/gfiledescriptorbased.h>
#include <string>
#include <vector>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include <sys/time.h>
#include <ctime>
#include <cstdlib>

// Test hook around the real g_file_move the locker calls. g_moveFaults > 0:
// that many calls fail, the next ones are real. An OVERWRITE call that fails
// first removes the target, as gvfs-sftp / libsmbclient do when their rename
// step fails after the remove step.
static int g_moveFaults = 0;
static gboolean rd_g_file_move(GFile* s, GFile* d, GFileCopyFlags f, GCancellable* c,
                               GFileProgressCallback p, gpointer pd, GError** e) {
	if (g_moveFaults > 0) {
		g_moveFaults--;
		if (f & G_FILE_COPY_OVERWRITE) g_file_delete(d, NULL, NULL);
		g_set_error_literal(e, G_IO_ERROR, G_IO_ERROR_FAILED, "injected move failure");
		return FALSE;
	}
	return g_file_move(s, d, f, c, p, pd, e);
}
#define g_file_move rd_g_file_move
typedef unsigned long DWORD;	// as core/DesktopEditor/common/Types.h
typedef unsigned char BYTE;
#define RELEASEARRAYOBJECTS(p) { if (p) { delete[] p; p = NULL; } }
static std::string U_TO_UTF8(const std::wstring& w) { std::string s; for (wchar_t c : w) s += (char)c; return s; }

namespace NSFile {
class CFileBinary {
	FILE* f = NULL;
public:
	bool OpenFile(const std::wstring& p) { f = fopen(U_TO_UTF8(p).c_str(), "rb"); return f != NULL; }
	long GetFileSize() { long c = ftell(f); fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, c, SEEK_SET); return n; }
	bool ReadFile(BYTE* b, DWORD n, DWORD& r) { r = (DWORD)fread(b, 1, n, f); return r == n; }
	void CloseFile() { if (f) fclose(f); f = NULL; }
};
}

namespace NSSystem {
enum class LockType { ltNone, ltLocked, ltReadOnly };
// The cooperative .~lock marker is #1362's business: a stub that always grants
// the lock and writes nothing.
class CLockFileTemp {
	std::wstring m_p;
public:
	CLockFileTemp(const std::wstring& p) : m_p(p) {}
	std::wstring GetPath() { return m_p; }
	void Save(int) {}
};
static bool IsLockFileExists(const std::wstring&, int) { return false; }
class CFileLocker {
public:
	std::wstring m_sFile, m_sLockFilePath;
	CFileLocker(const std::wstring& f) : m_sFile(f) {}
	virtual ~CFileLocker() {}
	static CLockFileTemp CheckLockFilePath(const std::wstring& f, const int& = 0) { return CLockFileTemp(f + L".lock"); }
	virtual void DeleteLockFile() { m_sLockFilePath = L""; }
	virtual bool Lock() = 0;
	virtual bool Unlock() = 0;
	virtual bool StartWrite() { return true; }
	virtual bool IsWriteReady() { return true; }
	virtual bool SeekFile(DWORD) = 0;
	virtual bool Truncate(DWORD) = 0;
	virtual bool WriteFile(const void*, DWORD, DWORD&) = 0;
	virtual bool Flush() { return true; }
	virtual bool IsEmpty() { return false; }
};
'''

HOLDER = r'''
// The real CLocalFileLocker keeps one locker for the document's lifetime; these
// are the parts SaveFile uses, as written there.
struct Holder {
	std::wstring m_sFile;
	CFileLocker* m_pLocker;
	Holder(const std::wstring& f) : m_sFile(f), m_pLocker(new CFileLockerGIO(f)) { Lock(); }
	~Holder() { Unlock(); delete m_pLocker; }
	bool Lock() { Unlock(); m_pLocker->Lock(); return true; }
	bool Unlock() { m_pLocker->Unlock(); return true; }
	%s
};
''' % save

MAIN = r'''
} // NSSystem
using namespace NSSystem;

static std::vector<BYTE> pattern(size_t n, BYTE seed) {
	std::vector<BYTE> v(n); for (size_t i = 0; i < n; i++) v[i] = (BYTE)(seed + i * 7 + (i >> 9)); return v;
}
static void put(const std::string& p, const std::vector<BYTE>& v) { FILE* f = fopen(p.c_str(), "wb"); fwrite(v.data(), 1, v.size(), f); fclose(f); }
static std::vector<BYTE> get(const std::string& p) {
	std::vector<BYTE> v; FILE* f = fopen(p.c_str(), "rb"); if (!f) return v;
	BYTE b[65536]; size_t n; while ((n = fread(b, 1, sizeof b, f)) > 0) v.insert(v.end(), b, b + n); fclose(f); return v;
}
static bool exists(const std::string& p) { struct stat st; return lstat(p.c_str(), &st) == 0; }
static std::wstring W(const std::string& s) { return std::wstring(s.begin(), s.end()); }
static void age(const std::string& p, time_t t) { struct timeval tv[2] = { {t, 0}, {t, 0} }; lutimes(p.c_str(), tv); }

static std::string g_prefix = "file://", g_root;
static bool g_smb = false;
static std::wstring uri(const std::string& path) { return W(g_prefix + path.substr(g_root.size())); }
// hidden temp files of ours in the work dir (".~...tmp")
static std::vector<std::string> temps(const std::string& dir) {
	std::vector<std::string> r; DIR* d = opendir(dir.c_str()); if (!d) return r;
	while (dirent* e = readdir(d)) { std::string n = e->d_name;
		if (n.compare(0, 2, ".~") == 0 && n.size() > 4 && n.compare(n.size() - 4, 4, ".tmp") == 0) r.push_back(n); }
	closedir(d); return r;
}

// what the locker wrote to the log
static std::string g_logText;
static void logHandler(const gchar*, GLogLevelFlags, const gchar* m, gpointer) { g_logText += m; g_logText += "\n"; }

static int failures = 0;
static void check(bool ok, const char* what) { printf("  %s  %s\n", ok ? "ok  " : "FAIL", what); if (!ok) failures++; }

int main(int argc, char** argv) {
	std::string base = argv[1];
	if (getenv("RD_URI_PREFIX")) g_prefix = getenv("RD_URI_PREFIX");
	if (getenv("RD_LOCAL_ROOT")) g_root = getenv("RD_LOCAL_ROOT");
	g_smb = g_prefix.compare(0, 6, "smb://") == 0;
	g_log_set_handler(NULL, (GLogLevelFlags)(G_LOG_LEVEL_WARNING | G_LOG_LEVEL_MESSAGE), logHandler, NULL);
	printf("documents at %s%s/...\n", g_prefix.c_str(), base.substr(g_root.size()).c_str());
	auto oldv = pattern(300000, 1), newv = pattern(200000, 101), newv2 = pattern(150000, 201);
	int k = 0;
	auto freshDir = [&]() { std::string d = base + "/d" + std::to_string(k++); mkdir(d.c_str(), 0755); return d; };

	{
		printf("(a) target removed, the rename fails once (transient)\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src0.bin";
		put(path, oldv); put(src, newv); g_logText.clear();
		{
			Holder h(uri(path));
			g_moveFaults = 1;
			bool r = h.SaveFile(W(src));
			g_moveFaults = 0;
			check(r, "SaveFile reports success (rename retried)");
			check(get(path) == newv, "document holds exactly the new content");
			check(temps(dir).empty(), "no temp file left");
			put(src, newv2);
			check(h.SaveFile(W(src)) && get(path) == newv2, "the next save in the session works");
		}
		check(get(path) == newv2, "document intact after the editor lets go of it");
	}
	{
		printf("(a) target removed, every rename fails until the share is back; document closed\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src1.bin";
		put(path, oldv); put(src, newv); g_logText.clear();
		{
			Holder h(uri(path));
			g_moveFaults = 1000;
			bool r = h.SaveFile(W(src));
			g_moveFaults = 0;
			auto t = temps(dir);
			check(!r, "SaveFile reports failure");
			check(t.size() == 1 && get(dir + "/" + t[0]) == newv, "the temp file with the new content is kept");
			check(!exists(path), "no empty document created in its place (Lock after the failure)");
			check(t.size() == 1 && g_logText.find(t[0]) != std::string::npos, "the log names the temp file");
		}
		check(get(path) == newv, "closing the document puts the temp back: document holds the new content");
		check(temps(dir).empty(), "no temp file left");
	}
	{
		printf("(a) same, then the next save in the session\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src2.bin";
		put(path, oldv); put(src, newv); g_logText.clear();
		{
			Holder h(uri(path));
			g_moveFaults = 1000;
			check(!h.SaveFile(W(src)), "SaveFile reports failure");
			g_moveFaults = 0;
			put(src, newv2);
			check(h.SaveFile(W(src)) && get(path) == newv2, "the next save works and holds the newer content");
			check(temps(dir).empty(), "the kept (older) temp is removed after that save");
		}
		check(get(path) == newv2, "document intact after the editor lets go of it");
	}
	{
		printf("(a) the document reappears (restored by hand) before the editor closes\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src3.bin";
		put(path, oldv); put(src, newv); g_logText.clear();
		{
			Holder h(uri(path));
			g_moveFaults = 1000;
			check(!h.SaveFile(W(src)), "SaveFile reports failure");
			g_moveFaults = 0;
			put(path, oldv);
		}
		auto t = temps(dir);
		check(get(path) == oldv, "the restored document is not replaced");
		check(t.size() == 1 && get(dir + "/" + t[0]) == newv, "the temp with the new content is still there");
		check(t.size() == 1 && g_logText.find(t[0]) != std::string::npos, "the log names it");
	}
	{
		printf("(b) stale temp files from an interrupted save\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src4.bin";
		std::string longName(210, 'L'); longName += ".docx";
		put(path, oldv); put(src, newv);
		time_t old = time(NULL) - 30 * 24 * 3600, recent = time(NULL) - 24 * 3600;
		struct F { std::string name; bool removed; time_t t; };
		std::vector<F> files = {
			{".~doc.docx.0123abcd.tmp", true, old},       // ours, a month old
			{".~doc.docx.ffffffff.tmp", true, old},
			{".~doc.docx.0123abce.tmp", false, recent},   // ours, a day old: could be someone's live save
			{".~other.docx.0123abcd.tmp", false, old},    // another document's
			{".~doc.docx.4567ABCD.tmp", false, old},      // not our hex (distinct on case-insensitive disks too)
			{".~doc.docx.0123abc.tmp", false, old},       // 7 digits
			{".~doc.docx.0123abcde.tmp", false, old},     // 9 digits
			{".~doc.docx.0123abcd.tmp.bak", false, old},
			{"doc.docx.0123abcd.tmp", false, old},
			{".~doc.docx.89abcdef.TMP", false, old},
			{".~lock.doc.docx#", false, old},
			{".~.0123abcd.tmp", false, old},              // long-name form: shared by every long name
		};
		for (auto& f : files) { put(dir + "/" + f.name, oldv); age(dir + "/" + f.name, f.t); }
		mkdir((dir + "/.~doc.docx.11111111.tmp").c_str(), 0755); age(dir + "/.~doc.docx.11111111.tmp", old);
		if (!g_smb) {
			put(dir + "/target.bin", oldv);
			if (symlink("target.bin", (dir + "/.~doc.docx.22222222.tmp").c_str())) {}
			age(dir + "/target.bin", old); age(dir + "/.~doc.docx.22222222.tmp", old);
		}
		{
			Holder h(uri(path));
			check(h.SaveFile(W(src)) && get(path) == newv, "save works");
		}
		for (auto& f : files) {
			std::string what = f.name + (f.removed ? " removed" : " kept");
			check(exists(dir + "/" + f.name) != f.removed, what.c_str());
		}
		check(exists(dir + "/.~doc.docx.11111111.tmp"), "directory with our name kept");
		if (!g_smb) {
			check(exists(dir + "/.~doc.docx.22222222.tmp") && get(dir + "/target.bin") == oldv, "symlink with our name kept, its target untouched");
		} else
			printf("  skip  symlink case: smb:// (samba shows links as their targets)\n");

		// long document name (> 200 bytes): its temps use the shared ".~.<hex>.tmp" form; never cleaned
		std::string lpath = dir + "/" + longName;
		put(lpath, oldv);
		{
			Holder h(uri(lpath));
			check(h.SaveFile(W(src)) && get(lpath) == newv, "save of a long-named document works");
		}
		check(exists(dir + "/.~.0123abcd.tmp"), "shared long-name temp kept");
	}
	{
		printf("(b) a save that fails does not clean up\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src5.bin";
		put(path, oldv); put(src, newv);
		std::string stale = dir + "/.~doc.docx.0123abcd.tmp";
		put(stale, oldv); age(stale, time(NULL) - 30 * 24 * 3600);
		{
			Holder h(uri(path));
			g_moveFaults = 1000;
			check(!h.SaveFile(W(src)), "SaveFile reports failure");
			g_moveFaults = 0;
			check(exists(stale), "stale temp still there after the failed save");
			put(path, oldv);	// the document as it was, so closing has nothing to restore
		}
		for (auto& n : temps(dir)) if (dir + "/" + n != stale) remove((dir + "/" + n).c_str());
	}

	// a real dropped connection between the backend's remove and rename
	const char* trigger = getenv("RD_DROP_TRIGGER");
	if (trigger) {
		printf("(a) real fault: the server process dies between remove and rename\n");
		std::string dir = freshDir(), path = dir + "/doc.docx", src = dir + "/../src6.bin";
		put(path, oldv); put(src, newv); g_logText.clear();
		bool r;
		{
			Holder h(uri(path));
			put(trigger, {'1'});
			r = h.SaveFile(W(src));
			bool fired = !exists(trigger);
			remove(trigger);
			auto t = temps(dir);
			printf("  info  shim fired: %s; SaveFile: %s; document: %s; temps: %zu\n", fired ? "yes" : "NO",
			       r ? "success" : "failure", !exists(path) ? "missing" : get(path) == newv ? "new" : get(path) == oldv ? "old" : "OTHER", t.size());
			if (!g_logText.empty()) printf("  log   %s", g_logText.c_str());
			check(fired, "the shim killed the server mid-move");
			bool safe = (r && get(path) == newv && t.empty()) ||
			            (!r && t.size() == 1 && get(dir + "/" + t[0]) == newv && g_logText.find(t[0]) != std::string::npos);
			check(safe, "new content is either in the document (save ok) or in a kept, logged temp");
			check(!exists(path) || get(path) == newv || get(path) == oldv, "no empty or partial document");
			if (getenv("RD_REMOUNT")) { if (system(getenv("RD_REMOUNT"))) {} }
		}
		check(get(path) == newv, "after the share is back and the document is closed it holds the new content");
		check(temps(dir).empty(), "no temp file left");
	}
	printf(failures ? "FAIL #2480 recovery: %d check(s) failed\n" : "PASS #2480 recovery: no content lost when the replace breaks half-way; stale temps cleaned, nothing else\n", failures);
	return failures ? 1 : 0;
}
'''


def main():
    try:
        flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'gio-2.0', 'gio-unix-2.0'],
                               capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        print('SKIP #2480 recovery: pkg-config gio-2.0 not available')
        return 0
    work = tempfile.mkdtemp(prefix='rd2480r-')
    docs = tempfile.mkdtemp(prefix='rd2480r-', dir=os.environ.get('RD_WORKDIR'))
    try:
        src = os.path.join(work, 't.cpp')
        with open(src, 'w') as f:
            f.write(PRELUDE + locker + HOLDER + MAIN)
        exe = os.path.join(work, 't')
        subprocess.run(['c++', '-std=c++17', '-w', src, '-o', exe] + flags, check=True)
        if BASELINE:
            print('BASELINE (%s): the transient-fault, empty-document and stale-temp checks must fail' % BASE_REF, flush=True)
        return subprocess.run([exe, docs]).returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(docs, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
