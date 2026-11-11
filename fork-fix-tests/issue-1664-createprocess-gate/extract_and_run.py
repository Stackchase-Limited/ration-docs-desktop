#!/usr/bin/env python3
"""
#1664 (security follow-up) - window.AscDesktopEditor._createProcess started any
command line for any onlyoffice:// frame.

client_renderer_wrapper.cpp, "_createProcess": the only check was
`0 != sCurrentUrl.find("onlyoffice://")`. Every plugin whose config.json sets
"onlyofficeScheme": true is served as onlyoffice://plugin/<path> - user-installed
plugins too, and the #1664 origin gate (bridge_access.h) rightly gives those the
bridge - so any plugin from the store or a .plugin file could run programs. All
such frames also share ONE origin (onlyoffice://plugin): a plugin can call the AI
agent's own AscDesktopEditor from a sibling frame, or load the agent's page into
an iframe of its own. Shown in a copy of the test app (see the report): a user
plugin started /usr/bin/touch in all four ways, and wrote files with ResaveFile
and saveAndOpen.

Now (desktop-sdk wip/1664-process):
- the renderer answers _createProcess only for the bundled AI agent's page
  (bridge_access.h CPolicy::IsProcessFrame, called through IsProcessFrameRenderer):
  onlyoffice://plugin/ under <app>/editors/sdkjs-plugins/{9DC93CDB-...777}/ - not
  the user plugins directory, so a user plugin cannot claim the GUID - with the
  start page or an editor (file:// under the app) as its parent;
- even then it only reserves an id and sends "external_process_confirm" to the
  browser process; external_process_confirm.h CQueue checks the frame again and
  asks the user (native dialog), remembering "Allow" per command line + env in
  <user data>/data/external_processes_allowed.txt. That is the real gate: the
  frame check cannot stop a same-origin plugin from calling the agent's function.
- plugin-scheme frames (CPolicy::IsPluginFrame) get the bridge without the
  methods that write/delete/copy to a page-chosen path or install plugins
  (CPolicy::IsPluginRestrictedMethod).

This test compiles the REAL bridge_access.h, the REAL IsProcessFrameRenderer /
GetBridgeFrameChain / GetAppDirFromSystemPlugins (taken from
client_renderer_wrapper.cpp by brace matching), the REAL external_process_confirm.h
and the REAL applicationmanager_events.h against stub CEF/file classes, and checks:
1. which frame chains pass the renderer gate (URLs as the running app reported them);
2. the browser queue: a new command asks (one dialog event, nothing started), "Don't
   Allow" answers no and remembers nothing, "Allow" answers yes and is written to the
   store, a new queue (next app start) answers a remembered command at once without a
   dialog, a different environment asks again, and a request from a frame that fails
   the gate is refused without a dialog;
3. the plugin-scheme tier and the restricted method list;
4. wiring: _createProcess never starts a process itself (only via the confirm answer),
   cefview.cpp hands "external_process_confirm" to the queue, OnContextCreated filters
   the methods for plugin frames, Execute refuses them.

BASELINE=1 reads the sources at BASE_REF: the old gate (its condition taken from the
real _createProcess block) lets every onlyoffice:// frame start a process at once, so
the user-plugin rows FAIL, and the confirm queue / plugin tier do not exist.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read sources at BASE_REF; must FAIL
  BASE_REF                         default 4f9635f9^ (the parent of the fix)

NOT claimed here (checked live in a copy of the test app, see the report): the real
CEF frame tree and URLs, the NSAlert itself, the Windows/Linux QMessageBox in
desktop-apps (syntax-checked only), and that the agent's MCP server then runs.
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
BASE_REF = os.environ.get('BASE_REF', '4f9635f9^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
INC = 'ChromiumBasedEditors/lib/include/'


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


def compile_run(work, name, src, stdin=''):
    with open(os.path.join(work, name + '.cpp'), 'w', encoding='utf-8') as f:
        f.write(src)
    exe = os.path.join(work, name)
    r = subprocess.run(['c++', '-std=c++11', '-Wall', '-Wno-unused-function', '-I', work, '-o', exe,
                        os.path.join(work, name + '.cpp')], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('compile of %s failed:\n%s' % (name, r.stderr))
    return subprocess.run([exe], input=stdin, capture_output=True, text=True, check=True).stdout


APP = '/Applications/Ration Docs.app/Contents/Resources'
APPU = 'file:///Applications/Ration%20Docs.app/Contents/Resources'
USERP = '/Users/u/Library/Application Support/com.stackchase.rationdocs/data/sdkjs-plugins'
USERPU = 'file:///Users/u/Library/Application%20Support/com.stackchase.rationdocs/data/sdkjs-plugins'
AGENT_GUID = '%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD777%7D'

START = (APPU + '/login/index.html?lang=en-EN&portal&desktop=true', '')
API = (APPU + '/editors/web-apps/apps/api/documents/index.html?placement=desktop&doctype=word', '')
EDITOR = (APPU + '/editors/web-apps/apps/documenteditor/main/index.html?_dc=0&lang=en', 'frameEditor')
# as the running app reported them: the start page uses onlyoffice://plugin//path, editors onlyoffice://plugin/file:///path
AGENT_START = ('onlyoffice://plugin/' + APPU[7:] + '/editors/sdkjs-plugins/' + AGENT_GUID + '/index.html?lang=en-EN&portal&desktop=true', 'system_asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}')
AGENT_EDITOR = ('onlyoffice://plugin/' + APPU + '/editors/sdkjs-plugins/' + AGENT_GUID + '/index.html?lang=en', 'iframe_asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}')
AI = ('onlyoffice://plugin/' + APPU + '/editors/sdkjs-plugins/%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD007%7D/index.html?lang=en', 'iframe_asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}')
UPLUGIN_START = ('onlyoffice://plugin/' + USERPU[7:] + '/%7BCC1664CC-0000-4000-8000-0000000000CC%7D/index.html', 'system_asc.{CC1664CC-0000-4000-8000-0000000000CC}')
UPLUGIN_EDITOR = ('onlyoffice://plugin/' + USERPU + '/%7BCC1664CC-0000-4000-8000-0000000000CC%7D/index.html?lang=en', 'iframe_asc.{CC1664CC}')
UPLUGIN_FAKEGUID = ('onlyoffice://plugin/' + USERPU + '/' + AGENT_GUID + '/index.html', 'iframe_asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}')
UPLUGIN_FILE = (USERPU + '/%7BCC1664CC-0000-4000-8000-0000000000CC%7D/index.html', 'iframe_asc.{CC1664CC}')


def c(*frames):
    return list(frames)


# (description, chain from the frame up to the main frame, may it ask for a process?)
GATE_CASES = [
    ('AI agent on the start page', c(AGENT_START, START), True),
    ('AI agent in an editor', c(AGENT_EDITOR, EDITOR, API), True),
    # must NOT
    ('user plugin (onlyofficeScheme) on the start page', c(UPLUGIN_START, START), False),
    ('user plugin (onlyofficeScheme) in an editor', c(UPLUGIN_EDITOR, EDITOR, API), False),
    ('user plugin installed under the AI agent\'s GUID', c(UPLUGIN_FAKEGUID, EDITOR, API), False),
    ('agent page loaded inside a user plugin\'s iframe', c(AGENT_START, UPLUGIN_START, START), False),
    ('agent page inside a file:// user plugin', c(AGENT_EDITOR, UPLUGIN_FILE, EDITOR, API), False),
    ('bundled AI plugin (another onlyoffice:// plugin)', c(AI, EDITOR, API), False),
    ('about:blank made by the agent', c(('about:blank', 'x'), AGENT_START, START), False),
    ('agent page as a main frame (no parent)', c(AGENT_START), False),
    ('agent path escaping with %2F..', c(('onlyoffice://plugin/' + APPU + '/editors/sdkjs-plugins/' + AGENT_GUID + '/..%2F..%2F..%2F..%2F..%2F..%2FUsers%2Fu%2Fx%2Findex.html', 'x'), EDITOR, API), False),
    ('agent GUID in a sibling-prefix directory', c(('onlyoffice://plugin/file:///Applications/Ration%20Docs.app/Contents/Resources/editors/sdkjs-plugins-evil/' + AGENT_GUID + '/index.html', 'x'), EDITOR, API), False),
    ('start page itself (file://)', c(START), False),
    ('editor (file://)', c(EDITOR, API), False),
    ('remote page', c(('https://evil.example.net/', ''),), False),
]

TIER_CASES = [
    ('AI agent', c(AGENT_START, START), True),
    ('user plugin (onlyofficeScheme)', c(UPLUGIN_EDITOR, EDITOR, API), True),
    ('about:blank made by a plugin', c(('about:blank', 'x'), UPLUGIN_EDITOR, EDITOR, API), True),
    ('about:srcdoc made by a plugin', c(('about:srcdoc', 'x'), UPLUGIN_EDITOR, EDITOR, API), True),
    ('blob: made by a plugin', c(('blob:onlyoffice://plugin/6f0e', 'x'), UPLUGIN_EDITOR, EDITOR, API), True),
    ('ascdesktop://plugin_content/', c(('ascdesktop://plugin_content/' + APPU + '/editors/sdkjs-plugins/x/index.html', ''), EDITOR, API), True),
    ('start page', c(START), False),
    ('editor', c(EDITOR, API), False),
    ('about:blank made by the editor', c(('about:blank', 'x'), EDITOR, API), False),
    ('connected portal', c(('https://portal.example.com/x', ''),), False),
]

RESTRICTED = ['ResaveFile', 'RemoveFile', '_DownloadFiles', 'SetCryptDocumentFolder', 'buildCryptedStart',
              'CryptoDownloadAs', '_ExportAdvancedEncryptedData', '_ImportAdvancedEncryptedData', 'setDocumentInfo',
              'localSaveToDrawingFormat', 'localSaveToDrawingFormat2', 'PluginInstall', 'PluginUninstall']
# what plugin-scheme frames really call (AI agent, AI plugin, store plugins): must stay
KEPT = ['_createProcess', '_endProcess', '_stdin', 'callToolFunction', 'getToolFunctions', '_convertFileExternal',
        '_onConvertFileExternal', '_saveAndOpen', '_OpenFilenameDialog', '_SaveFilenameDialog', 'getOfficeFileType',
        'openTemplate', 'generateNew', 'getGenerationInfo', 'GetImageBase64', '_getCurrentUrl', '_sendCloudsRequest']

STUBS = r'''
#include <string>
#include <vector>
#include <map>
#include <set>
#include <list>
#include <cstdio>
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
struct CefProcessMessage;
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
static std::vector<std::string> g_replies; // "token=allowed"
struct CefFrame {
	std::string url, name; CefFrame* parent; int64 id;
	CefString GetURL() { return CefString(url); }
	CefString GetName() { return CefString(name); }
	CefRefPtr<CefFrame> GetParent() { return CefRefPtr<CefFrame>(parent); }
	int64 GetIdentifier() { return id; }
	void SendProcessMessage(CefProcessId, CefRefPtr<CefProcessMessage> m) {
		char b[64]; snprintf(b, sizeof(b), "%d=%d", m->args.ints[0], (int)m->args.bools[1]); g_replies.push_back(b);
	}
};
struct CefBrowser {
	std::vector<CefFrame*> frames;
	CefRefPtr<CefFrame> GetFrame(int64 id) { for (size_t i = 0; i < frames.size(); ++i) if (frames[i]->id == id) return frames[i]; return CefRefPtr<CefFrame>(); }
};
struct CAscRendererProcessParams {
	std::map<std::string, std::string> m;
	std::string GetValue(const std::string& k, const std::string& d = "") { return m.count(k) ? m[k] : d; }
	static CAscRendererProcessParams& getInstance() { static CAscRendererProcessParams p; return p; }
};
namespace NSStringUtils {
	static void string_replaceA(std::string& s, const std::string& a, const std::string& b) {
		for (size_t p = s.find(a); p != std::string::npos; p = s.find(a, p + b.length())) s.replace(p, a.length(), b);
	}
}
'''

GATE_DRIVER = r'''
#include "bridge_access.h"
struct CAscEditorNativeV8Handler {
@@FUNCS@@
};
int main()
{
	CAscRendererProcessParams& p = CAscRendererProcessParams::getInstance();
	p.m["system_plugins_path"] = "@@APP@@/editors/sdkjs-plugins";
	p.m["user_plugins_path"] = "@@USERP@@";
	char line[8192];
	while (fgets(line, sizeof(line), stdin))
	{
		std::vector<std::string> f; std::string cur;
		for (char* c = line; *c && *c != '\n'; ++c) { if (*c == '\t') { f.push_back(cur); cur.clear(); } else cur += *c; }
		f.push_back(cur);
		std::string kind = f[0]; f.erase(f.begin());
		std::vector<CefFrame> frames(f.size() / 2);
		for (size_t i = 0; i < frames.size(); ++i)
		{
			frames[i].url = f[2 * i]; frames[i].name = f[2 * i + 1]; frames[i].id = (int64)i + 1;
			frames[i].parent = (i + 1 < frames.size()) ? &frames[i + 1] : 0;
		}
		if (kind == "gate")
			printf("%d\n", (int)CAscEditorNativeV8Handler::IsProcessFrameRenderer(CefRefPtr<CefFrame>(&frames[0])));
		else
			printf("%d\n", (int)NSBridgeAccess::CPolicy::IsPluginFrame(CAscEditorNativeV8Handler::GetBridgeFrameChain(CefRefPtr<CefFrame>(&frames[0]))));
	}
	return 0;
}
'''

BASE_GATE_DRIVER = r'''
// BASELINE: the old renderer gate, its condition copied from the real _createProcess block
#include <string>
#include <cstdio>
static bool OldGate(const std::string& sCurrentUrl) { if (@@COND@@) return false; return true; }
int main()
{
	char line[8192];
	while (fgets(line, sizeof(line), stdin))
	{
		std::string s(line); s = s.substr(s.find('\t') + 1); s = s.substr(0, s.find('\t')); // "gate", then the frame's URL
		printf("%d\n", (int)OldGate(s));
	}
	return 0;
}
'''

QUEUE_DRIVER = r'''
#include "applicationmanager_events.h"
static std::string ToUtf8(const std::wstring& w) { return std::string(w.begin(), w.end()); }
static std::wstring FromUtf8(const std::string& s) { return std::wstring(s.begin(), s.end()); }
#define U_TO_UTF8(w) ToUtf8(w)
#define UTF8_TO_U(s) FromUtf8(s)
static std::string g_store_dir;
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
	std::vector<int> asks; std::vector<std::wstring> texts;
	virtual void OnEvent(NSEditorApi::CAscCefMenuEvent* e) {
		if (e->m_nType == ASC_MENU_EVENT_TYPE_SYSTEM_EXTERNAL_PROCESS_CONFIRM) {
			NSEditorApi::CAscExternalProcessConfirm* d = (NSEditorApi::CAscExternalProcessConfirm*)e->m_pData;
			asks.push_back(d->get_Id()); texts.push_back(d->get_Text());
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

static CefRefPtr<CefListValue> Args(int token, const std::string& cmd, const char* k = 0, const char* v = 0)
{
	CefListValue* a = new CefListValue(); a->SetInt(0, token); a->SetString(1, cmd);
	if (k) { a->SetString(2, k); a->SetString(3, v); }
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

	NSExternalProcessConfirm::CQueue& q = NSExternalProcessConfirm::GetQueue(); // where Answer() goes
	q.Request(&man, 7, &browser, &agent, Args(1, "/usr/bin/python3 /srv/mcp.py"));
	printf("new command: dialogs=%d replies=%s\n", (int)man.listener.asks.size(), Replies().c_str());
	bool bShown = !man.listener.texts.empty() && std::wstring::npos != man.listener.texts[0].find(L"/usr/bin/python3 /srv/mcp.py");
	printf("dialog shows the command: %d\n", (int)bShown);
	NSExternalProcessConfirm::Answer(man.listener.asks.back(), false);
	printf("Don't Allow: replies=%s\n", Replies().c_str());
	std::ifstream none((dir + "/data/external_processes_allowed.txt").c_str());
	printf("store after Don't Allow exists: %d\n", (int)(bool)none);

	q.Request(&man, 7, &browser, &agent, Args(2, "/usr/bin/python3 /srv/mcp.py"));
	q.Request(&man, 7, &browser, &agent, Args(3, "/usr/bin/python3 /srv/mcp.py"));
	printf("asked again: dialogs=%d replies=%s\n", (int)man.listener.asks.size(), Replies().c_str());
	NSExternalProcessConfirm::Answer(man.listener.asks.back(), true);
	printf("Allow: replies=%s\n", Replies().c_str());

	NSExternalProcessConfirm::CQueue q2; // the next start of the application
	size_t nBefore = man.listener.asks.size();
	q2.Request(&man, 7, &browser, &agent, Args(4, "/usr/bin/python3 /srv/mcp.py"));
	printf("remembered after restart: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	q2.Request(&man, 7, &browser, &agent, Args(5, "/usr/bin/python3 /srv/mcp.py", "NODE_OPTIONS", "--require /tmp/x.js"));
	printf("same command, other env: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	q2.OnAnswer(man.listener.asks.back(), false);
	Replies();
	nBefore = man.listener.asks.size();
	q2.Request(&man, 7, &browser, &user, Args(6, "/usr/bin/python3 /srv/mcp.py"));
	printf("user plugin frame, remembered command: dialogs=%d replies=%s\n", (int)(man.listener.asks.size() - nBefore), Replies().c_str());
	return 0;
}
'''

QUEUE_EXPECT = [
    'new command: dialogs=1 replies=-',
    'dialog shows the command: 1',
    "Don't Allow: replies=1=0",
    "store after Don't Allow exists: 0",
    'asked again: dialogs=2 replies=-',
    'Allow: replies=2=1,3=1',
    'remembered after restart: dialogs=0 replies=4=1',
    'same command, other env: dialogs=1 replies=-',
    'user plugin frame, remembered command: dialogs=0 replies=6=0',
]


def main():
    wrapper = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')
    header = read(SRC + 'bridge_access.h', missing_ok=True)
    confirm = read(SRC + 'external_process_confirm.h', missing_ok=True)
    events = read(INC + 'applicationmanager_events.h')
    view = read(SRC + 'cefview.cpp')

    failures = []
    block = brace_block(wrapper, 'else if (name == "_createProcess")')
    if block is None:
        sys.exit('_createProcess not found')

    work = tempfile.mkdtemp(prefix='rd1664p-')
    try:
        # 1. the renderer gate
        gate_stdin = ''.join('\t'.join(['gate'] + [x for fr in chain for x in fr]) + '\n' for _, chain, _ in GATE_CASES)
        uses_new_gate = 'IsProcessFrameRenderer(' in block
        if uses_new_gate and header is not None:
            funcs = ''.join(brace_block(wrapper, sig) + '\n' for sig in (
                'static std::vector<NSBridgeAccess::CFrame> GetBridgeFrameChain(',
                'static std::string GetAppDirFromSystemPlugins(',
                'static bool IsProcessFrameRenderer('))
            with open(os.path.join(work, 'bridge_access.h'), 'w', encoding='utf-8') as f:
                f.write(header)
            drv = STUBS + GATE_DRIVER.replace('@@FUNCS@@', funcs).replace('@@APP@@', APP).replace('@@USERP@@', USERP)
            gate = [o == '1' for o in compile_run(work, 'gate', drv, gate_stdin).split()]
            tier_stdin = ''.join('\t'.join(['tier'] + [x for fr in chain for x in fr]) + '\n' for _, chain, _ in TIER_CASES)
            tier = [o == '1' for o in compile_run(work, 'gate', drv, tier_stdin).split()]
        else:
            m = re.search(r'if \((0 != sCurrentUrl\.find\("onlyoffice://"\))\)', block)
            if not m:
                sys.exit('neither the new nor the old _createProcess gate found')
            print('old gate (from the real _createProcess):', m.group(1))
            gate = [o == '1' for o in compile_run(work, 'oldgate', BASE_GATE_DRIVER.replace('@@COND@@', m.group(1)), gate_stdin).split()]
            tier = None

        # whether a passing frame starts the process at once (old) or only asks the browser (new)
        starts_at_once = '->Start(' in block
        asks_browser = 'CefProcessMessage::Create("external_process_confirm")' in block
        print('_createProcess starts the process itself:', starts_at_once, '| asks the browser process first:', asks_browser)
        if starts_at_once or not asks_browser:
            failures.append('_createProcess starts a process without the browser process (the user) agreeing')

        print('\n-- may this frame ask to run a command line? --')
        for (desc, chain, want), got in zip(GATE_CASES, gate):
            ok = got == want
            print('%-4s %-58s %s (want %s)' % ('ok' if ok else 'FAIL', desc, 'yes' if got else 'no', 'yes' if want else 'no'))
            if not ok:
                failures.append(desc)

        # 2. the browser-side queue
        print('\n-- browser process: dialog, answers, remembered command lines --')
        if confirm is None or 'CAscExternalProcessConfirm' not in events:
            print('FAIL external_process_confirm.h / CAscExternalProcessConfirm missing: nothing asks the user')
            failures.append('no confirmation in the browser process')
        else:
            with open(os.path.join(work, 'external_process_confirm.h'), 'w', encoding='utf-8') as f:
                f.write(confirm)
            with open(os.path.join(work, 'applicationmanager_events.h'), 'w', encoding='utf-8') as f:
                f.write(events)
            drv = STUBS + QUEUE_DRIVER.replace('@@APP@@', APP).replace('@@USERP@@', USERP) \
                .replace('@@START@@', START[0]).replace('@@AGENT@@', AGENT_START[0]).replace('@@UPLUGIN@@', UPLUGIN_START[0])
            store = os.path.join(work, 'userdata')
            os.makedirs(store)
            with open(os.path.join(work, 'queue.cpp'), 'w', encoding='utf-8') as f:
                f.write(drv)
            exe = os.path.join(work, 'queue')
            r = subprocess.run(['c++', '-std=c++11', '-Wall', '-Wno-unused-function', '-I', work, '-o', exe, os.path.join(work, 'queue.cpp')], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit('compile of queue failed:\n' + r.stderr)
            got = subprocess.run([exe, store], capture_output=True, text=True, check=True).stdout.strip().split('\n')
            for want_line, got_line in zip(QUEUE_EXPECT, got + [''] * len(QUEUE_EXPECT)):
                ok = want_line == got_line
                print('%-4s %s%s' % ('ok' if ok else 'FAIL', got_line, '' if ok else '   (want: %s)' % want_line))
                if not ok:
                    failures.append('queue: ' + want_line)
            stored = open(os.path.join(store, 'data', 'external_processes_allowed.txt')).read() if os.path.exists(os.path.join(store, 'data', 'external_processes_allowed.txt')) else ''
            print('store:', repr(stored))
            if stored != '/usr/bin/python3 /srv/mcp.py\n':
                failures.append('store content')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 3. plugin-scheme tier
    print('\n-- plugin-scheme frames: the bridge without path writers --')
    if tier is None:
        print('FAIL no plugin-scheme tier: every onlyoffice:// frame (user plugins too) gets ResaveFile, RemoveFile, PluginInstall...')
        failures.append('no plugin-scheme tier')
    else:
        for (desc, chain, want), got in zip(TIER_CASES, tier):
            ok = got == want
            print('%-4s %-58s plugin tier=%s' % ('ok' if ok else 'FAIL', desc, 'yes' if got else 'no'))
            if not ok:
                failures.append('tier: ' + desc)
        listed = re.findall(r'"([A-Za-z_0-9]+)",\s*(?://[^\n]*)?\n', brace_block(header, 'static bool IsPluginRestrictedMethod(') or '')
        for n in RESTRICTED:
            if n not in listed:
                print('FAIL %s is still given to plugin-scheme frames' % n)
                failures.append('restricted ' + n)
        for n in KEPT:
            if n in listed:
                print('FAIL %s (used by plugin-scheme plugins) was taken away' % n)
                failures.append('kept ' + n)
        print('restricted: %d methods; kept for plugins: %s' % (len(listed), ', '.join(KEPT)))

    # 4. wiring
    print('\n-- wiring --')
    occ = brace_block(wrapper, 'virtual void OnContextCreated(') or ''
    ex = wrapper
    wiring = {
        'OnContextCreated leaves restricted methods off plugin frames': 'IsPluginRestrictedMethod(*cur)' in occ and 'ExtendObject(obj, handler, methodsPlugin)' in occ,
        'Execute refuses them on a plugin-frame bridge': 'm_bPluginFrame && NSBridgeAccess::CPolicy::IsPluginRestrictedMethod(name)' in ex,
        'renderer starts only on the browser\'s answer': 'sMessageName == "external_process_confirm_result"' in wrapper and 'StartReserved(' in wrapper,
        'cefview.cpp hands external_process_confirm to the queue': 'GetQueue().Request(' in (brace_block(view, 'else if ("external_process_confirm" == message_name)') or ''),
        'saveAndOpen only to the path picked in the save dialog': 'm_mapSaveDialogResults' in (brace_block(view, 'else if ("convert_file_external_and_open" == message_name)') or ''),
        '_onConvertFileExternal reads only reported results': 'ConvertedExternalFiles()' in (brace_block(wrapper, 'else if (name == "_onConvertFileExternal")') or ''),
    }
    for k, v in wiring.items():
        print('%-4s %s' % ('ok' if v else 'FAIL', k))
        if not v:
            failures.append(k)

    if failures:
        print('\nFAIL: %d problem(s)%s' % (len(failures), ' [BASELINE %s]' % BASE_REF if BASELINE else ''))
        sys.exit(1)
    print('\nPASS: only the bundled AI agent can ask for a process, the user decides, plugin frames lose the path writers')


if __name__ == '__main__':
    main()
