#!/usr/bin/env python3
"""
#1664 (security follow-up) - the AI agent's tool calls read any file the model
named, and saveAndOpen's callback never ran.

1. window.AscDesktopEditor.callToolFunction (desktop-sdk
   client_renderer_wrapper.cpp) handed the model's arguments straight to
   CAITools::callFunc (lib/tools). file_content_reader returned the text of ANY
   path (plain text read as is, everything else through x2t),
   form_field_analyser / form_field_filler opened any document, and
   folder_content_reader listed any folder recursively. The agent reads
   documents, web search results and MCP output, so text in any of them can
   tell the model to read ~/.ssh/id_rsa or a browser profile and pass it on
   (web search, an MCP server, its reply). The chat's "Allow" button is page
   UI that "Allow always" switches off per tool, and any onlyoffice:// plugin
   could call the function itself.

   Now: the native function is _callToolFunction, answered only for the bundled
   AI agent's page (bridge_access.h IsProcessFrame, as _createProcess). A call
   that names a file runs at once only for what the user gave the agent - a file
   picked in a dialog or dropped (the resolver), attached to the chat
   (_convertFileExternal from the agent), or written by an earlier tool call
   (form_field_filler's filled form). Anything else is sent to the browser
   process ("ai_tool_file_confirm"), which checks the frame again and asks the
   user in the same native dialog as the MCP command confirm
   (external_process_confirm.h CQueue::RequestFile, "Don't Allow" the default);
   a yes is remembered for that path until the application quits, never on disk.
   Paths with "..", relative ones and file:// URLs of another host are refused.
   The bridge script turns the deferred answer into a Promise, so the agent's
   DesktopEditor.ts (which awaits) and its composer's synchronous
   recent_files_reader call both keep working unchanged.

2. _saveAndOpen (client_renderer_wrapper.cpp, the AI agent's "save the chat as
   docx") evaluated "(function(){ if (...) ... = 0; }\\n counter++; ...})()" -
   the "}" closed the function early, a SyntaxError, so the callback was never
   registered and the conversion result went to converter 1: nobody, or a
   pending attachment conversion that then received the saved document. The
   agent's callbacks (AssistantMessage.tsx, useThreadsStore.ts) had never run,
   and logged "Conversion error" on success (code 0); they now log on a
   non-zero code, in src and in the rebuilt deploy bundle.

This compiles the REAL tools/tool_paths.h (with the real json.hpp and
file_access.h), the REAL CAITools::getPathArgument/getOutputFile/getRefusal
(tools.cpp) and the REAL renderer helpers AIToolGivenFiles, AddAIToolGivenFile,
the AIToolCallCheck enum, CheckAIToolCall and RunAIToolFunction (taken from
client_renderer_wrapper.cpp by brace matching) against stubs (resolver,
callFunc), and runs a table of tool calls; compiles the REAL
external_process_confirm.h against stub CEF objects and drives RequestFile;
runs the REAL injected callToolFunction wrapper and the REAL saveAndOpen eval
code in node; and checks the wiring.

BASELINE=1 reads the sources at BASE_REF: callToolFunction runs every call at
once (its block taken from the real source: no check before tools.callFunc), so
the ~/.ssh, cookie and folder rows FAIL, there is no RequestFile, and the
saveAndOpen code is a SyntaxError.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read sources at BASE_REF; must FAIL
  BASE_REF                         default <fix commit>^ (the parent of the fix)

NOT claimed here (needs a GUI check in the test app): the real CEF frame tree
and message round trip, the NSAlert / QMessageBox shown, and that x2t then
converts the allowed file. The resolver is a stub (IsFileFromDialog compares
NormalizePath'ed paths, as the real CorrectPath does). Symbolic links inside a
given path are followed (see issue-1664-symlinks).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'f86491b2^')
BASELINE = bool(os.environ.get('BASELINE'))
LIB = 'ChromiumBasedEditors/lib/'
SRC = LIB + 'src/'


def read(rel, missing_ok=False):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            if missing_ok:
                return None
            sys.exit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    p = os.path.join(REPO, rel)
    if missing_ok and not os.path.exists(p):
        return None
    return open(p, encoding='utf-8').read()


def brace_block(text, start):
    """From the line holding `start` to its matching closing brace."""
    a = text.find(start)
    if a < 0:
        return None
    a = text.rfind('\n', 0, a) + 1
    b = text.find('{', a)
    depth = 0
    i = b
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
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


def compile_exe(work, name, src):
    with open(os.path.join(work, name + '.cpp'), 'w', encoding='utf-8') as f:
        f.write(src)
    exe = os.path.join(work, name)
    r = subprocess.run(['c++', '-std=c++11', '-Wall', '-Wno-unused-function', '-I', work, '-o', exe,
                        os.path.join(work, name + '.cpp')], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('compile of %s failed:\n%s' % (name, r.stderr[:6000]))
    return exe


def unescape_c(s):
    """The text of a C++ string literal body whose lines end in "\\n\\" continuations."""
    s = s.replace('\\\n', '')
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            out.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\', "'": "'"}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


HOME = '/Users/u'
PICKED = HOME + '/Documents/report.docx'        # chosen in the composer's "Add local file" dialog
ATTACHED = HOME + '/Documents/budget.xlsx'      # a recent file attached from the composer's menu
FILLED = '/var/folders/x/T/IMG1234.pdf'         # what form_field_filler wrote

# (description, tool, arguments, expected: run / ask-file / ask-folder / refuse)
CASES = [
    ('read a file picked in a dialog', 'file_content_reader', {'path': PICKED}, 'run'),
    ('read it as html', 'file_content_reader', {'path': PICKED, 'format': 'html'}, 'run'),
    ('read it by file:// URL', 'file_content_reader', {'path': 'file://' + PICKED}, 'run'),
    ('read an attached recent file', 'file_content_reader', {'path': ATTACHED}, 'run'),
    ('analyse the picked form', 'form_field_analyser', {'document': PICKED}, 'run'),
    ('fill the picked form', 'form_field_filler', {'document': PICKED, 'fields': {'Name': 'A'}}, 'run'),
    ('read back the filled form', 'file_content_reader', {'path': FILLED}, 'run'),
    ('a form at a web address', 'form_field_analyser', {'document': 'https://example.com/form.pdf'}, 'run'),
    ('list "Documents"', 'folder_content_reader', {'folder': 'Documents'}, 'run'),
    ('list "Desktop"', 'folder_content_reader', {'folder': 'Desktop'}, 'run'),
    ('recent files list', 'recent_files_reader', {}, 'run'),
    ('generate a document', 'generate_docx', {'description': 'x'}, 'run'),
    ('open a file in an editor tab (nothing returned)', 'file_opener', {'path': HOME + '/a.docx'}, 'run'),
    ('no path given (the tool answers)', 'file_content_reader', {}, 'run'),
    ('arguments that are not JSON (the tool answers)', 'file_content_reader', 'not json', 'run'),
    # the user is asked
    ('read ~/.ssh/id_rsa', 'file_content_reader', {'path': HOME + '/.ssh/id_rsa'}, 'ask-file'),
    ('read ~/.ssh/id_rsa by file:// URL', 'file_content_reader', {'path': 'file:///Users/u/.ssh/id_rsa'}, 'ask-file'),
    ('read a browser profile\'s Cookies', 'file_content_reader',
     {'path': HOME + '/Library/Application Support/Google/Chrome/Default/Cookies'}, 'ask-file'),
    ('read a document not given to the agent', 'file_content_reader', {'path': HOME + '/Documents/secret.docx'}, 'ask-file'),
    ('the picked file\'s sibling', 'file_content_reader', {'path': HOME + '/Documents/report.docx.bak'}, 'ask-file'),
    ('analyse an unopened document', 'form_field_analyser', {'document': HOME + '/Documents/contract.pdf'}, 'ask-file'),
    ('fill an unopened document', 'form_field_filler', {'document': HOME + '/Documents/contract.pdf', 'fields': {}}, 'ask-file'),
    ('list ~/.ssh', 'folder_content_reader', {'folder': HOME + '/.ssh'}, 'ask-folder'),
    ('list the home folder', 'folder_content_reader', {'folder': HOME}, 'ask-folder'),
    ('list a Windows folder', 'folder_content_reader', {'folder': 'C:\\Users\\u\\AppData'}, 'ask-folder'),
    # refused outright
    ('".." out of a given folder', 'file_content_reader', {'path': HOME + '/Documents/../.ssh/id_rsa'}, 'refuse'),
    ('a relative path', 'file_content_reader', {'path': '.ssh/id_rsa'}, 'refuse'),
    ('a file:// URL of another host', 'file_content_reader', {'path': 'file://server/share/x.docx'}, 'refuse'),
    ('an escaped NUL', 'file_content_reader', {'path': 'file:///Users/u/report.docx%00.txt'}, 'refuse'),
]

STUBS = r'''
#include <string>
#include <vector>
#include <map>
#include <set>
#include <cstdio>
static std::wstring FromUtf8(const std::string& s) { return std::wstring(s.begin(), s.end()); }
#define UTF8_TO_U(s) FromUtf8(s)
#include "src/file_access.h"
#include "tools/tools.h"
#include "tools/tool_paths.h"
// the resolver: files picked in a dialog or dropped (CLocalFilesResolver::IsFileFromDialog)
struct CResolverStub {
	std::set<std::wstring> files;
	bool IsFileFromDialog(const std::wstring& s) { return files.count(NSFileAccess::NormalizePath(s)) > 0; }
};
struct CResolverPtr {
	CResolverStub* p; bool is_init() { return p != 0; } CResolverStub* operator->() { return p; }
};
static CResolverStub g_resolver;
static CResolverPtr g_pLocalResolver = { &g_resolver };
// the tools themselves are not run: form_field_filler answers as the real one does
static std::string g_calls;
CAITools::CAITools() : m_funcs(0) {}
CAITools::~CAITools() {}
CAITools& CAITools::getInstance() { static CAITools t; return t; }
std::string CAITools::callFunc(const std::string& name, const std::string& arg, CAIToolsHelper* helper)
{
	g_calls += name + ";";
	if (name == "form_field_filler")
		return "{\"role\":\"tool\",\"status\":\"success\",\"document\":\"@@FILLED@@\",\"toolSystemType\":\"file\",\"toolSystemResult\":\"@@FILLED@@\"}";
	return "{\"role\":\"tool\",\"status\":\"success\"}";
}
@@TOOLS_CPP@@
struct CAscEditorNativeV8Handler : public CAIToolsHelper {
	virtual void OpenTemplate(const std::wstring&, const std::wstring&) {}
	virtual void OpenFile(const std::wstring&) {}
	virtual std::vector<CRecentFileInfo> GetRecents() { return std::vector<CRecentFileInfo>(); }
	virtual void ExecuteJS(const std::string&) {}
@@FUNCS@@
};
int main()
{
	CAscEditorNativeV8Handler h;
	g_resolver.files.insert(NSFileAccess::NormalizePath(L"@@PICKED@@"));
	CAscEditorNativeV8Handler::AddAIToolGivenFile(L"@@ATTACHED@@"); // what _convertFileExternal from the agent does
	char line[16384];
	while (fgets(line, sizeof(line), stdin))
	{
		std::string s(line); if (!s.empty() && s[s.length() - 1] == '\n') s.erase(s.length() - 1);
		std::string name = s.substr(0, s.find('\t')), args = s.substr(s.find('\t') + 1);
		std::string path;
		int n = CAscEditorNativeV8Handler::CheckAIToolCall(name, args, path);
		const char* r = (n == CAscEditorNativeV8Handler::atcRun) ? "run" : (n == CAscEditorNativeV8Handler::atcAskFile) ? "ask-file" :
						(n == CAscEditorNativeV8Handler::atcAskFolder) ? "ask-folder" : (n == CAscEditorNativeV8Handler::atcRefuse) ? "refuse" : "?";
		if (n == CAscEditorNativeV8Handler::atcRun)
			h.RunAIToolFunction(name, args); // records what the tool wrote
		printf("%s\t%s\n", r, path.c_str());
	}
	printf("refusal\t%s\n", CAITools::getInstance().getRefusal("file_content_reader", "no").c_str());
	return 0;
}
'''

# the browser process: the same queue and dialog as the MCP command confirm
QUEUE_STUBS = r'''
#include <string>
#include <vector>
#include <map>
#include <set>
#include <list>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
typedef long long int64;
typedef unsigned char BYTE;
typedef unsigned int DWORD;
template <class T> class CefRefPtr {
public:
	T* p; CefRefPtr() : p(0) {} CefRefPtr(T* x) : p(x) {}
	T* operator->() const { return p; } operator bool() const { return p != 0; }
	bool operator!() const { return p == 0; } T* get() const { return p; }
};
struct CefString {
	std::string s; CefString(const std::string& x) : s(x) {}
	std::string ToString() const { return s; }
	std::wstring ToWString() const { return std::wstring(s.begin(), s.end()); }
};
enum CefProcessId { PID_BROWSER, PID_RENDERER };
struct CefListValue {
	std::vector<std::string> v; std::map<size_t, int> ints; std::map<size_t, bool> bools;
	size_t GetSize() { return v.size(); }
	int GetInt(size_t i) { return ints[i]; }
	CefString GetString(size_t i) { return CefString(v[i]); }
	void SetInt(size_t i, int x) { if (v.size() <= i) v.resize(i + 1); ints[i] = x; }
	void SetBool(size_t i, bool x) { if (v.size() <= i) v.resize(i + 1); bools[i] = x; }
	void SetString(size_t i, const std::string& x) { if (v.size() <= i) v.resize(i + 1); v[i] = x; }
};
struct CefProcessMessage {
	std::string name; CefListValue args;
	static CefRefPtr<CefProcessMessage> Create(const std::string& n) { CefProcessMessage* m = new CefProcessMessage(); m->name = n; return m; }
	CefListValue* GetArgumentList() { return &args; }
};
static std::vector<std::string> g_replies; // "message:token=allowed"
struct CefFrame {
	std::string url, name; CefFrame* parent; int64 id;
	CefString GetURL() { return CefString(url); }
	CefString GetName() { return CefString(name); }
	CefRefPtr<CefFrame> GetParent() { return CefRefPtr<CefFrame>(parent); }
	int64 GetIdentifier() { return id; }
	void SendProcessMessage(CefProcessId, CefRefPtr<CefProcessMessage> m) {
		char b[256]; snprintf(b, sizeof(b), "%s:%d=%d", m->name.c_str(), m->args.ints[0], (int)m->args.bools[1]); g_replies.push_back(b);
	}
};
struct CefBrowser {
	std::vector<CefFrame*> frames;
	CefRefPtr<CefFrame> GetFrame(int64 id) { for (size_t i = 0; i < frames.size(); ++i) if (frames[i]->id == id) return frames[i]; return CefRefPtr<CefFrame>(); }
};
namespace NSStringUtils {
	static void string_replaceA(std::string& s, const std::string& a, const std::string& b) {
		for (size_t p = s.find(a); p != std::string::npos; p = s.find(a, p + b.length())) s.replace(p, a.length(), b);
	}
}
#include "applicationmanager_events.h"
static std::string ToUtf8(const std::wstring& w) { return std::string(w.begin(), w.end()); }
static std::wstring FromUtf8(const std::string& s) { return std::wstring(s.begin(), s.end()); }
#define U_TO_UTF8(w) ToUtf8(w)
#define UTF8_TO_U(s) FromUtf8(s)
namespace NSFile {
	struct CFileBinary {
		std::ofstream o;
		static bool ReadAllTextUtf8A(const std::wstring& p, std::string& s) { std::ifstream i(U_TO_UTF8(p).c_str()); if (!i) return false; std::stringstream ss; ss << i.rdbuf(); s = ss.str(); return true; }
		bool CreateFileW(const std::wstring& p) { o.open(U_TO_UTF8(p).c_str(), std::ios::binary | std::ios::trunc); return (bool)o; }
		void WriteFile(const BYTE* d, DWORD n) { o.write((const char*)d, n); }
		void CloseFile() { o.close(); }
	};
	static std::wstring GetDirectoryName(const std::wstring& p) { return p.substr(0, p.rfind(L'/')); }
}
namespace NSDirectory { static bool CreateDirectories(const std::wstring& p) { std::string c = "mkdir -p '" + U_TO_UTF8(p) + "'"; return 0 == system(c.c_str()); } }
struct CefTask { virtual ~CefTask() {} virtual void Execute() = 0; };
#define IMPLEMENT_REFCOUNTING(x)
enum { TID_UI };
static bool CefCurrentlyOn(int) { return true; }
static void CefPostTask(int, CefTask* t) { t->Execute(); delete t; }
struct CListener : public NSEditorApi::CAscCefMenuEventListener {
	std::vector<int> asks; std::vector<std::wstring> titles, texts;
	virtual void OnEvent(NSEditorApi::CAscCefMenuEvent* e) {
		if (e->m_nType == ASC_MENU_EVENT_TYPE_SYSTEM_EXTERNAL_PROCESS_CONFIRM) {
			NSEditorApi::CAscExternalProcessConfirm* d = (NSEditorApi::CAscExternalProcessConfirm*)e->m_pData;
			asks.push_back(d->get_Id()); titles.push_back(d->get_Title()); texts.push_back(d->get_Text());
		}
	}
};
struct CSettings { std::wstring system_plugins_path, user_plugins_path, app_data_path; };
struct CAscApplicationManager {
	CSettings m_oSettings; CListener listener;
	NSEditorApi::CAscCefMenuEventListener* GetEventListener() { return &listener; }
};
#include "external_process_confirm.h"
void NSExternalProcessConfirm::Answer(int a, bool b) { NSExternalProcessConfirm::AnswerImpl(a, b); }
'''

QUEUE_DRIVER = r'''
static CefRefPtr<CefListValue> Args(int token, int kind, const std::string& path)
{
	CefListValue* a = new CefListValue(); a->SetInt(0, token); a->SetInt(1, kind); a->SetString(2, path);
	return a;
}
static std::string Replies() { std::string s; for (size_t i = 0; i < g_replies.size(); ++i) s += (i ? "," : "") + g_replies[i]; g_replies.clear(); return s.empty() ? "-" : s; }

int main(int argc, char** argv)
{
	std::string dir = argv[1];
	CAscApplicationManager man;
	man.m_oSettings.system_plugins_path = UTF8_TO_U(std::string("@@APP@@/editors/sdkjs-plugins"));
	man.m_oSettings.user_plugins_path = UTF8_TO_U(std::string("@@USERP@@"));
	man.m_oSettings.app_data_path = UTF8_TO_U(dir);

	CefFrame start; start.url = "@@START@@"; start.name = ""; start.parent = 0; start.id = 1;
	CefFrame agent; agent.url = "@@AGENT@@"; agent.name = "system_asc"; agent.parent = &start; agent.id = 2;
	CefFrame user; user.url = "@@UPLUGIN@@"; user.name = "system_asc"; user.parent = &start; user.id = 3;
	CefBrowser browser; browser.frames.push_back(&start); browser.frames.push_back(&agent); browser.frames.push_back(&user);

	NSExternalProcessConfirm::CQueue& q = NSExternalProcessConfirm::GetQueue();
	q.RequestFile(&man, 7, &browser, &agent, Args(1, 1, "/Users/u/.ssh/id_rsa"));
	printf("new file: dialogs=%d replies=%s\n", (int)man.listener.asks.size(), Replies().c_str());
	bool bShown = !man.listener.texts.empty() && std::wstring::npos != man.listener.texts.back().find(L"/Users/u/.ssh/id_rsa");
	printf("dialog shows the path: %d, title: %s\n", (int)bShown, man.listener.titles.empty() ? "" : U_TO_UTF8(man.listener.titles.back()).c_str());
	NSExternalProcessConfirm::Answer(man.listener.asks.back(), false);
	printf("Don't Allow: replies=%s\n", Replies().c_str());

	q.RequestFile(&man, 7, &browser, &agent, Args(2, 1, "/Users/u/.ssh/id_rsa"));
	q.RequestFile(&man, 7, &browser, &agent, Args(3, 1, "/Users/u/.ssh/id_rsa"));
	printf("asked again: dialogs=%d replies=%s\n", (int)man.listener.asks.size(), Replies().c_str());
	NSExternalProcessConfirm::Answer(man.listener.asks.back(), true);
	printf("Allow: replies=%s\n", Replies().c_str());
	size_t nBefore = man.listener.asks.size();
	q.RequestFile(&man, 7, &browser, &agent, Args(4, 1, "/Users/u/.ssh/id_rsa"));
	printf("same path again: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	q.RequestFile(&man, 7, &browser, &agent, Args(5, 2, "/Users/u/.ssh/id_rsa"));
	printf("listing it is another question: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	printf("folder title: %s\n", U_TO_UTF8(man.listener.titles.back()).c_str());
	NSExternalProcessConfirm::Answer(man.listener.asks.back(), false);
	Replies();
	std::ifstream store((dir + "/data/external_processes_allowed.txt").c_str());
	printf("written to disk: %d\n", (int)(bool)store);
	nBefore = man.listener.asks.size();
	q.RequestFile(&man, 7, &browser, &user, Args(6, 1, "/Users/u/.ssh/id_rsa"));
	printf("user plugin frame, allowed path: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	NSExternalProcessConfirm::CQueue q2; // the next start of the application
	q2.RequestFile(&man, 7, &browser, &agent, Args(7, 1, "/Users/u/.ssh/id_rsa"));
	printf("after restart: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	return 0;
}
'''

QUEUE_EXPECT = [
    'new file: dialogs=1 replies=-',
    'dialog shows the path: 1, title: Allow the AI agent to read a file?',
    "Don't Allow: replies=ai_tool_file_confirm_result:1=0",
    'asked again: dialogs=2 replies=-',
    'Allow: replies=ai_tool_file_confirm_result:2=1,ai_tool_file_confirm_result:3=1',
    'same path again: dialogs=0 replies=ai_tool_file_confirm_result:4=1',
    'listing it is another question: dialogs=1 replies=-',
    'folder title: Allow the AI agent to list a folder?',
    'written to disk: 0',
    'user plugin frame, allowed path: dialogs=0 replies=ai_tool_file_confirm_result:6=0',
    'after restart: dialogs=1 replies=-',
]

APP = '/Applications/Ration Docs.app/Contents/Resources'
APPU = 'file:///Applications/Ration%20Docs.app/Contents/Resources'
USERP = '/Users/u/Library/Application Support/com.stackchase.rationdocs/data/sdkjs-plugins'
USERPU = 'file:///Users/u/Library/Application%20Support/com.stackchase.rationdocs/data/sdkjs-plugins'
AGENT_GUID = '%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD777%7D'
START = APPU + '/login/index.html?lang=en-EN&portal&desktop=true'
AGENT_START = 'onlyoffice://plugin/' + APPU[7:] + '/editors/sdkjs-plugins/' + AGENT_GUID + '/index.html?lang=en-EN&portal&desktop=true'
UPLUGIN_START = 'onlyoffice://plugin/' + USERPU[7:] + '/%7BCC1664CC-0000-4000-8000-0000000000CC%7D/index.html'

WRAPPER_JS = r'''
const vm = require('vm');
const code = process.argv[process.argv.length - 1];
let pendingCallback = null;
const window = { AscDesktopEditor: {
	_callToolFunction(name, args, cb) {
		if (name === 'recent_files_reader') return '{"files":[]}';   // answered at once
		pendingCallback = cb; return undefined;                     // the user is asked
	} } };
vm.runInNewContext(code, { window, Promise });
const sync = window.AscDesktopEditor.callToolFunction('recent_files_reader');
console.log('sync answer is a string:', typeof sync === 'string' && JSON.parse(sync).files.length === 0);
const later = window.AscDesktopEditor.callToolFunction('file_content_reader', '{"path":"/Users/u/x.docx"}');
console.log('deferred answer is a Promise:', later instanceof Promise);
later.then(r => console.log('Promise resolves with the result:', r === 'RESULT'));
setTimeout(() => pendingCallback('RESULT'), 10);
'''

SAVE_JS = r'''
const vm = require('vm');
const code = process.argv[process.argv.length - 1];
const calls = [];
const window = { AscDesktopEditor: { _saveAndOpenCallback: (c) => calls.push(c) } };
let id;
try { id = vm.runInNewContext(code, { window }); }
catch (e) { console.log('eval:', e.name + ': ' + e.message); process.exit(0); }
console.log('eval: ok, converter id', id);
const conv = window._external_converters && window._external_converters[id];
console.log('callback registered:', typeof conv === 'function');
if (conv) { conv('/Users/u/Documents/chat.docx', 0); console.log('callback got code', calls[0]); }
'''


def main():
    wrapper = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')
    paths_h = read(LIB + 'tools/tool_paths.h', missing_ok=True)
    tools_h = read(LIB + 'tools/tools.h')
    tools_cpp = read(LIB + 'tools/tools.cpp')
    access_h = read(SRC + 'file_access.h', missing_ok=True)
    confirm = read(SRC + 'external_process_confirm.h', missing_ok=True)
    events = read(LIB + 'include/applicationmanager_events.h')
    view = read(SRC + 'cefview.cpp')
    failures = []

    work = tempfile.mkdtemp(prefix='rd1664t-')
    try:
        # 1. the renderer: which tool calls run at once
        print('-- tool calls: run at once / ask the user / refuse --')
        new_block = brace_block(wrapper, 'else if (name == "_callToolFunction")')
        old_block = brace_block(wrapper, 'else if (name == "callToolFunction")')
        if new_block and paths_h is not None:
            os.makedirs(os.path.join(work, 'tools', 'functions', 'internal'))
            os.makedirs(os.path.join(work, 'src'))
            for rel, text in (('tools/tool_paths.h', paths_h), ('tools/tools.h', tools_h), ('src/file_access.h', access_h)):
                with open(os.path.join(work, rel), 'w', encoding='utf-8') as f:
                    f.write(text)
            shutil.copy(os.path.join(REPO, LIB, 'tools/functions/internal/json.hpp'), os.path.join(work, 'tools/functions/internal/json.hpp'))
            tools_funcs = '\n'.join(brace_block(tools_cpp, sig) for sig in (
                'int CAITools::getPathArgument(', 'std::string CAITools::getOutputFile(', 'std::string CAITools::getRefusal('))
            funcs = '\n'.join([
                brace_block(wrapper, 'static std::set<std::wstring>& AIToolGivenFiles()'),
                brace_block(wrapper, 'static void AddAIToolGivenFile('),
                brace_block(wrapper, 'enum AIToolCallCheck') + ';',
                brace_block(wrapper, 'static int CheckAIToolCall('),
                brace_block(wrapper, 'std::string RunAIToolFunction('),
            ])
            src = STUBS.replace('@@TOOLS_CPP@@', tools_funcs).replace('@@FUNCS@@', funcs) \
                .replace('@@PICKED@@', PICKED).replace('@@ATTACHED@@', ATTACHED).replace('@@FILLED@@', FILLED)
            exe = compile_exe(work, 'calls', src)
            stdin = ''.join('%s\t%s\n' % (tool, args if isinstance(args, str) else json.dumps(args)) for _, tool, args, _ in CASES)
            out = subprocess.run([exe], input=stdin, capture_output=True, text=True, check=True).stdout.strip().split('\n')
            got = [line.split('\t')[0] for line in out[:len(CASES)]]
            refusal = json.loads(out[-1].split('\t', 1)[1])
            if refusal.get('role') != 'tool' or refusal.get('status') != 'error' or refusal.get('content') != '':
                failures.append('refusal shape')
            print('refusal the model gets:', json.dumps(refusal))
        else:
            if old_block is None:
                sys.exit('neither _callToolFunction nor callToolFunction found')
            # the old function: anything before tools.callFunc that could stop a call?
            before = old_block[:old_block.find('tools.callFunc(')]
            checks = [w for w in ('Check', 'IsProcessFrame', 'Resolver', 'confirm') if w in before]
            print('old callToolFunction (from the real source): checks before tools.callFunc:', checks or 'none')
            got = ['run' if not checks else '?'] * len(CASES)
        for (desc, tool, args, want), g in zip(CASES, got):
            ok = g == want
            print('%-4s %-50s %-22s %s%s' % ('ok' if ok else 'FAIL', desc, tool, g, '' if ok else '   (want %s)' % want))
            if not ok:
                failures.append(desc)

        # 2. the browser process asks
        print('\n-- browser process: the native dialog for a file --')
        if confirm is None or 'RequestFile(' not in confirm:
            print('FAIL external_process_confirm.h has no RequestFile: nobody asks the user before a tool reads a file')
            failures.append('no RequestFile')
        else:
            qwork = os.path.join(work, 'q')
            os.makedirs(qwork)
            for name, text in (('external_process_confirm.h', confirm), ('applicationmanager_events.h', events),
                               ('bridge_access.h', read(SRC + 'bridge_access.h'))):
                with open(os.path.join(qwork, name), 'w', encoding='utf-8') as f:
                    f.write(text)
            src = QUEUE_STUBS + QUEUE_DRIVER.replace('@@APP@@', APP).replace('@@USERP@@', USERP) \
                .replace('@@START@@', START).replace('@@AGENT@@', AGENT_START).replace('@@UPLUGIN@@', UPLUGIN_START)
            exe = compile_exe(qwork, 'queue', src)
            store = os.path.join(qwork, 'userdata')
            os.makedirs(store)
            got_q = subprocess.run([exe, store], capture_output=True, text=True, check=True).stdout.strip().split('\n')
            for want_line, got_line in zip(QUEUE_EXPECT, got_q + [''] * len(QUEUE_EXPECT)):
                ok = want_line == got_line
                print('%-4s %s%s' % ('ok' if ok else 'FAIL', got_line, '' if ok else '   (want: %s)' % want_line))
                if not ok:
                    failures.append('queue: ' + want_line)

        # 3. the bridge script and saveAndOpen, in node
        print('\n-- bridge script (node) --')
        m = re.search(r'(window\.AscDesktopEditor\.callToolFunction = function\(name, args\) \{\\n\\\n.*?\n\};\\n\\\n)', wrapper, re.S)
        if not m:
            print('FAIL no callToolFunction wrapper in the bridge script (the native function answers synchronously only)')
            failures.append('no callToolFunction wrapper')
        else:
            r = subprocess.run(['node', '-e', WRAPPER_JS, '--', unescape_c(m.group(1))], capture_output=True, text=True)
            print(r.stdout.strip() or r.stderr.strip())
            if r.stdout.count(': true') != 3:
                failures.append('callToolFunction wrapper')

        save = brace_block(wrapper, 'else if (name == "_saveAndOpen")')
        m = re.search(r'std::string sCode = "(\(function\(\)\{\\n\\\n.*?)";', save[save.find('nConvertCounter'):], re.S)
        if not m:
            sys.exit('saveAndOpen eval code not found')
        code = unescape_c(m.group(1))
        r = subprocess.run(['node', '-e', SAVE_JS, '--', code], capture_output=True, text=True)
        print('saveAndOpen ' + (r.stdout.strip() or r.stderr.strip()).replace('\n', '\nsaveAndOpen '))
        if 'callback got code 0' not in r.stdout:
            failures.append('saveAndOpen callback not registered')

        agent = 'ChromiumBasedEditors/plugins/ai-agent/'
        for rel in ('src/pages/chat/sub-components/AssistantMessage.tsx', 'src/store/useThreadsStore.ts',
                    'deploy/{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}/index.js'):
            text = read(agent + rel)
            # src: "(code) => { ... if (code) console.log(...)"; deploy: "m=>{m&&console.log(...)"
            bad = re.findall(r'if \(!code\) console\.log\("Conversion error"\)|\b(\w)=>\{\1\|\|console\.log\("Conversion error"\)', text)
            good = re.findall(r'if \(code\) console\.log\("Conversion error"\)|\b(\w)=>\{\1&&console\.log\("Conversion error"\)', text)
            ok = not bad and len(good) >= 1
            print('%-4s %s: "Conversion error" only for a non-zero code (%d ok, %d inverted)' % ('ok' if ok else 'FAIL', rel.split('/')[-1], len(good), len(bad)))
            if not ok:
                failures.append('saveAndOpen callback check in ' + rel)

        # 4. wiring
        print('\n-- wiring --')
        occ = brace_block(wrapper, 'virtual void OnContextCreated(') or ''
        nb = new_block or ''
        wiring = {
            'native function is _callToolFunction (callToolFunction is the script wrapper)':
                '"_callToolFunction",' in occ and '"callToolFunction",' not in occ,
            '_callToolFunction answers only the bundled AI agent (IsProcessFrameRenderer)':
                'IsProcessFrameRenderer(m_frame)' in nb[:nb.find('CheckAIToolCall(') if 'CheckAIToolCall(' in nb else 0],
            'no tool runs before CheckAIToolCall': 'callFunc(' not in nb and 'RunAIToolFunction(' in nb[nb.find('CheckAIToolCall('):] if nb else False,
            'unknown files go to the browser ("ai_tool_file_confirm")': 'CefProcessMessage::Create("ai_tool_file_confirm")' in nb,
            'the answer reaches the renderer': 'sMessageName == "ai_tool_file_confirm_result"' in wrapper and 'OnToolFileConfirmed(' in wrapper,
            'cefview.cpp hands ai_tool_file_confirm to the queue':
                'GetQueue().RequestFile(' in (brace_block(view, 'else if ("ai_tool_file_confirm" == message_name)') or ''),
            'attachments from the agent count as given':
                'AddAIToolGivenFile(' in (brace_block(wrapper, 'else if (name == "_convertFileExternal")') or ''),
        }
        for k, v in wiring.items():
            print('%-4s %s' % ('ok' if v else 'FAIL', k))
            if not v:
                failures.append(k)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print('\nFAIL: %d problem(s)%s' % (len(failures), ' [BASELINE %s]' % BASE_REF if BASELINE else ''))
        sys.exit(1)
    print('\nPASS: the agent\'s tools read only what the user gave it or allowed; saveAndOpen\'s callback runs')


if __name__ == '__main__':
    main()
