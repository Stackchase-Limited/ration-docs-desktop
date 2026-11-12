#!/usr/bin/env python3
"""
RD-0030 - file names put into executed JavaScript without escaping (our finding).

desktop-sdk src/cefwrapper/client_renderer_wrapper.cpp builds JS source text from
file paths in three renderer message handlers and runs it with ExecuteJavaScript:

 - "set_drop_files" (a file dragged over the window; cefview.cpp OnDragEnter):
   window.AscDesktopEditor.SetDropFiles(["<path>", ...]) in EVERY frame of the
   browser. The path was pasted in raw. On Linux and macOS a file name may contain
   '"' (and '\\', newlines), so such a name made the script a syntax error (the
   drop list was not updated), and a crafted name - e.g. one in a downloaded
   archive - closed the literal and ran its own code in the start page / editor
   frame, which has the AscDesktopEditor bridge.
 - "onlocaldocument_onaddimage" (Insert image from file) and
   "on_save_filename_dialog" (path from the save dialog): '\\' was escaped but
   '"' was not, same defect.

Fix: all three use the file's existing CAscDragDrop::EscapeJSString (\\\\, \\",
\\r, \\n, U+2028/2029), added for #905's drop event.

This slices the REAL handler bodies and the REAL CAscDragDrop class from
client_renderer_wrapper.cpp, compiles them with minimal CEF stubs (the frame
records the script it is asked to run) and core's real NSStringUtils::string_replace,
then runs each generated script in node with a fake window and checks what the
JS callback received, and that a crafted name did not run code.

Claimed: the generated scripts parse and deliver the exact path for names with
'"', '\\', newlines, U+2028 and an injection attempt; no injected code runs.
NOT claimed: the native drag hand-off (CEF OnDragEnter / Qt drop) or the save /
open dialogs themselves; no Linux app build here (Docker unavailable), so the
real Linux GUI drop is unverified.

  python3 fork-fix-tests/rd-0030-js-file-name-quoting/extract_and_run.py
  RD_REPO=<desktop-sdk checkout>  (default ../../desktop-sdk)
  RD_CORE=<core checkout>         (default ../../core; read only: string_replace)
  BASELINE=1                      reads desktop-sdk sources from BASE_REF; must FAIL.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '1fea875f^')
BASELINE = bool(os.environ.get('BASELINE'))

RENDER = 'ChromiumBasedEditors/lib/src/cefwrapper/client_renderer_wrapper.cpp'


def read(rel, repo=REPO, baseline=BASELINE):
    if baseline:
        return subprocess.check_output(['git', '-C', repo, 'show', BASE_REF + ':' + rel]).decode('utf-8')
    with open(os.path.join(repo, rel), encoding='utf-8') as f:
        return f.read()


def braces(src, start):
    """src[start:] up to the brace closing the first '{' after start."""
    o = src.index('{', start)
    d = 0
    for i in range(o, len(src)):
        if src[i] == '{':
            d += 1
        elif src[i] == '}':
            d -= 1
            if d == 0:
                return src[start:i + 1]
    raise SystemExit('unbalanced braces')


def body(src, message):
    """the { ... } block of `else if (sMessageName == "<message>")`"""
    at = src.index('else if (sMessageName == "%s")' % message)
    blk = braces(src, at)
    return blk[blk.index('{'):]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('command failed: ' + ' '.join(cmd[:3]))
    return r.stdout


failures = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        failures.append(name)


src = read(RENDER)
cls = braces(src, src.index('\tclass CAscDragDrop\n')) + ';'
assert 'EscapeJSString' in cls, 'sliced the wrong class'
handlers = {m: body(src, m) for m in ('set_drop_files', 'onlocaldocument_onaddimage', 'on_save_filename_dialog')}
assert 'SetDropFiles' in handlers['set_drop_files']
assert 'DesktopOfflineAppDocumentAddImageEnd' in handlers['onlocaldocument_onaddimage']
assert 'on_native_save_filename_dialog' in handlers['on_save_filename_dialog']

core_sb = read('DesktopEditor/common/StringBuilder.cpp', repo=CORE, baseline=False)
sr = braces(core_sb, core_sb.index('void string_replace(std::wstring& text'))

stubs = r'''
#include <string>
#include <vector>
#include <cstdio>
#include <cstdint>
#include <locale>
#include <codecvt>
typedef int64_t int64;
namespace NSStringUtils { ''' + sr + r''' }
namespace NSFile { std::wstring GetFileName(const std::wstring& s) { return s; } }
std::string GetFileBase64(const std::wstring&, int* = NULL) { return ""; }
#define UTF8_TO_U(val) std::wstring((val).begin(), (val).end())
static std::string u8out(const std::wstring& s) { return std::wstring_convert<std::codecvt_utf8<wchar_t>>().to_bytes(s); }
struct CefString {
    std::wstring s; CefString() {} CefString(const std::wstring& v) : s(v) {}
    std::wstring ToWString() const { return s; } std::string ToString() const { return u8out(s); }
    operator std::wstring() const { return s; }
};
template <class T> struct CefRefPtr {
    T* p = nullptr; CefRefPtr() {} CefRefPtr(T* v) : p(v) {}
    T* operator->() const { return p; } T* get() const { return p; } explicit operator bool() const { return p != nullptr; }
};
struct CefListValue {
    std::vector<int> ints; std::vector<std::wstring> strs;
    int GetInt(size_t i) { return ints[i]; }
    CefString GetString(size_t i) { return CefString(strs[i]); }
    size_t GetSize() { return strs.size(); }
};
struct CefProcessMessage {
    CefListValue args;
    CefRefPtr<CefListValue> GetArgumentList() { return CefRefPtr<CefListValue>(&args); }
    CefRefPtr<CefProcessMessage> Copy() { return CefRefPtr<CefProcessMessage>(new CefProcessMessage(*this)); }
};
// the frame prints every script it is asked to run, one JSON-ish line each
struct CefFrame {
    std::string GetURL() { return ""; }
    void ExecuteJavaScript(const std::wstring& code, const std::string&, int) { printf("%s\n%c", u8out(code).c_str(), 0); }
    void ExecuteJavaScript(const std::string& code, const std::string&, int) { printf("%s\n%c", code.c_str(), 0); }
};
static CefFrame g_frame;
struct CefBrowser {
    void GetFrameIdentifiers(std::vector<int64>& ids) { ids.push_back(1); }
    CefRefPtr<CefFrame> GetFrame(int64) { return CefRefPtr<CefFrame>(&g_frame); }
};
static CefRefPtr<CefFrame> GetEditorFrame(CefRefPtr<CefBrowser>) { return CefRefPtr<CefFrame>(&g_frame); }
struct CResolver { bool is_init() { return true; } void AddFile(const std::wstring&) {} CResolver* operator->() { return this; } };
static CResolver g_pLocalResolver;
'''

main = stubs + cls + r'''
static bool h_drop(CefRefPtr<CefBrowser> browser, CefRefPtr<CefProcessMessage> message)
''' + handlers['set_drop_files'] + r'''
static bool h_image(CefRefPtr<CefBrowser> browser, CefRefPtr<CefProcessMessage> message)
''' + handlers['onlocaldocument_onaddimage'] + r'''
static bool h_save(CefRefPtr<CefBrowser> browser, CefRefPtr<CefProcessMessage> message)
''' + handlers['on_save_filename_dialog'] + r'''
static std::wstring u8in(const char* s) { return std::wstring_convert<std::codecvt_utf8<wchar_t>>().from_bytes(s); }
int main(int argc, char** argv)
{
    // argv: which path...
    std::string which = argv[1];
    CefBrowser b; CefRefPtr<CefBrowser> browser(&b);
    CefProcessMessage m; CefRefPtr<CefProcessMessage> pm(&m);
    if (which == "save") m.args.strs.push_back(L"");
    for (int i = 2; i < argc; i++) m.args.strs.push_back(u8in(argv[i]));
    if (which == "drop") h_drop(browser, pm);
    else if (which == "image") h_image(browser, pm);
    else h_save(browser, pm);
    return 0;
}
'''

js_runner = r'''
// runs each generated script against a fake window; reports what the callbacks got
const scripts = require('fs').readFileSync(process.argv[2], 'utf8').split('\n\0').filter(s => s.length);
const res = { errors: [], got: [], injected: false };
const window = {
  AscDesktopEditor: { SetDropFiles: a => res.got.push(a) },
  DesktopOfflineAppDocumentAddImageEnd: p => res.got.push(p),
  on_native_save_filename_dialog: p => res.got.push(p),
};
const pwn = () => { res.injected = true; };
for (const s of scripts) {
  try { new Function('window', 'pwn', s)(window, pwn); } catch (e) { res.errors.push(String(e)); }
}
console.log(JSON.stringify(res));
'''

tmp = tempfile.mkdtemp(prefix='rd0030-')
try:
    with open(os.path.join(tmp, 'h.cpp'), 'w') as f:
        f.write(main)
    with open(os.path.join(tmp, 'run.js'), 'w') as f:
        f.write(js_runner)
    run(['c++', '-std=c++17', '-Wno-deprecated-declarations', os.path.join(tmp, 'h.cpp'), '-o', os.path.join(tmp, 'h')])

    def go(which, paths):
        out = subprocess.run([os.path.join(tmp, 'h'), which] + paths, capture_output=True).stdout
        p = os.path.join(tmp, 'code.js')
        with open(p, 'wb') as f:
            f.write(out)
        return json.loads(run(['node', os.path.join(tmp, 'run.js'), p]))

    names = [
        ('plain', '/home/u/report.docx'),
        ('double quote', '/home/u/my "final" report.docx'),
        ('backslash', '/home/u/back\\slash.docx'),
        ('newline', '/home/u/two\nlines.docx'),
        ('U+2028', '/home/u/sep x.docx'),
        ('injection', '/home/u/x");pwn();("'),
        ('injection 2', '/home/u/x"]);pwn();(["'),
    ]
    for label, path in names:
        r = go('drop', [path])
        ok = not r['errors'] and not r['injected'] and r['got'] == [[path]]
        check('drop ' + label + ': SetDropFiles gets the exact path', ok, json.dumps(r))
    r = go('drop', [p for _, p in names])
    check('drop of all names at once', not r['errors'] and not r['injected'] and r['got'] == [[p for _, p in names]], json.dumps(r))

    for which, label in (('image', 'insert image'), ('save', 'save dialog')):
        for nl, path in (('double quote', '/home/u/my "final" pic.png'), ('injection', '/home/u/x");pwn();("'),
                         ('backslash', '/home/u/back\\slash.png')):
            r = go(which, [path])
            ok = not r['errors'] and not r['injected'] and r['got'] == [path]
            check(label + ' ' + nl + ': callback gets the exact path', ok, json.dumps(r))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
sys.exit(1 if failures else 0)
