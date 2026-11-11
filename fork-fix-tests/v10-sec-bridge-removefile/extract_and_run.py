#!/usr/bin/env python3
"""
ONLYOFFICE 10.0 security backport (desktop-sdk 1ec765ed "Fix permissions for
dangerous functions"), the parts that apply to our tree:

- "Fixed arbitrary file deletion from a PDF document": window.AscDesktopEditor
  .RemoveFile(path) (client_renderer_wrapper.cpp, Execute, name == "RemoveFile")
  deleted whatever path it was handed. Our #1664 work already keeps PDF form
  JavaScript in QuickJS (no bridge) and keeps the method from plugin-scheme
  frames, but editor and cloud-portal frames still had it. It now refuses a
  path g_pLocalResolver->CheckNoFont does not allow, as upstream does.
- "Fixed document crash when calling AscDesktopEditor.execCommand() and
  AscDesktopEditor.PluginInstall() without arguments": both read
  arguments[0] / *arguments.begin() of an empty CefV8ValueList.

This lifts the REAL "RemoveFile" branch of Execute by brace matching and runs it
against stubs (a resolver that allows one folder, a file layer that records
removals), and the REAL opening of the "execCommand" and "PluginInstall"
branches - every statement up to and including the first one that touches the
argument list - against an argument list that aborts on an out-of-range read,
as CEF's does.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read the source at BASE_REF; must FAIL
  BASE_REF                         default: the parent of the fix commit

NOT claimed: which folders the real CLocalFilesResolver allows (the existing
issue-1664-file-access test covers CheckNoFont); that the GUI app was run; the
rest of execCommand/PluginInstall. Compiled on macOS and syntax-checked for
Linux separately (see the report).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '439fe179^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'ChromiumBasedEditors/lib/src/cefwrapper/client_renderer_wrapper.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth, i = 0, b
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


def head_until_args(blk, needle):
    """the branch up to the end of the first statement that reads `needle`"""
    at = blk.find(needle)
    if at < 0:
        sys.exit('%r not in the branch' % needle)
    end = blk.find(';', at)
    return blk[:end + 1] + '\n\t\t\t\tputs("READ-ARGS"); return true;\n\t\t\t}'


src = read(REL)
remove = block(src, 'else if (name == "RemoveFile")')
assert 'Remove(' in remove, 'extracted RemoveFile branch looks wrong'
execcmd = head_until_args(block(src, 'else if (name == "execCommand")'), 'arguments[0]')
install = head_until_args(block(src, 'else if (name == "PluginInstall")'), 'arguments.begin()')

harness = r'''
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <set>
#include <iostream>
#define U_TO_UTF8(s) std::string((s).begin(), (s).end())
struct CefStr { std::wstring w; std::string ToString() const { return U_TO_UTF8(w); }
	std::wstring ToWString() const { return w; } operator std::wstring() const { return w; } };
struct Val { std::wstring s; CefStr GetStringValue() const { return CefStr{s}; } bool IsInt() const { return false; } };
typedef const Val* ValPtr;
struct ArgList {
	std::vector<ValPtr> v;
	size_t size() const { return v.size(); }
	ValPtr operator[](size_t i) const { if (i >= v.size()) { puts("CRASH: out-of-range argument read"); exit(3); } return v[i]; }
	struct It { const ArgList* l; size_t i; ValPtr operator*() const { if (i >= l->v.size()) { puts("CRASH: out-of-range argument read"); exit(3); } return l->v[i]; } };
	It begin() const { return It{this, 0}; }
};
std::set<std::wstring> g_removed;
namespace NSFile { struct CFileBinary {
	static bool Exists(const std::wstring&) { return true; }
	static bool Remove(const std::wstring& s) { g_removed.insert(s); return true; } }; }
struct Resolver { bool CheckNoFont(const std::wstring& s) { return 0 == s.find(L"/allowed/") && std::wstring::npos == s.find(L".."); } };
Resolver g_resolver; Resolver* g_pLocalResolver = &g_resolver;
static void LogFileAccessDenied(const char*, const std::wstring&) {}
// what the opening of the PluginInstall branch touches before it reads the arguments
struct CPluginsManager { std::wstring m_strDirectory, m_strUserDirectory; };
static std::wstring m_sSystemPlugins, m_sUserPlugins;

static bool run(const std::string& name, const ArgList& arguments)
{
	if (false) {}
	REMOVE
	EXEC
	INSTALL
	return false;
}
int main(int argc, char** argv)
{
	std::string what = argv[1];
	if (what == "remove") {
		Val a{L"/allowed/IMG1.png"}, b{L"/Users/u/Documents/thesis.docx"};
		ArgList l1; l1.v.push_back(&a); run("RemoveFile", l1);
		ArgList l2; l2.v.push_back(&b); run("RemoveFile", l2);
		ArgList l3; run("RemoveFile", l3);
		printf("removed-allowed=%d removed-outside=%d\n", (int)g_removed.count(a.s), (int)g_removed.count(b.s));
	} else {
		ArgList empty; run(what, empty);
		printf("returned\n");
	}
	return 0;
}
'''.replace('REMOVE', remove).replace('EXEC', execcmd).replace('INSTALL', install)

fails = 0
with tempfile.TemporaryDirectory() as work:
    cpp = os.path.join(work, 'h.cpp')
    open(cpp, 'w').write(harness)
    exe = os.path.join(work, 'h')
    r = subprocess.run(['c++', '-std=c++11', '-w', '-o', exe, cpp], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('compile failed:\n' + r.stderr)

    def run(arg):
        p = subprocess.run([exe, arg], capture_output=True, text=True)
        return (p.stdout + p.stderr).strip()

    out = run('remove')
    ok = 'removed-allowed=1 removed-outside=0' in out
    print(('ok   ' if ok else 'FAIL ') + 'RemoveFile deletes a file in an allowed folder, refuses one outside: ' + out)
    fails += not ok
    for name in ('execCommand', 'PluginInstall'):
        out = run(name)
        ok = 'returned' in out and 'CRASH' not in out
        print(('ok   ' if ok else 'FAIL ') + '%s() with no arguments returns without reading them: %s' % (name, out.replace('\n', ' | ')))
        fails += not ok

print('%d check(s) FAILED' % fails if fails else 'all checks passed')
sys.exit(1 if fails else 0)
