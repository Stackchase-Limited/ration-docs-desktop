#!/usr/bin/env python3
"""
desktop-sdk: CAscClientHandler::OnFileDialog (cefview.cpp) had not been called since
the move to CEF 102+ (ONLYOFFICE 7.4, 2023).

CEF 102 dropped the `int selected_accept_filter` parameter from
CefDialogHandler::OnFileDialog (and from CefFileDialogCallback::Continue). The
Continue() call sites were updated (#ifndef CEF_VERSION_ABOVE_102), the handler
was not, and it had no `override`, so it compiled as a new, unrelated virtual.
GetDialogHandler() returns the client handler, CEF calls the base-class
OnFileDialog, the base returns false, and Chromium's own dialog ran for every
<input type=file> on every platform. (Visible in the binary: the mangled name of
CAscClientHandler::OnFileDialog had an extra `i` parameter and no vtable thunk.)

What the handler is for (never on macOS - its body is #ifndef _MAC):
  Windows+Linux  an open/open-multiple chooser with no accept filter (cloud portal
                 "Upload" buttons) goes to the app's own dialog, filter "any",
                 starting in the app's last-used folder (2018, "crash of the
                 renderer after uploading files to the cloud").
  Linux          image choosers go to the app's image dialog (bug 39786); with
                 DONT_USE_NATIVE_FILE_DIALOGS every open and folder chooser goes to
                 the app, which honours --xdg-desktop-portal / --native-file-dialog
                 (Wayland/Flatpak) instead of Chromium's in-process GTK dialog.
Revived as it was meant to work, plus:
  - a list of image MIME types (the OCR plugin's accept=image/bmp,image/jpeg,...)
    counts as "images" too; it used to fall through to "any";
  - a chooser the app never answered is cancelled when the next one starts,
    so it cannot block the page or take a later OpenFilenameDialog result;
  - no listener -> Chromium's dialog instead of a NULL dereference (Linux path);
  - files picked for an <input type=file> are NOT added to the local-files
    resolver: Chromium reads them itself and gives them to that page only,
    whereas the resolver would let any cloud frame fetch them by path later.

How: the REAL `virtual bool OnFileDialog(...)` declaration with its default body
is extracted from CEF 109's include/cef_dialog_handler.h (mac, linux and windows
copies must agree), the REAL CAscClientHandler::OnFileDialog and the REAL
`m_pFileDialogCallback` branch of CCefView::Apply are extracted from cefview.cpp
by brace matching, compiled with c++ against minimal stubs of the NSEditorApi
events and the CEF callback, and driven THROUGH A CefDialogHandler* (as CEF calls
it) under three configurations: Windows (neither _MAC nor _LINUX), Linux (_LINUX,
plus DONT_USE_NATIVE_FILE_DIALOGS exactly as cefview.cpp defines it) and macOS
(_MAC and _LINUX, as the mac build defines both).

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read cefview.cpp at BASE_REF; must FAIL
  BASE_REF                         default <fix commit>^ (re-pin after cherry-pick)

NOT claimed: no Windows or Linux build was run; the app-side dialogs (Qt
CEditorTools::getlocalfile, which answers these events) are not exercised here.
On macOS the handler returns false, as before, so the dialog there is still
Chromium's NSOpenPanel - checked in the test app (the handler is now reached).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
BASE_REF = os.environ.get('BASE_REF', '970a438c^')
BASELINE = bool(os.environ.get('BASELINE'))
LIB = 'ChromiumBasedEditors/lib/src/'


def read(rel, at_base=False):
    if at_base:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def brace_block(text, start, frm=0):
    """From the line holding `start` (searched from frm) to its matching closing brace."""
    a = text.find(start, frm)
    if a < 0:
        sys.exit('anchor not found: %r' % start)
    a = text.rfind('\n', 0, a) + 1
    b = text.find('{', a)
    depth, i = 0, b
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == "'":
            i += 1
            while text[i] != "'":
                i += 2 if text[i] == '\\' else 1
        elif c == '/' and text.startswith('//', i):
            i = text.find('\n', i)
            continue
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


# ---- CEF 109's real declaration (the contract CEF calls) ----
decls = []
for plat in ('mac', 'linux', 'windows'):
    h = read(LIB + 'cef/%s/include/cef_dialog_handler.h' % plat)
    cls = brace_block(h, 'class CefDialogHandler : public virtual CefBaseRefCounted')
    d = brace_block(cls, 'virtual bool OnFileDialog(')
    decls.append(re.sub(r'\s+', ' ', d))
if len(set(decls)) != 1:
    sys.exit('CEF headers disagree on OnFileDialog:\n' + '\n'.join(decls))
CEF_DECL = brace_block(read(LIB + 'cef/mac/include/cef_dialog_handler.h'), 'virtual bool OnFileDialog(')

# ---- our code ----
CPP = read(LIB + 'cefview.cpp', BASELINE)
cls_at = CPP.find('class CAscClientHandler')
if cls_at < 0:
    sys.exit('class CAscClientHandler not found')
HANDLER = brace_block(CPP, 'virtual bool OnFileDialog(', cls_at)
DONT_USE = re.search(r'#if defined ?\(_LINUX\) && !defined\(_MAC\)\n#define DONT_USE_NATIVE_FILE_DIALOGS\n#endif\n', CPP)
if not DONT_USE:
    sys.exit('DONT_USE_NATIVE_FILE_DIALOGS block not found in cefview.cpp')
case_at = CPP.find('case ASC_MENU_EVENT_TYPE_DOCUMENTEDITORS_OPENFILENAME_DIALOG:', CPP.find('void CCefView::Apply('))
APPLY_CB = brace_block(CPP, 'if (m_pInternal->m_handler->m_pFileDialogCallback)', case_at)

STUBS = r'''
#include <cstdio>
#include <string>
#include <vector>
#include <locale>
#include <codecvt>
#define OVERRIDE override
#define CEF_VERSION_ABOVE_102
#define CEF_VERSION_ABOVE_86

template<class T> struct CefRefPtr {
	T* p = nullptr;
	CefRefPtr() {}
	CefRefPtr(std::nullptr_t) {}
	CefRefPtr(T* x) : p(x) {}
	T* operator->() const { return p; }
	explicit operator bool() const { return p != nullptr; }
	CefRefPtr& operator=(std::nullptr_t) { p = nullptr; return *this; }
};
struct CefString {
	std::wstring w;
	CefString() {}
	CefString(const char* s) : w(s, s + strlen(s)) {}
	CefString(const std::wstring& s) : w(s) {}
	std::string ToString() const { return std::string(w.begin(), w.end()); }
	std::wstring ToWString() const { return w; }
};
struct CefBrowser {};
enum cef_file_dialog_mode_t { FILE_DIALOG_OPEN = 0, FILE_DIALOG_OPEN_MULTIPLE, FILE_DIALOG_OPEN_FOLDER, FILE_DIALOG_SAVE };

struct CefFileDialogCallback {
	int nCancel = 0, nContinue = 0;
	std::vector<std::wstring> paths;
	void Continue(const std::vector<CefString>& p) { ++nContinue; for (auto& s : p) paths.push_back(s.w); }
	void Cancel() { ++nCancel; }
};

class CefDialogHandler {
public:
	typedef cef_file_dialog_mode_t FileDialogMode;
	virtual ~CefDialogHandler() {}
	/*CEF_DECL*/
};

#define ASC_MENU_EVENT_TYPE_DOCUMENTEDITORS_OPENFILENAME_DIALOG 1001
#define ASC_MENU_EVENT_TYPE_DOCUMENTEDITORS_OPENDIRECTORY_DIALOG 1002
namespace NSEditorApi {
	struct IMenuEventDataBase { virtual ~IMenuEventDataBase() {} };
	struct CAscLocalOpenFileDialog : IMenuEventDataBase {
		int id = -1; bool multi = false; std::wstring filter, path; std::vector<std::wstring> files;
		void put_Id(int v) { id = v; }
		void put_IsMultiselect(bool v) { multi = v; }
		bool get_IsMultiselect() { return multi; }
		void put_Filter(const std::wstring& v) { filter = v; }
		std::wstring get_Path() { return path; }
		std::vector<std::wstring>& get_Files() { return files; }
	};
	struct CAscLocalOpenDirectoryDialog : IMenuEventDataBase {};
	struct CAscCefMenuEvent { int m_nType; IMenuEventDataBase* m_pData = nullptr; CAscCefMenuEvent(int t) : m_nType(t) {} };
	struct CAscCefMenuEventListener {
		std::vector<CAscCefMenuEvent*> events;
		void OnEvent(CAscCefMenuEvent* e) { events.push_back(e); }
	};
}
struct FakeManager {
	NSEditorApi::CAscCefMenuEventListener* listener = nullptr;
	NSEditorApi::CAscCefMenuEventListener* GetEventListener() { return listener; }
	std::vector<std::wstring> resolved;
	void AddFileToLocalResolver(const std::wstring& s) { resolved.push_back(s); }
};
struct FakeView {
	FakeManager* manager = nullptr;
	FakeManager* GetAppManager() { return manager; }
	int GetId() { return 7; }
	NSEditorApi::CAscCefMenuEvent* CreateCefEvent(int t) { return new NSEditorApi::CAscCefMenuEvent(t); }
};

/*DONT_USE*/

class CAscClientHandler : public CefDialogHandler {
public:
	FakeView* m_pParent = nullptr;
	CefRefPtr<CefFileDialogCallback> m_pFileDialogCallback;
	CefRefPtr<CefFileDialogCallback> m_pDirectoryDialogCallback;
	/*HANDLER*/
};

// CCefView::Apply's branch for a pending <input type=file> chooser
struct FakeInternal { CAscClientHandler* m_handler; FakeManager* m_pManager; };
static bool apply_callback_branch(FakeInternal* m_pInternal, NSEditorApi::CAscLocalOpenFileDialog* pData)
{
	do {
		/*APPLY_CB*/
		return false;
	} while (0);
	return true;
}

static int failures = 0;
static void check(bool ok, const char* what) { printf("%s %s\n", ok ? "ok  " : "FAIL", what); if (!ok) ++failures; }

static std::string W(const std::wstring& w) { return std::string(w.begin(), w.end()); }

struct Run {
	FakeManager mgr; NSEditorApi::CAscCefMenuEventListener lis; FakeView view; CAscClientHandler h;
	Run(bool withListener = true) { mgr.listener = withListener ? &lis : nullptr; view.manager = &mgr; h.m_pParent = &view; }
	bool ask(cef_file_dialog_mode_t mode, std::vector<CefString> filters, CefFileDialogCallback* cb) {
		CefDialogHandler* base = &h;   // CEF calls through the CefDialogHandler interface
		return base->OnFileDialog(CefRefPtr<CefBrowser>(), mode, CefString(""), CefString(""), filters, CefRefPtr<CefFileDialogCallback>(cb));
	}
	NSEditorApi::CAscCefMenuEvent* last() { return lis.events.empty() ? nullptr : lis.events.back(); }
	std::string filter() { auto e = last(); return e && e->m_pData ? W(((NSEditorApi::CAscLocalOpenFileDialog*)e->m_pData)->filter) : "<none>"; }
};

int main()
{
#if defined(_MAC)
	const char* plat = "mac";
#elif defined(_LINUX)
	const char* plat = "linux";
#else
	const char* plat = "windows";
#endif
	std::string P(plat);
	bool app = (P != "mac");     // Windows and Linux route to the app; macOS never does
	bool lin = (P == "linux");
	char buf[256];
#define CHECK(c, ...) do { snprintf(buf, sizeof(buf), __VA_ARGS__); std::string s = P + ": " + buf; check((c), s.c_str()); } while (0)

	{ Run r; CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_OPEN, {}, &cb);
	  CHECK(ret == app && (app ? r.filter() == "any" : r.last() == nullptr),
	        "open, no accept filter (portal upload) -> %s (got ret=%d filter=%s)", app ? "app dialog, filter any" : "Chromium dialog", ret, r.filter().c_str()); }

	{ Run r; CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_OPEN, {CefString("image/*")}, &cb);
	  CHECK(ret == lin && (lin ? r.filter() == "images" : r.last() == nullptr),
	        "open, image/* (AI agent attach) -> %s (got ret=%d filter=%s)", lin ? "app images dialog" : "Chromium dialog", ret, r.filter().c_str()); }

	{ Run r; CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_OPEN_MULTIPLE, {CefString("image/bmp"), CefString("image/jpeg"), CefString("image/png")}, &cb);
	  bool multi = r.last() && ((NSEditorApi::CAscLocalOpenFileDialog*)r.last()->m_pData)->multi;
	  CHECK(ret == lin && (lin ? (r.filter() == "images" && multi) : r.last() == nullptr),
	        "open multiple, image/bmp,image/jpeg,image/png (OCR plugin) -> %s (got ret=%d filter=%s)", lin ? "app images dialog, multiselect" : "Chromium dialog", ret, r.filter().c_str()); }

	{ Run r; CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_OPEN, {CefString(".js")}, &cb);
	  CHECK(ret == lin && (lin ? r.filter() == "any" : r.last() == nullptr),
	        "open, .js (AI custom providers) -> %s (got ret=%d filter=%s)", lin ? "app dialog, filter any" : "Chromium dialog", ret, r.filter().c_str()); }

	{ Run r; CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_OPEN_FOLDER, {}, &cb);
	  bool dir = r.last() && r.last()->m_nType == ASC_MENU_EVENT_TYPE_DOCUMENTEDITORS_OPENDIRECTORY_DIALOG;
	  CHECK(ret == lin && dir == lin, "folder chooser -> %s (got ret=%d)", lin ? "app folder dialog" : "Chromium dialog", ret); }

	{ Run r; CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_SAVE, {}, &cb);
	  CHECK(!ret && r.last() == nullptr, "save chooser -> Chromium dialog (got ret=%d)", ret); }

	if (app) {
	  { Run r; CefFileDialogCallback cb1, cb2;
	    r.ask(FILE_DIALOG_OPEN, {}, &cb1);
	    r.ask(FILE_DIALOG_OPEN, {}, &cb2);
	    CHECK(cb1.nCancel == 1 && r.h.m_pFileDialogCallback.p == &cb2,
	          "an unanswered chooser is cancelled when the next starts (cancel=%d, pending is the new one=%d)", cb1.nCancel, r.h.m_pFileDialogCallback.p == &cb2); }

	  { Run r; CefFileDialogCallback cb;
	    r.h.m_pFileDialogCallback = CefRefPtr<CefFileDialogCallback>(&cb);   // a chooser waiting for the app
	    NSEditorApi::CAscLocalOpenFileDialog ans; ans.multi = true; ans.files = {L"/home/u/a.pdf", L"/home/u/b.png"};
	    FakeInternal in{&r.h, &r.mgr};
	    bool handled = apply_callback_branch(&in, &ans);
	    CHECK(handled && cb.nContinue == 1 && cb.paths.size() == 2 && !r.h.m_pFileDialogCallback,
	          "app answer goes to the chooser (handled=%d continue=%d files=%d)", handled, cb.nContinue, (int)cb.paths.size());
	    CHECK(r.mgr.resolved.empty(), "files picked for <input type=file> are not added to the local resolver (added %d)", (int)r.mgr.resolved.size()); }
	}

	if (lin) {
	  Run r(false); CefFileDialogCallback cb;
	  bool ret = r.ask(FILE_DIALOG_OPEN, {CefString(".docx")}, &cb);
	  CHECK(!ret, "no event listener -> Chromium dialog, no crash (got ret=%d)", ret);
	}

	printf("%s: %d failure(s)\n", plat, failures);
	return failures ? 1 : 0;
}
'''


def main():
    cxx = shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
    if not cxx:
        sys.exit('no C++ compiler')
    src = (STUBS.replace('/*CEF_DECL*/', CEF_DECL)
                .replace('/*DONT_USE*/', DONT_USE.group(0))
                .replace('/*HANDLER*/', HANDLER)
                .replace('/*APPLY_CB*/', APPLY_CB))
    src = '#include <cstring>\n' + src
    tmp = tempfile.mkdtemp(prefix='cef-file-dialog-')
    print('%s cefview.cpp from %s' % ('BASELINE' if BASELINE else 'checkout', BASE_REF if BASELINE else REPO))
    rc = 0
    try:
        with open(os.path.join(tmp, 't.cpp'), 'w') as f:
            f.write(src)
        for name, defs in (('windows', []), ('linux', ['-D_LINUX']), ('mac', ['-D_MAC', '-D_LINUX'])):
            exe = os.path.join(tmp, name)
            r = subprocess.run([cxx, '-std=c++17', '-w', '-o', exe, os.path.join(tmp, 't.cpp')] + defs,
                               capture_output=True, text=True)
            if r.returncode != 0:
                print('%s: compile failed\n%s' % (name, r.stderr[-3000:]))
                rc = 1
                continue
            r = subprocess.run([exe], capture_output=True, text=True)
            sys.stdout.write(r.stdout)
            rc |= r.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('PASS' if rc == 0 else 'FAIL')
    return rc


if __name__ == '__main__':
    sys.exit(main())
