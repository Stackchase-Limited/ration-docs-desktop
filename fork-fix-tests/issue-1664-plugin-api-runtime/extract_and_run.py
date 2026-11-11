#!/usr/bin/env python3
"""
#1664 (security follow-up) - user plugins must load the plugin API the app
ships, not one downloaded at run time.

Bug: every plugin install from the store (AscDesktopEditor.PluginInstall,
desktop-sdk client_renderer_wrapper.cpp, comment "ENGINE can be updated")
downloaded plugins.js, plugins-ui.js and plugins.css from
https://onlyoffice.github.io/sdkjs-plugins/v1/ into <user plugins>/v1/.
CPluginsManager::AddPlugin rewrites every user plugin's
https://onlyoffice.github.io/sdkjs-plugins/ links to that folder, so whoever
controlled that host (or the network path to it) put script into every
user-installed plugin - file:// pages beside the editor with the desktop
bridge. The start-up refresh of that folder (cefapplication.cpp, Init_CEF,
"user plugins") never worked: it called CFileBinary::Remove (std::remove /
_wremove) on the directory, which cannot remove a non-empty directory, so a
v1/ once filled by the download stayed for good, across app updates.

Fix (desktop-sdk wip/1664-plugin-api): PluginInstall copies the three files
from the app's <system plugins>/v1/ (build_tools a3a1931 checks them in, see
issue-1664-build-plugin-api); start-up deletes the user v1/ with
NSDirectory::DeleteDirectory and copies the app's v1/ in (only when the app
has one).

This test takes, by brace matching, the REAL
  - "if (true) { ... }" block that PluginInstall runs after installing (the one
    before "// send to editor"), and
  - "// user plugins" block of CApplicationCEF::Init_CEF,
compiles each against stub NSFile/NSDirectory/CFileDownloaderWrapper classes
that act on a temp directory (CFileBinary::Remove is std::remove, as in core;
the downloader "downloads" a marker naming the URL and records the call), and
checks:
  1. PluginInstall leaves <user>/v1/plugins*.js/.css byte-identical to the
     app's v1/ and downloads nothing (also when <user>/v1 is missing);
  2. start-up replaces a stale <user>/v1/ (as an earlier download left it)
     with the app's files, and keeps it when the app has no v1/;
  3. no source under ChromiumBasedEditors/lib/src names a URL ending in
     sdkjs-plugins/v1/.

BASELINE=1 reads the sources at BASE_REF: the install block downloads all three
files from onlyoffice.github.io and start-up keeps the stale folder - FAILS.

NOT claimed here (checked live in an APFS copy of the test app, see the
report): the CEF call path, the real store download of the plugin package
(which is the plugin the user chose - still downloaded, by design), and that a
store plugin runs with the app's API. Plugins that need an API newer than the
one the app ships get the app's.

  RD_REPO=<desktop-sdk checkout>  (default ../../desktop-sdk)
  BASELINE=1                      read sources at BASE_REF; must FAIL
  BASE_REF                        default 793de03c^ (the parent of the fix)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '793de03c^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
API = ('plugins.js', 'plugins-ui.js', 'plugins.css')

failures = 0


def check(name, ok, detail=''):
    global failures
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok or not detail else ': ' + detail))
    if not ok:
        failures += 1


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def list_sources():
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'ls-tree', '-r', '--name-only', BASE_REF, SRC],
                           capture_output=True, text=True, check=True)
        names = r.stdout.split()
    else:
        names = []
        for root, _, files in os.walk(os.path.join(REPO, SRC)):
            for f in files:
                names.append(os.path.relpath(os.path.join(root, f), REPO))
    return [n for n in names if re.search(r'\.(cpp|h|mm|js)$', n) and '/cef/' not in n
            and not re.search(r'/cef_\d+/', n)]


def match_brace(text, b):
    """Index of the brace closing the one at text[b] (skips comments, string/char literals)."""
    depth = 0
    i = b
    while i < len(text):
        c = text[i]
        if text.startswith('//', i):
            i = text.find('\n', i)
            continue
        if text.startswith('/*', i):
            i = text.find('*/', i) + 2
            continue
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == "'":
            i += 1
            while text[i] != "'":
                i += 2 if text[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    sys.exit('unbalanced braces')


def block_from(text, start):
    """From the line holding `start` to the brace closing the first '{' after it."""
    a = text.find(start)
    if a < 0:
        sys.exit('not found: %r' % start)
    a = text.rfind('\n', 0, a) + 1
    return text[a:match_brace(text, text.find('{', a)) + 1]


STUBS = r'''
#include <string>
#include <vector>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <filesystem>
namespace fs = std::filesystem;
static std::vector<std::wstring> g_downloads;
namespace NSFile {
struct CFileBinary {
    static bool Exists(const std::wstring& p) { return fs::is_regular_file(fs::path(p)); }
    // core File.cpp: std::remove (Windows: _wremove) - fails on a non-empty directory
    static bool Remove(const std::wstring& p) { return 0 == std::remove(fs::path(p).string().c_str()); }
    static bool Copy(const std::wstring& s, const std::wstring& d) {
        std::error_code ec; fs::copy_file(fs::path(s), fs::path(d), fs::copy_options::overwrite_existing, ec); return !ec; }
    static std::wstring GetTempPath() { return fs::temp_directory_path().wstring(); }
    static std::wstring CreateTempFileWithUniqueName(const std::wstring& dir, const std::wstring& pre) {
        static int n = 0; return dir + L"/" + pre + std::to_wstring(++n) + L".tmp"; }
};
}
namespace NSDirectory {
    static bool Exists(const std::wstring& p) { return fs::is_directory(fs::path(p)); }
    static bool CreateDirectories(const std::wstring& p) { std::error_code ec; fs::create_directories(fs::path(p), ec); return !ec; }
    static void CreateDirectory(const std::wstring& p) { CreateDirectories(p); }
    static void DeleteDirectory(const std::wstring& p, bool deleteRoot = true) { std::error_code ec; fs::remove_all(fs::path(p), ec); if (!deleteRoot) CreateDirectories(p); }
    static bool CopyDirectory(const std::wstring& s, const std::wstring& d, bool r = true) {
        std::error_code ec; fs::create_directories(fs::path(d), ec);
        fs::copy(fs::path(s), fs::path(d), fs::copy_options::recursive | fs::copy_options::overwrite_existing, ec); return !ec; }
}
// "downloads" a marker naming the URL, as a remote host would answer
struct CFileDownloaderWrapper {
    std::wstring u, o;
    CFileDownloaderWrapper(const std::wstring& url, const std::wstring& out) : u(url), o(out) {}
    int DownloadSync() { g_downloads.push_back(u); std::ofstream f{fs::path(o)}; f << "REMOTE "; for (wchar_t c : u) f << (char)c; return 0; }
};
static std::wstring W(const char* s) { std::string a(s); return std::wstring(a.begin(), a.end()); }
'''

INSTALL_MAIN = r'''
int main(int argc, char** argv) {
    std::wstring m_sSystemPlugins = W(argv[1]);
    std::wstring m_sUserPlugins = W(argv[2]);
    @@BLOCK@@
    for (auto& d : g_downloads) { printf("DOWNLOAD "); for (wchar_t c : d) putchar((char)c); putchar('\n'); }
    return 0;
}
'''

STARTUP_MAIN = r'''
struct CSettings { std::wstring system_plugins_path, user_plugins_path; };
struct CManager { CSettings m_oSettings; };
int main(int argc, char** argv) {
    CManager oManager; CManager* pManager = &oManager;
    pManager->m_oSettings.system_plugins_path = W(argv[1]);
    pManager->m_oSettings.user_plugins_path = W(argv[2]);
    @@BLOCK@@
    for (auto& d : g_downloads) { printf("DOWNLOAD "); for (wchar_t c : d) putchar((char)c); putchar('\n'); }
    return 0;
}
'''


def build(work, name, main, block):
    src = os.path.join(work, name + '.cpp')
    with open(src, 'w', encoding='utf-8') as f:
        f.write(STUBS + main.replace('@@BLOCK@@', block))
    exe = os.path.join(work, name)
    r = subprocess.run(['c++', '-std=c++17', '-w', '-o', exe, src], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('compile of %s failed:\n%s' % (name, r.stderr))
    return exe


def fill(d, prefix):
    os.makedirs(d, exist_ok=True)
    for n in API:
        with open(os.path.join(d, n), 'w') as f:
            f.write('/* %s %s */\n' % (prefix, n))


def same_as_app(user, system):
    bad = []
    for n in API:
        u, s = os.path.join(user, 'v1', n), os.path.join(system, 'v1', n)
        if not os.path.exists(u) or open(u, 'rb').read() != open(s, 'rb').read():
            bad.append(n + ' = ' + (open(u).read().strip()[:80] if os.path.exists(u) else '(missing)'))
    return bad


def main():
    print('%s desktop-sdk %s' % ('BASELINE' if BASELINE else 'FIX', BASE_REF if BASELINE else REPO))
    renderer = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')
    install = block_from(renderer, 'else if (name == "PluginInstall")')
    tail = install[:install.find('// send to editor')]
    k = tail.rfind('if (true)')
    if k < 0:
        sys.exit('no post-install "if (true)" block in PluginInstall')
    install_block = tail[k:match_brace(tail, tail.find('{', k)) + 1]
    startup_block = block_from(read(SRC + 'cefapplication.cpp'), '// user plugins')

    work = tempfile.mkdtemp(prefix='rd1664v1-')
    try:
        exe_i = build(work, 'install', INSTALL_MAIN, install_block)
        exe_s = build(work, 'startup', STARTUP_MAIN, startup_block)

        system = os.path.join(work, 'app', 'sdkjs-plugins')
        fill(os.path.join(system, 'v1'), 'APP pinned')
        for n in ('pluginBase.js', 'plugins.css'):
            open(os.path.join(system, n), 'w').write('/* app %s */\n' % n)

        # 1. install, user v1 present (start-up made it) and missing
        for label, prep in (('user v1/ present', True), ('user v1/ missing', False)):
            user = os.path.join(work, 'user-' + str(prep), 'sdkjs-plugins')
            os.makedirs(user)
            if prep:
                fill(os.path.join(user, 'v1'), 'APP pinned')
            out = subprocess.run([exe_i, system, user], capture_output=True, text=True, check=True).stdout
            dl = [l for l in out.splitlines() if l.startswith('DOWNLOAD')]
            check('PluginInstall (%s) downloads nothing' % label, not dl, '; '.join(dl))
            bad = same_as_app(user, system)
            check('PluginInstall (%s): user v1/ is the app\'s v1/' % label, not bad, '; '.join(bad))

        # 2. start-up with a stale v1/ left by an earlier download
        user = os.path.join(work, 'user-stale', 'sdkjs-plugins')
        fill(os.path.join(user, 'v1'), 'REMOTE stale download of')
        subprocess.run([exe_s, system, user], capture_output=True, text=True, check=True)
        bad = same_as_app(user, system)
        check('start-up replaces a stale user v1/ with the app\'s', not bad, '; '.join(bad))
        check('start-up still copies pluginBase.js', os.path.exists(os.path.join(user, 'pluginBase.js')))

        # ... and keeps the user's v1/ when the app has none to put back
        bare = os.path.join(work, 'app-bare', 'sdkjs-plugins')
        os.makedirs(bare)
        user = os.path.join(work, 'user-keep', 'sdkjs-plugins')
        fill(os.path.join(user, 'v1'), 'USER only copy of')
        subprocess.run([exe_s, bare, user], capture_output=True, text=True, check=True)
        check('start-up keeps user v1/ when the app has no v1/',
              all(os.path.exists(os.path.join(user, 'v1', n)) for n in API))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 3. no run-time source of the plugin API anywhere in the library
    hits = []
    for rel in list_sources():
        for i, line in enumerate(read(rel).splitlines(), 1):
            if re.search(r'https?://[^"\s]*sdkjs-plugins/v1/?"', line):
                hits.append('%s:%d' % (rel, i))
    check('no source names a sdkjs-plugins/v1/ URL to fetch', not hits, ', '.join(hits))

    print('PASS' if not failures else 'FAILED (%d)' % failures)
    sys.exit(1 if failures else 0)


main()
