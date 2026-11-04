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

This compiles the real CFileLockerGIO class (filelocker.cpp) and the real
CLocalFileLocker::SaveFile loop (applicationmanager_p.h) against GLib, and
saves over real files through file:// URIs. A local file takes the same GIO
append-stream path the report measured on sftp (can_seek = TRUE, writes still
appended), so the baseline reproduces the reported damage byte for byte.

It also fails a save partway: the document must be left exactly as it was.
Before the fix SaveFile finalised (Truncate) even a failed write, and with a
replace stream that commit would have put the half-written file in place.

  BASELINE=1 re-reads both files from the parent of the fix, where the
  overwrite cases must FAIL.

What is NOT claimed: no smb or sftp share was mounted; gvfs-smb's can_seek =
FALSE variant is not exercised (the fix does not depend on seeking).
Needs pkg-config gio-2.0 (Homebrew glib on macOS, libglib2.0-dev on Linux).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CPP = 'ChromiumBasedEditors/lib/src/filelocker.cpp'
APP = 'ChromiumBasedEditors/lib/src/applicationmanager_p.h'
# Pinned to the parent of the commit that landed the fix, never HEAD: once the
# fix is committed HEAD carries it and the baseline would test nothing.
BASE_REF = os.environ.get('BASE_REF', '565af3d1^')
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

static int failures = 0;
static void check(bool ok, const char* what) { printf("  %s  %s\n", ok ? "ok  " : "FAIL", what); if (!ok) failures++; }

int main(int argc, char** argv) {
	std::string dir = argv[1];
	struct Case { const char* name; size_t oldN, newN; };
	Case cases[] = { {"smaller save (200000 over 300000)", 300000, 200000},
	                 {"larger save (360000 over 300000)", 300000, 360000},
	                 {"same-size save", 250000, 250000} };
	int k = 0;
	for (auto& c : cases) {
		std::string path = dir + "/doc" + std::to_string(k++) + ".docx", src = path + ".new";
		auto oldv = pattern(c.oldN, 1), newv = pattern(c.newN, 101);
		put(path, oldv); put(src, newv); chmod(path.c_str(), 0644);
		printf("%s\n", c.name);
		{
			Holder h(W("file://" + path));
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
		}
		struct stat st; stat(path.c_str(), &st);
		check((st.st_mode & 0777) == 0644, "file mode kept (0644)");
	}
	// A save that fails after bytes went out must leave the document as it was:
	// SaveFile then calls Unlock(), and committing the replace stream there would
	// put a half-written file in place of the original.
	{
		printf("save failing mid-write\n");
		std::string path = dir + "/abort.docx", src = path + ".new";
		auto oldv = pattern(300000, 1), newv = pattern(200000, 101);
		put(path, oldv); put(src, newv);
		Holder h(W("file://" + path));
		g_shortRead = true;
		bool r = h.SaveFile(W(src));
		g_shortRead = false;
		check(!r, "SaveFile reports failure");
		check(get(path) == oldv, "document left exactly as it was");
		put(src, newv);
		check(h.SaveFile(W(src)) && get(path) == newv, "the next save in the session works");
	}
	printf(failures ? "FAIL #2480: %d check(s) failed\n" : "PASS #2480: GIO saves overwrite the document\n", failures);
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
    try:
        src = os.path.join(work, 't.cpp')
        with open(src, 'w') as f:
            f.write(PRELUDE + locker + HOLDER + MAIN)
        exe = os.path.join(work, 't')
        subprocess.run(['c++', '-std=c++17', '-w', src, '-o', exe] + flags, check=True)
        if BASELINE:
            print('BASELINE (%s): the overwrite checks must fail' % BASE_REF)
        return subprocess.run([exe, work]).returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
