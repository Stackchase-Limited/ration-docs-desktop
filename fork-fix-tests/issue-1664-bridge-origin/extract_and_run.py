#!/usr/bin/env python3
"""
#1664 (security hardening) - the native bridge window.AscDesktopEditor was put on
the global object of EVERY JS context of every frame, whatever its origin.

ClientRenderDelegate::OnContextCreated (desktop-sdk client_renderer_wrapper.cpp)
created the bridge object unconditionally: a remote iframe inside the editor, a
YouTube embed in a plugin, the remote marketplace page, a third-party frame in a
portal page, a cloud "editor" tab opened at an arbitrary address - all got
RemoveFile, LocalFileSaveChanges, _convertFile, _createProcess, execCommand...
(seen in a copy of the test app: a 127.0.0.1 iframe had all 230 members).

Now OnContextCreated calls CheckBridgeAccess(frame), which builds the frame's
chain of (URL, name) up its parents and asks NSBridgeAccess::CPolicy
(bridge_access.h), and returns before creating the bridge unless the answer is
Full. The trusted directories come from the startup properties
system_plugins_path (its <app> above /editors/sdkjs-plugins) and
user_plugins_path; the trusted origins from "bridge_origins" (the start page's
portal list, GetRendererStartupProperties) and "bridge_view_origin" (the URL a
portal tab was opened at, CCefView::load), added by AddFromParams in
OnBrowserCreated.

This compiles the REAL bridge_access.h and the REAL CheckBridgeAccess (taken
from client_renderer_wrapper.cpp by brace matching) against stub CefFrame /
CefRefPtr / startup-properties classes, feeds the startup properties under the
key names the browser side really writes (read from applicationmanager.cpp and
cefview.cpp), and checks a table of frame chains: every legitimate consumer
seen in the running app (start page, editor, frameEditor, the AI plugin and the
AI agent through onlyoffice://plugin/, the plugin manager and its local store,
a user plugin, srcdoc/about:blank frames our pages create, a connected
portal, its cross-origin document server and that server's plugins) keeps the
bridge; remote iframes, YouTube, the remote store, a spoofed "frameEditor",
data:, file:// outside our directories (also via %2F.. and a sibling-prefix
directory), network shares and untrusted cloud tabs do not.
It also checks that OnContextCreated returns on a non-Full answer BEFORE
SetValue("AscDesktopEditor", ...).

BASELINE=1 reads the sources at BASE_REF: OnContextCreated has no gate, so
every context gets the bridge (that is what the code does), and the table
FAILS on every frame that must not have it.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read sources at BASE_REF; must FAIL
  BASE_REF                         default 088146a4^ (the parent of the fix)

Follow-up (PLUGIN_ORIGIN_PLAN.md): user-installed plugins no longer run as
file:// from the user plugins directory; they are rdplugin://<guid>/ pages with
the Plugin tier (answer 2: an allowlist bridge, bridge_access.h
IsPluginTierMethod), inside one of our pages or as a top-level page only. A
file:// or onlyoffice://plugin/ page from the user plugins directory gets none,
even if that directory is inside the application's. The rdplugin chains below
expect 2; at BASE_REF they get 1 (no gate), so they fail there too. The new
behaviour has its own test with a later BASE_REF:
fork-fix-tests/issue-1664-plugin-origin.

NOT claimed here (checked live in a copy of the test app instead, see the
report): CEF's real GetURL/GetName/GetParent values - the URLs below are the
ones the running app reported. With --site-per-process (not on in this
build) a cross-origin document server's frameEditor is in another process,
its parent is not visible and it gets NO bridge - a later change that turns
site isolation on must pass that origin too.
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
BASE_REF = os.environ.get('BASE_REF', '088146a4^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'


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
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


APP = '/Applications/Ration Docs.app/Contents/Resources'
APPU = 'file:///Applications/Ration%20Docs.app/Contents/Resources'
USERP = '/Users/u/Library/Application Support/com.stackchase.rationdocs/data/sdkjs-plugins'
USERPU = 'file:///Users/u/Library/Application%20Support/com.stackchase.rationdocs/data/sdkjs-plugins'

START = (APPU + '/login/index.html?lang=en-EN&portal&desktop=true', '')
API = (APPU + '/editors/web-apps/apps/api/documents/index.html?placement=desktop&doctype=word', '')
EDITOR = (APPU + '/editors/web-apps/apps/documenteditor/main/index.html?_dc=0&lang=en', 'frameEditor')
AI = ('onlyoffice://plugin/' + APPU + '/editors/sdkjs-plugins/%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD007%7D/index.html?lang=en', 'iframe_asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}')
AGENT = ('onlyoffice://plugin/' + APPU[7:] + '/editors/sdkjs-plugins/%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD777%7D/index.html', 'system_asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}')
MANAGER = (APPU + '/editors/sdkjs-plugins/%7BAA2EA9B6-9EC2-415F-9762-634EE8D9A95E%7D/index.html?lang=en', 'pluginFrameEditor')
STORE = (APPU + '/editors/sdkjs-plugins/%7BAA2EA9B6-9EC2-415F-9762-634EE8D9A95E%7D/store/index.html?lang=en', '')
USERPLUGIN = (USERPU + '/%7BB1664B1D-0000-4000-8000-0000000000B1%7D/index.html?lang=en', 'pluginFrameEditor')
RDPLUGIN = ('rdplugin://b1664b1d-0000-4000-8000-0000000000b1/index.html?lang=en-EN&theme-type=light', 'pluginFrameEditor')
RDOCR = ('rdplugin://440ebf13-9b19-4bd8-8621-05200e58140b/index.html?lang=en', 'iframe_asc.{440EBF13-9B19-4BD8-8621-05200E58140B}')
MAIN = 'main'  # marks the last frame of a chain as CefFrame::IsMain()
PORTAL = ('https://portal.example.com/Products/Files/DocEditor.aspx?fileid=1&placement=desktop', '')
NCINNER = ('https://nc.example.com/nextcloud/apps/onlyoffice/42?inframe=true', 'onlyofficeFrame')
DS = ('https://ds.example.com/web-apps/apps/documenteditor/main/index.html?_dc=0', 'frameEditor')
DSPLUGIN = ('https://ds.example.com/sdkjs-plugins/%7B38E022EA-AD92-45FC-B22B-49DF39746DB4%7D/index.html', 'iframe_asc.{38E022EA}')
YOUTUBE = ('https://www.youtube.com/embed/abc', 'youtube')


def c(*frames):
    return list(frames)


# (description, chain from the frame up to the main frame, expected answer: True = Full (1),
# False = None (0), 2 = Plugin tier)
CASES = [
    ('start page', c(START), True),
    ('AI agent in the start page (onlyoffice://plugin//path)', c(AGENT, START), True),
    ('local editor api page', c(API), True),
    ('local frameEditor', c(EDITOR, API), True),
    ('AI plugin (onlyoffice://plugin/file://...)', c(AI, EDITOR, API), True),
    ('plugin manager', c(MANAGER, EDITOR, API), True),
    ('plugin manager local store', c(STORE, MANAGER, EDITOR, API), True),
    ('user plugin as file:// (user_plugins_path): now none', c(USERPLUGIN, EDITOR, API), False),
    ('user plugin as onlyoffice://plugin/ from user_plugins_path', c(('onlyoffice://plugin/' + USERPU + '/%7BB1664B1D-0000-4000-8000-0000000000B1%7D/index.html', 'iframe_asc.{B1664B1D}'), EDITOR, API), False),
    ('user plugin as ascdesktop://plugin_content/ from user_plugins_path', c(('ascdesktop://plugin_content/' + USERPU + '/%7BB1664B1D-0000-4000-8000-0000000000B1%7D/index.html', 'x'), EDITOR, API), False),
    # rdplugin: the Plugin tier (2)
    ('rdplugin user plugin in the editor', c(RDPLUGIN, EDITOR, API), 2),
    ('rdplugin OCR (non-visual iframe in the editor)', c(RDOCR, EDITOR, API), 2),
    ('rdplugin external plugin in the start page', c(RDPLUGIN, START), 2),
    ('rdplugin as a top-level page (main frame)', c(RDPLUGIN + (MAIN,)), 2),
    ('about:blank made by an rdplugin page', c(('about:blank', 'x'), RDPLUGIN, EDITOR, API), 2),
    ('blob:rdplugin made by the plugin, in the editor', c(('blob:rdplugin://b1664b1d-0000-4000-8000-0000000000b1/6f0e', 'x'), EDITOR, API), 2),
    ('rdplugin page framed by a remote page', c(RDPLUGIN, ('http://127.0.0.1:8765/probe.html', 'bx-remote'), EDITOR, API), False),
    ('rdplugin page whose parent is in another process (not main)', c(RDPLUGIN), False),
    ('rdplugin with a host that is not a GUID', c(('rdplugin://evil.example.com/x.html', 'x'), EDITOR, API), False),
    ('about:srcdoc made by the editor', c(('about:srcdoc', 'x'), EDITOR, API), True),
    ('about:blank made by the editor', c(('about:blank', 'x'), EDITOR, API), True),
    ('blob:file made by the editor', c(('blob:file:///6f0e', 'x'), EDITOR, API), True),
    ('file://localhost/ start page', c(('file://localhost' + APPU[7:] + '/login/index.html', ''),), True),
    ('ascdesktop://crash.html', c(('ascdesktop://crash.html?lang=en', ''),), True),
    ('ascdesktop://loaderror.html', c(('ascdesktop://loaderror.html', ''),), True),
    ('connected portal main frame', c(PORTAL), True),
    ('connected portal, upper case + :443', c(('HTTPS://Portal.Example.COM:443/x', ''),), True),
    ('blob: of the connected portal', c(('blob:https://portal.example.com/1b2c', ''), PORTAL), True),
    ('portal kept without scheme, with path (nc.example.com/nextcloud)', c(('https://nc.example.com/nextcloud/apps/files/', ''),), True),
    ('document server frameEditor under a Nextcloud inner frame', c(DS, NCINNER, ('https://nc.example.com/nextcloud/apps/onlyoffice/42', ''),), True),
    ('document server plugin (same origin as frameEditor)', c(DSPLUGIN, DS, PORTAL), True),
    ('portal tab being connected (bridge_view_origin http)', c(('http://new.example.com/login?desktop=true', ''),), True),
    ('... after its redirect to https', c(('https://new.example.com/apps/files', ''),), True),
    # must NOT have it
    ('remote iframe in the local editor', c(('http://127.0.0.1:8765/probe.html', 'bx-remote'), EDITOR, API), False),
    ('YouTube in a plugin', c(YOUTUBE, AI, EDITOR, API), False),
    ('remote marketplace in the plugin manager', c(('https://onlyoffice.github.io/store/index.html?lang=en', ''), MANAGER, EDITOR, API), False),
    ('about:blank made by a remote frame', c(('about:blank', 'y'), ('http://127.0.0.1:8765/probe.html', 'bx-remote'), EDITOR, API), False),
    ('spoofed "frameEditor" under the local editor', c(('http://localhost:8765/probe.html', 'frameEditor'), API), False),
    ('spoofed "frameEditor" under a document server plugin', c(('https://evil.example.net/x', 'frameEditor'), DSPLUGIN, DS, PORTAL), False),
    ('YouTube in a document server plugin', c(YOUTUBE, DSPLUGIN, DS, PORTAL), False),
    ('third-party frame in a portal page', c(('https://ads.example.net/x', 'ad'), PORTAL), False),
    ('data: iframe in the editor', c(('data:text/html,<p>x</p>', 'bx-data'), EDITOR, API), False),
    ('file:// outside our directories', c(('file:///Users/u/Downloads/evil.html', 'x'), EDITOR, API), False),
    ('file:// escaping with %2F..', c((APPU + '/editors%2F..%2F..%2F..%2F..%2F..%2FUsers%2Fu%2FDownloads%2Fevil.html', 'x'), EDITOR, API), False),
    ('file:// sibling directory with the same prefix', c(('file:///Applications/Ration%20Docs.app/Contents/Resources-evil/x.html', 'x'), EDITOR, API), False),
    ('file:// on a network share', c(('file://server/share' + APPU[7:] + '/login/index.html', ''),), False),
    ('onlyoffice://plugin/ outside our directories', c(('onlyoffice://plugin/file:///Users/u/Downloads/x/index.html', 'iframe_asc.{X}'), EDITOR, API), False),
    ('ascdesktop://fonts/ page', c(('ascdesktop://fonts/Users/u/Downloads/x.html', ''),), False),
    ('cloud editor tab at an unconnected address', c(('http://localhost:8766/Products/Files/DocEditor.aspx?fileid=2', ''),), False),
    ('blob: of another origin', c(('blob:https://evil.example.net/1b2c', ''), PORTAL), False),
    ('about:blank main frame', c(('about:blank', ''),), False),
    ('chrome-error page', c(('chrome-error://chromewebdata/', ''),), False),
    ('https downgraded to http', c(('http://portal.example.com/x', ''),), False),
]

STUBS = r'''
#include <string>
#include <vector>
#include <map>
#include <cstdio>
template <class T> class CefRefPtr {
public:
	T* p; CefRefPtr() : p(0) {} CefRefPtr(T* x) : p(x) {}
	T* operator->() const { return p; } operator bool() const { return p != 0; }
	bool operator!() const { return p == 0; } T* get() const { return p; }
};
struct CefString {
	std::string s; CefString(const std::string& x) : s(x) {}
	std::string ToString() const { return s; }
};
struct CefFrame {
	std::string url, name; CefFrame* parent; bool main;
	bool IsMain() { return main; }
	CefString GetURL() { return CefString(url); }
	CefString GetName() { return CefString(name); }
	CefRefPtr<CefFrame> GetParent() { return CefRefPtr<CefFrame>(parent); }
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

DRIVER = r'''
#include "bridge_access.h"
struct ClientRenderDelegate {
@@CHECK@@
};
int main(int argc, char** argv)
{
	// the renderer's startup properties, under the keys the browser side writes
	CAscRendererProcessParams& p = CAscRendererProcessParams::getInstance();
	p.m["system_plugins_path"] = "@@APP@@/editors/sdkjs-plugins";
	p.m["user_plugins_path"] = "@@USERP@@";
	std::vector<std::string> props;
	props.push_back("@@KEY_ORIGINS@@https://portal.example.com;nc.example.com/nextcloud");
	props.push_back("@@KEY_VIEW@@http://new.example.com");
	NSBridgeAccess::AddFromParams(props);

	ClientRenderDelegate d;
	char line[8192];
	while (fgets(line, sizeof(line), stdin))
	{
		// one chain per line: url \t name \t url \t name ...
		std::vector<std::string> f; std::string cur;
		for (char* c = line; *c && *c != '\n'; ++c) { if (*c == '\t') { f.push_back(cur); cur.clear(); } else cur += *c; }
		f.push_back(cur);
		std::vector<CefFrame> frames(f.size() / 2);
		for (size_t i = 0; i < frames.size(); ++i)
		{
			frames[i].url = f[2 * i]; frames[i].name = f[2 * i + 1];
			frames[i].main = false;
			if (frames[i].name.size() > 5 && frames[i].name.compare(frames[i].name.size() - 5, 5, "|main") == 0)
			{
				frames[i].name = frames[i].name.substr(0, frames[i].name.size() - 5);
				frames[i].main = true;
			}
			frames[i].parent = (i + 1 < frames.size()) ? &frames[i + 1] : 0;
		}
		printf("%d\n", (int)d.CheckBridgeAccess(CefRefPtr<CefFrame>(&frames[0])));
	}
	return 0;
}
'''


def key_written(text, key):
    if text is None or ('"' + key) not in text:
        return False
    return True


def main():
    wrapper = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')
    header = read(SRC + 'bridge_access.h', missing_ok=True)
    manager = read(SRC + 'applicationmanager.cpp')
    view = read(SRC + 'cefview.cpp')
    app = read(SRC + 'cefwrapper/client_app.h')

    failures = []
    occ = brace_block(wrapper, 'virtual void OnContextCreated(')
    if occ is None:
        sys.exit('OnContextCreated not found')
    pos_set = occ.find('SetValue("AscDesktopEditor"')
    m = re.search(r'if\s*\(\s*NSBridgeAccess::Full\s*!=\s*CheckBridgeAccess\([^)]*\)\s*\)\s*\)?\s*return\s*;', occ)
    if m is None:
        # since the rdplugin follow-up: the answer is kept (eAccess) and the bridge is made only
        # for Full or Plugin
        m = re.search(r'if\s*\(\s*NSBridgeAccess::Full\s*!=\s*eAccess\s*&&\s*NSBridgeAccess::Plugin\s*!=\s*eAccess\s*\)\s*return\s*;', occ)
    gated = m is not None and pos_set > m.start()
    print('OnContextCreated returns before SetValue("AscDesktopEditor") on a non-Full answer:', gated)
    if not gated:
        failures.append('OnContextCreated creates the bridge without asking for the frame\'s access')

    # the browser side must write the keys AddFromParams reads, and OnBrowserCreated must feed them
    wiring = {
        'applicationmanager.cpp writes bridge_origins=': key_written(manager, 'bridge_origins='),
        'cefview.cpp writes bridge_view_origin=': key_written(view, 'bridge_view_origin='),
        'client_app.h calls NSBridgeAccess::AddFromParams': app is not None and app.count('NSBridgeAccess::AddFromParams(params)') == 2,
        'set_portals_list only from the start page': 'GetViewForSystemMessages())\n\t\t\treturn true;' in (brace_block(view, 'else if ("set_portals_list" == message_name)') or ''),
    }
    for k, v in wiring.items():
        print('%-55s %s' % (k, v))
        if not v:
            failures.append(k)

    results = None
    if gated and header is not None:
        check = brace_block(wrapper, 'NSBridgeAccess::Access CheckBridgeAccess(')
        if check is None:
            sys.exit('CheckBridgeAccess not found')
        work = tempfile.mkdtemp(prefix='rd1664b-')
        try:
            with open(os.path.join(work, 'bridge_access.h'), 'w', encoding='utf-8') as f:
                f.write(header)
            src = STUBS + DRIVER.replace('@@CHECK@@', check).replace('@@APP@@', APP).replace('@@USERP@@', USERP) \
                .replace('@@KEY_ORIGINS@@', 'bridge_origins=').replace('@@KEY_VIEW@@', 'bridge_view_origin=')
            with open(os.path.join(work, 'driver.cpp'), 'w', encoding='utf-8') as f:
                f.write(src)
            exe = os.path.join(work, 'driver')
            r = subprocess.run(['c++', '-std=c++11', '-Wall', '-I', work, '-o', exe, os.path.join(work, 'driver.cpp')], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit('compile failed:\n' + r.stderr)
            def frame_fields(fr):
                # (url, name) or (url, name, MAIN): the last marks CefFrame::IsMain()
                return [fr[0], fr[1] + ('|main' if len(fr) > 2 and fr[2] == MAIN else '')]
            stdin = ''.join('\t'.join(x for fr in chain for x in frame_fields(fr)) + '\n' for _, chain, _ in CASES)
            out = subprocess.run([exe], input=stdin, capture_output=True, text=True, check=True).stdout.split()
            results = [int(o) for o in out]
        finally:
            shutil.rmtree(work, ignore_errors=True)
    else:
        # no gate: OnContextCreated gives every context the bridge
        results = [1] * len(CASES)

    names = {0: 'no', 1: 'yes', 2: 'plugin tier'}
    for (desc, chain, want), got in zip(CASES, results):
        want = int(want) if not isinstance(want, bool) else (1 if want else 0)
        ok = got == want
        print('%-4s %-62s bridge=%s (want %s)' % ('ok' if ok else 'FAIL', desc, names.get(got, got), names.get(want, want)))
        if not ok:
            failures.append(desc)

    if failures:
        print('\nFAIL: %d problem(s)%s' % (len(failures), ' [BASELINE %s]' % BASE_REF if BASELINE else ''))
        sys.exit(1)
    print('\nPASS: the bridge reaches only our pages, plugins and connected portals (%d frame chains)' % len(CASES))


if __name__ == '__main__':
    main()
