#!/usr/bin/env python3
"""
#2480 - on Linux, saving over a document opened from a GVFS location (smb://,
sftp://) left the OLD content at the NEW length. Smaller save: the old zip cut
short, unopenable. Larger save: the old document followed by the start of the
new one, which opens as the previous version. No error either way.

CFileLockerGIO::Lock() opens the document with g_file_append_to() and the save
wrote through that stream: SeekFile(0), WriteFile..., SeekFile(n), Truncate(n).
An append stream writes at the end whatever the seek says - gvfs-smb refuses
the seek, gvfs-sftp and local files accept it and append anyway - so the new
bytes went after the old ones and the truncate kept the old head.

The first fix (565af3d1) wrote through g_file_replace() and aborted a failed
save by closing that stream with a cancelled GCancellable. That is safe for
local files only: on gvfs the client close says "cancelled" while gvfsd closes
its handle ~1 s later and COMMITS the replace - a save that failed partway put
the half-written file in place of the document. Now the save goes to a hidden
sibling temp file (.~<name>.<random>.tmp, g_file_create) that Truncate() - the
commit SaveFile calls only after a complete write - moves over the document
(g_file_move OVERWRITE | NO_FALLBACK_FOR_MOVE); an aborted save deletes it.

This compiles the real CFileLockerGIO class (filelocker.cpp) and the real
CLocalFileLocker::SaveFile loop (applicationmanager_p.h) against GLib and saves
over real files: overwrite smaller / larger / same size, a second save in the
session, document mode kept (0640) but not its old mtime, a save failing mid-write leaves the
document byte-identical (checked again after 3 s, when gvfsd would have
committed), no temp file left behind, and a failing move (injected by wrapping
g_file_move; on smb:// also a real sharing violation from an open handle)
reports failure and keeps the document; when the backend removed the target
before its rename failed, the temp - the only copy of the new content - stays.

Modes:
  default            file:// URIs under a temp dir (GLib's local backend).
  RD_URI_PREFIX=...  gvfs mode, e.g. sftp://user@localhost or
                     smb://localhost/share (mounted with `gio mount` first,
                     GIO_USE_VFS=gvfs, a session bus). The test reads and
                     writes the files through local paths too, so the server
                     must be on this machine: RD_WORKDIR = local dir to create
                     the temp dir in (must be inside the exported tree),
                     RD_LOCAL_ROOT = local path the URI prefix maps to (empty
                     for sftp, e.g. /srv/share for smb://localhost/share).
                     On smb:// the mode check is skipped: samba applies its
                     own create mask to the renamed file and gvfs-smb cannot
                     set unix::mode.
  RD_REPO            desktop-sdk checkout (default ../../desktop-sdk).
  BASELINE=1         re-reads both files from BASE_REF (default: the parent of
                     the temp-file fix, i.e. the cancel-based replace stream).
                     Locally that FAILS the injected-move-failure checks (it
                     never moves); on sftp/smb it also FAILS the mid-write abort
                     (ORIGINAL LOST after the wait).

What is NOT claimed: atomicity of the backends' own replace (gvfs-sftp and
libsmbclient remove the target, then rename - a crash between the two leaves
only the temp); other gvfs backends (dav, ftp, mtp, google) were not run.
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
# Pinned to the parent of the commit that landed the fix, never HEAD: once the
# fix is committed HEAD carries it and the baseline would test nothing.
# (The original append-stream bug's baseline was 565af3d1^.)
BASE_REF = os.environ.get('BASE_REF', '17e125e1^')
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


locker = extract(read(CPP, BASELINE), 'class CFileLockerGIO', ('g_file_append_to', 'StartWrite')) + ';'
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

// Test hook around the real g_file_move the locker calls: 1 = fail without
// touching anything, 2 = fail after removing the target (what gvfs-sftp and
// libsmbclient do when their rename step fails after the remove step).
static int g_moveFault = 0;
static gboolean rd_g_file_move(GFile* s, GFile* d, GFileCopyFlags f, GCancellable* c,
                               GFileProgressCallback p, gpointer pd, GError** e) {
	if (g_moveFault) {
		if (g_moveFault == 2) g_file_delete(d, NULL, NULL);
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

static bool g_shortRead = false;	// test hook: the conversion result reads back short
namespace NSFile {
class CFileBinary {
	FILE* f = NULL;
public:
	bool OpenFile(const std::wstring& p) { f = fopen(U_TO_UTF8(p).c_str(), "rb"); return f != NULL; }
	long GetFileSize() { long c = ftell(f); fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, c, SEEK_SET); return n; }
	bool ReadFile(BYTE* b, DWORD n, DWORD& r) { r = (DWORD)fread(b, 1, n, f); if (g_shortRead && r > 10) r -= 10; return r == n; }
	void CloseFile() { if (f) fclose(f); f = NULL; }
};
}

namespace NSSystem {
enum class LockType { ltNone, ltLocked, ltReadOnly };
// The cooperative .~lock marker is #1362's business, not this test's: a stub that
// always grants the lock and writes nothing.
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
static std::wstring W(const std::string& s) { return std::wstring(s.begin(), s.end()); }

static std::string g_prefix = "file://", g_root;
static bool g_smb = false;
// local path -> the URI the editor would have opened
static std::wstring uri(const std::string& path) { return W(g_prefix + path.substr(g_root.size())); }
// hidden entries in the work dir: leftover temp files (the stubbed lock marker writes nothing)
static std::vector<std::string> hidden(const std::string& dir) {
	std::vector<std::string> r; DIR* d = opendir(dir.c_str()); if (!d) return r;
	while (dirent* e = readdir(d)) { std::string n = e->d_name; if (n[0] == '.' && n != "." && n != "..") r.push_back(n); }
	closedir(d); return r;
}
static void clearHidden(const std::string& dir) { for (auto& n : hidden(dir)) remove((dir + "/" + n).c_str()); }

static int failures = 0;
static void check(bool ok, const char* what) { printf("  %s  %s\n", ok ? "ok  " : "FAIL", what); if (!ok) failures++; }

int main(int argc, char** argv) {
	std::string dir = argv[1];
	if (getenv("RD_URI_PREFIX")) g_prefix = getenv("RD_URI_PREFIX");
	if (getenv("RD_LOCAL_ROOT")) g_root = getenv("RD_LOCAL_ROOT");
	g_smb = g_prefix.compare(0, 6, "smb://") == 0;
	printf("documents at %s%s/...\n", g_prefix.c_str(), dir.substr(g_root.size()).c_str());

	struct Case { const char* name; size_t oldN, newN; };
	Case cases[] = { {"smaller save (200000 over 300000)", 300000, 200000},
	                 {"larger save (360000 over 300000)", 300000, 360000},
	                 {"same-size save", 250000, 250000} };
	int k = 0;
	for (auto& c : cases) {
		std::string path = dir + "/doc" + std::to_string(k++) + ".docx", src = dir + "/src.bin";
		auto oldv = pattern(c.oldN, 1), newv = pattern(c.newN, 101);
		put(path, oldv); put(src, newv); chmod(path.c_str(), 0640);
		struct timeval old2020[2] = { {1577836800, 0}, {1577836800, 0} };
		utimes(path.c_str(), old2020);
		printf("%s\n", c.name);
		{
			Holder h(uri(path));
			bool r = h.SaveFile(W(src));
			auto got = get(path);
			check(r, "SaveFile reports success");
			check(got.size() == newv.size(), "file has the new length");
			check(got == newv, "file holds exactly the new content");
			bool oldHead = got.size() >= 4096 && memcmp(got.data(), oldv.data(), 4096) == 0;
			check(!oldHead, "file does not start with the old content");

			// a second save in the same session, after the append stream is reopened
			auto newv2 = pattern(c.newN / 2 + 1000, 201);
			put(src, newv2);
			bool r2 = h.SaveFile(W(src));
			check(r2 && get(path) == newv2, "second save in the same session is exact");
			check(hidden(dir).empty(), "no temp file left next to the document");
		}
		struct stat st; stat(path.c_str(), &st);
		check(time(NULL) - st.st_mtime < 3600, "modification time is the save's, not the old file's");
		if (g_smb)
			printf("  skip  file mode kept (0640): smb:// - samba's create mask decides the mode (now 0%o)\n", st.st_mode & 0777);
		else
			check((st.st_mode & 0777) == 0640, "file mode kept (0640)");
	}
	// A save that fails after bytes went out must leave the document as it was:
	// SaveFile then calls Unlock(). gvfsd committed a cancelled replace stream
	// about a second later, so look again after waiting.
	{
		printf("save failing mid-write\n");
		std::string path = dir + "/abort.docx", src = dir + "/src.bin";
		auto oldv = pattern(300000, 1), newv = pattern(200000, 101);
		put(path, oldv); put(src, newv);
		{
			Holder h(uri(path));
			g_shortRead = true;
			bool r = h.SaveFile(W(src));
			g_shortRead = false;
			check(!r, "SaveFile reports failure");
			check(get(path) == oldv, "document left exactly as it was");
			g_usleep(3 * G_USEC_PER_SEC);
			check(get(path) == oldv, "document still exactly as it was 3 s later");
			check(hidden(dir).empty(), "no temp file left next to the document");
			put(src, newv);
			check(h.SaveFile(W(src)) && get(path) == newv, "the next save in the session works");
		}
		check(get(path) == newv, "document intact after the editor lets go of it");
	}
	// The commit (moving the temp over the document) fails.
	{
		printf("move over the document fails\n");
		std::string path = dir + "/move.docx", src = dir + "/src.bin";
		auto oldv = pattern(300000, 1), newv = pattern(200000, 101);
		put(path, oldv); put(src, newv);
		Holder h(uri(path));
		g_moveFault = 1;
		bool r = h.SaveFile(W(src));
		g_moveFault = 0;
		check(!r, "SaveFile reports failure");
		check(get(path) == oldv, "document left exactly as it was");
		check(hidden(dir).empty(), "no temp file left next to the document");

		// the backend removed the target, then its rename failed: the temp is all there is
		g_moveFault = 2;
		r = h.SaveFile(W(src));
		g_moveFault = 0;
		auto left = hidden(dir);
		check(!r, "target removed, rename failed: SaveFile reports failure");
		check(left.size() == 1 && get(dir + "/" + left[0]) == newv, "the temp file with the new content is kept");
		clearHidden(dir);
		put(path, oldv);

		check(h.SaveFile(W(src)) && get(path) == newv, "the next save in the session works");
		check(hidden(dir).empty(), "no temp file left next to the document");
	}
	if (g_smb) {
		// real failure: samba refuses to rename over a file another handle has open
		printf("smb: another handle holds the document open\n");
		std::string path = dir + "/held.docx", src = dir + "/src.bin";
		auto oldv = pattern(300000, 1), newv = pattern(200000, 101);
		put(path, oldv); put(src, newv);
		Holder h(uri(path));
		GFile* f = g_file_new_for_uri((g_prefix + path.substr(g_root.size())).c_str());
		GInputStream* in = G_INPUT_STREAM(g_file_read(f, NULL, NULL));
		bool r = h.SaveFile(W(src));
		check(in && !r, "SaveFile reports failure (sharing violation)");
		check(get(path) == oldv, "document left exactly as it was");
		check(hidden(dir).empty(), "no temp file left next to the document");
		if (in) { g_input_stream_close(in, NULL, NULL); g_object_unref(in); }
		g_object_unref(f);
		check(h.SaveFile(W(src)) && get(path) == newv, "once it is closed the save works");
	}
	printf(failures ? "FAIL #2480: %d check(s) failed\n" : "PASS #2480: GIO saves overwrite the document; failed saves keep it\n", failures);
	return failures ? 1 : 0;
}
'''


def main():
    try:
        flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'gio-2.0', 'gio-unix-2.0'],
                               capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        print('SKIP #2480: pkg-config gio-2.0 not available')
        return 0
    work = tempfile.mkdtemp(prefix='rd2480-')
    docs = tempfile.mkdtemp(prefix='rd2480-', dir=os.environ.get('RD_WORKDIR'))
    try:
        src = os.path.join(work, 't.cpp')
        with open(src, 'w') as f:
            f.write(PRELUDE + locker + HOLDER + MAIN)
        exe = os.path.join(work, 't')
        subprocess.run(['c++', '-std=c++17', '-w', src, '-o', exe] + flags, check=True)
        if BASELINE:
            print('BASELINE (%s): the move-failure checks must fail (and on gvfs the mid-write abort)' % BASE_REF, flush=True)
        return subprocess.run([exe, docs]).returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(docs, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
