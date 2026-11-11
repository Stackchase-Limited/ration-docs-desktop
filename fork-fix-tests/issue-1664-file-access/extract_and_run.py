#!/usr/bin/env python3
"""
#1664 (security follow-up) - a script in one of our file:// pages could read ANY
local file, two ways.

1. --allow-file-access-from-files (it has to stay: the editors XHR their
   templates and locales from file://) makes every file:// URL same-origin, so
   an XHR from the editor frame to file:///etc/hosts returned the file (seen
   in a copy of the test app: status 200, 971 bytes). The browser's resource
   handler (desktop-sdk cefview.cpp CAscClientHandler::GetResourceHandler) sees
   every file:// request but served them all.
2. The bridge's file functions (GetImageBase64, getOfficeFileType,
   _convertFileExternal, LoadFontBase64, GetOpenedFile, "get") ask the
   renderer's NSSystem::CLocalFilesResolver (applicationmanager_p.h), whose
   Check/CheckNoFont/CheckFont returned true for ANY path once m_bIsLocalUrl
   was set - i.e. for every file:// page. GetImageBase64("/etc/hosts", true)
   returned the file as base64. Folders were also compared by prefix only
   ("<recovery>" allowed "<recovery>-evil/...").

Now:
- file_access.h (new, pure C++): FileUrlToPath (decodes, refuses network hosts,
  broken escapes, NUL), NormalizePath (refuses "..", relative paths, NUL),
  IsInDir (whole folder names), GetApplicationDirectory.
- CLocalFilesResolver: no "any path" for local pages; folders compared with
  IsInDir; a file:// page additionally gets m_arLocalUrlFolders (the
  application, system and user plugins minus the encryption files, the temp
  folder, the fonts cache) and the documents in recents.xml (the AI agent
  attaches recent files); CheckLocalPageRead is what the browser serves to
  file:// requests: the resolver's folders (recovery, plugins, temp), the
  application, the fonts and templates caches, files picked in a dialog/dropped.
- GetResourceHandler starts with a file:// gate: outside CheckLocalPageRead it
  answers with CAscFileAccessDeniedHandler (net::ERR_ACCESS_DENIED), except an
  <img> (RT_IMAGE) whose file really is a picture (pasted HTML refers to its
  pictures by file:// URL and the editor sizes them from the loaded element).

This compiles the REAL file_access.h, the REAL CLocalFilesResolver class (by
brace matching from applicationmanager_p.h), the REAL resolver set-up of the
browser (cefapplication.cpp, "// local files resolver" .. SetTempPath) and of
the renderer (client_renderer_wrapper.cpp, the `if (!g_pLocalResolver.is_init())`
block) and the REAL file:// gate block of GetResourceHandler, against stubs
for NSFile/XmlUtils/critical sections/CEF request objects, in a temporary
directory laid out like the app's folders, and checks a table: every read the
running app made in a scripted session (see the report) is still allowed, and
/etc/hosts, the user's settings and cookies, the plugins' encryption keys, an
unopened document, a sibling folder with the same prefix, "..", "%2F.." and a
network share are refused.

BASELINE=1 reads the sources at BASE_REF: file_access.h and the gate do not
exist (every file:// URL is served) and the resolver allows any path to a
file:// page - the table FAILS.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read sources at BASE_REF; must FAIL
  BASE_REF                         default 67c62bc5^ (the parent of the fix)

NOT claimed here: CImageFileFormatChecker is a stub (PNG magic only); that CEF
calls GetResourceHandler for every file:// request of a page (seen live: the
denials in the session log), the renderer's image fallbacks in GetImageBase64/
LocalFileGetImageUrl (checked only by the structural asserts below and live).
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
BASE_REF = os.environ.get('BASE_REF', '67c62bc5^')
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


def brace_block(text, start, from_pos=0):
    """From the line holding `start` to its matching closing brace."""
    a = text.find(start, from_pos)
    if a < 0:
        return None
    a = text.rfind('\n', 0, a) + 1
    b = text.find('{', a)
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
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


STUBS = r'''
#include <string>
#include <vector>
#include <set>
#include <map>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <iostream>
#include <locale>
#include <codecvt>
typedef unsigned char BYTE; typedef unsigned int DWORD; typedef long LONG;
static std::string W2U(const std::wstring& s) { std::wstring_convert<std::codecvt_utf8<wchar_t>> c; return c.to_bytes(s); }
static std::wstring U2W(const std::string& s) { std::wstring_convert<std::codecvt_utf8<wchar_t>> c; return c.from_bytes(s); }
#define UTF8_TO_U(val) U2W(val)
namespace NSStringUtils {
	static void string_replace(std::wstring& s, const std::wstring& a, const std::wstring& b) {
		for (size_t p = s.find(a); p != std::wstring::npos; p = s.find(a, p + b.length())) s.replace(p, a.length(), b);
	}
}
namespace NSFile {
	static std::wstring GetFileName(const std::wstring& s) { size_t p = s.find_last_of(L"/\\"); return p == std::wstring::npos ? s : s.substr(p + 1); }
	static std::wstring GetDirectoryName(const std::wstring& s) { size_t p = s.find_last_of(L"/\\"); return p == std::wstring::npos ? L"" : s.substr(0, p); }
	struct CUtf8Converter { static std::wstring GetUnicodeStringFromUTF8(BYTE* p, LONG n) { return U2W(std::string((char*)p, n)); } };
	class CFileBinary {
		std::string m_data; bool m_open = false;
	public:
		bool OpenFile(const std::wstring& f) { std::ifstream i(W2U(f), std::ios::binary); if (!i) return false; std::stringstream ss; ss << i.rdbuf(); m_data = ss.str(); m_open = true; return true; }
		long GetFileSize() { return (long)m_data.size(); }
		bool ReadFile(BYTE* p, DWORD n, DWORD& r) { r = n < m_data.size() ? n : (DWORD)m_data.size(); memcpy(p, m_data.data(), r); return true; }
		void CloseFile() { m_open = false; }
	};
}
namespace NSCriticalSection { struct CRITICAL_SECTION { void InitializeCriticalSection() {} void DeleteCriticalSection() {} void Enter() {} void Leave() {} }; }
struct CTemporaryCS { CTemporaryCS(NSCriticalSection::CRITICAL_SECTION*) {} };
namespace XmlUtils {
	// enough of CXmlNode for recents.xml: <recents><file path="..." .../></recents>
	class CXmlNode {
	public:
		std::map<std::wstring, std::wstring> attrs; std::vector<CXmlNode> kids;
		bool FromXmlFile(const std::wstring& f) {
			std::ifstream i(W2U(f)); if (!i) return false; std::stringstream ss; ss << i.rdbuf(); std::string t = ss.str();
			for (size_t p = t.find("<file "); p != std::string::npos; p = t.find("<file ", p + 1)) {
				size_t e = t.find('>', p); std::string tag = t.substr(p, e - p); CXmlNode n;
				size_t a = tag.find("path=\""); if (a != std::string::npos) { size_t b = tag.find('"', a + 6); std::string v = tag.substr(a + 6, b - a - 6);
					for (size_t q = v.find("&amp;"); q != std::string::npos; q = v.find("&amp;", q + 1)) v.replace(q, 5, "&");
					n.attrs[L"path"] = U2W(v); }
				kids.push_back(n);
			}
			return true;
		}
		std::vector<CXmlNode> GetNodes(const std::wstring&) { return kids; }
		std::wstring GetAttribute(const std::wstring& k) { return attrs.count(k) ? attrs[k] : L""; }
	};
}
// stub: a picture is a PNG (magic bytes)
struct CImageFileFormatChecker {
	bool isImageFile(const std::wstring& f) { std::ifstream i(W2U(f), std::ios::binary); char b[8] = {0}; i.read(b, 8); return i.gcount() == 8 && 0 == memcmp(b, "\x89PNG\r\n\x1a\n", 8); }
};
namespace NSCommon {
	template <class T> class smart_ptr { T* p = nullptr; public: smart_ptr() {} smart_ptr(T* x) : p(x) {} smart_ptr& operator=(T* x) { delete p; p = x; return *this; }
		bool is_init() const { return p != nullptr; } T* operator->() const { return p; } void reset() { delete p; p = nullptr; } };
@@URL_CORRECT@@
}
'''

DRIVER = r'''
#include <cstring>
@@FILE_ACCESS_INCLUDE@@
@@STUBS@@
namespace NSSystem {
@@RESOLVER@@;
}

// --- browser side -------------------------------------------------------------------------------
struct CSettings { std::wstring fonts_cache_info_path, recover_path, user_plugins_path, system_plugins_path, templates_cache_info_path; };
struct CInternal { NSSystem::CLocalFilesResolver m_oLocalFilesResolver; std::wstring m_sTmp; std::wstring StartTmpDirectory() { return m_sTmp; } };
struct CAppManager { CInternal* m_pInternal; CSettings m_oSettings; };
static void BrowserInit(CAppManager* pManager)
{
@@BROWSER_INIT@@
}
struct CefString { std::string s; CefString(const std::string& x) : s(x) {} std::string ToString() const { return s; } std::wstring ToWString() const { return U2W(s); } };
enum { RT_IMAGE = 5, RT_XHR = 13 };
struct CRequest { std::string url; int type; CefString GetURL() { return CefString(url); } int GetResourceType() { return type; } };
struct CFrame { CefString GetURL() { return CefString("file:///app/editors/web-apps/apps/documenteditor/main/index.html"); } };
template <class T> struct CefRefPtr { T* p; CefRefPtr(T* x) : p(x) {} T* operator->() const { return p; } operator bool() const { return p != 0; } };
struct CAscFileAccessDeniedHandler {};
struct CParent { CAppManager* m; CAppManager* GetAppManager() { return m; } };
struct CHandler {
	CParent* m_pParent;
	void* Gate(CRequest* pRequest)
	{
		CefRefPtr<CRequest> request(pRequest); CefRefPtr<CFrame> frame(new CFrame());
		std::wstring url = request->GetURL().ToWString();
@@GATE@@
		return 0;
	}
};

// --- renderer side ------------------------------------------------------------------------------
NSCommon::smart_ptr<NSSystem::CLocalFilesResolver> g_pLocalResolver;
static void RendererInit(const std::wstring& sUrl, const std::wstring& m_sFontsData, const std::wstring& m_sRecoversFolder,
	const std::wstring& m_sSystemPlugins, const std::wstring& m_sUserPlugins, const std::wstring& m_sAppTmpFolder)
{
	g_pLocalResolver.reset();
@@RENDERER_INIT@@
}

int main(int argc, char** argv)
{
	// argv: root, then stdin lines "<op>\t<arg>" (op: page-local, page-remote, check, checkfont,
	// pageread, dialog, gate-xhr, gate-img)
	std::string R = argv[1]; std::wstring W = U2W(R);
	CAppManager oManager; CInternal oInternal; oManager.m_pInternal = &oInternal;
	oInternal.m_sTmp = W + L"/tmp/rd-1";
	oManager.m_oSettings.fonts_cache_info_path = W + L"/data/data/fonts";
	oManager.m_oSettings.recover_path = W + L"/data/recovery";
	oManager.m_oSettings.user_plugins_path = W + L"/data/data/sdkjs-plugins";
	oManager.m_oSettings.system_plugins_path = W + L"/app/editors/sdkjs-plugins";
	oManager.m_oSettings.templates_cache_info_path = W + L"/data/data/templates_cache";
	BrowserInit(&oManager);
	CParent oParent; oParent.m = &oManager; CHandler oHandler; oHandler.m_pParent = &oParent;

	char line[8192];
	while (fgets(line, sizeof(line), stdin))
	{
		std::string l(line); while (!l.empty() && (l.back() == '\n' || l.back() == '\r')) l.pop_back();
		size_t t = l.find('\t'); std::string op = l.substr(0, t), arg = (t == std::string::npos) ? "" : l.substr(t + 1);
		int res = -1;
		if (op == "page-local" || op == "page-remote")
		{
			RendererInit(U2W(arg), oManager.m_oSettings.fonts_cache_info_path, oManager.m_oSettings.recover_path,
				oManager.m_oSettings.system_plugins_path, oManager.m_oSettings.user_plugins_path, oInternal.m_sTmp);
			res = 1;
		}
		else if (op == "dialog") { g_pLocalResolver->AddFile(U2W(arg)); oInternal.m_oLocalFilesResolver.AddFile(U2W(arg)); res = 1; }
		else if (op == "check") res = g_pLocalResolver->Check(U2W(arg)) ? 1 : 0;
		else if (op == "checknofont") res = g_pLocalResolver->CheckNoFont(U2W(arg)) ? 1 : 0;
		else if (op == "checkfont") res = g_pLocalResolver->CheckFont(U2W(arg)) ? 1 : 0;
		else if (op == "pageread")
		{
#ifdef HAVE_PAGE_READ
			res = oInternal.m_oLocalFilesResolver.CheckLocalPageRead(U2W(arg)) ? 1 : 0;
#else
			res = 1; // no file:// gate: the browser served every file:// request
#endif
		}
		else if (op == "gate-xhr" || op == "gate-img")
		{
			CRequest oRequest; oRequest.url = arg; oRequest.type = (op == "gate-img") ? RT_IMAGE : RT_XHR;
			res = oHandler.Gate(&oRequest) ? 0 : 1;
		}
		printf("%d\n", res);
	}
	return 0;
}
'''


def build_cases(root):
    app = root + '/app'
    data = root + '/data'
    rec = data + '/recovery'
    userp = data + '/data/sdkjs-plugins'
    tmp = root + '/tmp/rd-1'
    fonts = data + '/data/fonts'
    tpl = data + '/data/templates_cache'
    sysfonts = root + '/sysfonts'
    out = root + '/outside'
    docs = root + '/docs'
    appu = 'file://' + app.replace(' ', '%20')
    G = '{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}'
    # (op, arg, expected or None for a set-up line, description)
    cases = [
        ('page-local', appu + '/editors/web-apps/apps/documenteditor/main/index.html', None, 'renderer of a local editor page'),
        ('dialog', out + '/picked.png', None, 'user picks a file in a dialog'),
        # what the running app read through the bridge in the session
        ('check', rec + '/DE__a/Editor.bin', 1, 'bridge: the document\'s Editor.bin (recovery folder)'),
        ('check', 'file://' + rec + '/DE__a/media/image1.png', 1, 'bridge: a media file as a file:// URL'),
        ('check', app + '/editors/sdkjs-plugins/' + G + '/index.js', 1, 'bridge: bundled plugin file'),
        ('check', userp + '/' + G + '/config.json', 1, 'bridge: user plugin file'),
        ('check', tmp + '/IMG1.png', 1, 'bridge: app temp folder'),
        ('check', fonts + '/AllFonts.js', 1, 'bridge: fonts cache'),
        ('check', sysfonts + '/Arial.ttf', 1, 'bridge: font in a folder of fonts.log'),
        ('check', out + '/picked.png', 1, 'bridge: file picked in a dialog'),
        ('check', docs + '/recent.docx', 1, 'bridge: recent document (AI agent attach)'),
        ('checkfont', sysfonts + '/Arial.ttf', 1, 'LoadFontBase64: system font'),
        # must be refused
        ('check', '/etc/hosts', 0, 'bridge: /etc/hosts'),
        ('check', 'file:///etc/hosts', 0, 'bridge: file:///etc/hosts'),
        ('checkfont', '/etc/hosts', 0, 'LoadFontBase64: /etc/hosts'),
        ('checknofont', '/etc/hosts', 0, 'get/GetOpenedFile: /etc/hosts'),
        ('check', out + '/secret.docx', 0, 'bridge: a document never opened'),
        ('check', docs + '/other.docx', 0, 'bridge: neighbour of a recent document'),
        ('check', userp + '/cloud_crypto.xml', 0, 'bridge: plugins\' encryption keys'),
        ('check', data + '/data/settings.xml', 0, 'bridge: user settings'),
        ('check', data + '/data/cache/Cookies', 0, 'bridge: cookies'),
        ('check', rec + '-evil/x.bin', 0, 'bridge: sibling folder with the recovery prefix'),
        ('check', rec + '/../../../etc/hosts', 0, 'bridge: recovery/../../../etc/hosts'),
        ('check', rec + '/DE__a/../../data/settings.xml', 0, 'bridge: recovery/x/../../data/settings.xml'),
        ('page-remote', 'https://portal.example.com/doceditor', None, 'renderer of a cloud portal page'),
        ('check', rec + '/DE__a/Editor.bin', 1, 'portal: recovery folder (as before)'),
        ('check', tmp + '/IMG1.png', 0, 'portal: temp folder (as before: not for remote pages)'),
        ('check', '/etc/hosts', 0, 'portal: /etc/hosts'),
        # browser: what our file:// pages may load
        ('pageread', app + '/login/index.html', 1, 'browser: start page'),
        ('pageread', app + '/editors/web-apps/apps/documenteditor/main/locale/en.json', 1, 'browser: locale'),
        ('pageread', tpl + '/100/Agenda .jpg', 1, 'browser: template thumbnail'),
        ('pageread', rec + '/DE__a/media/image1.png', 1, 'browser: document media'),
        ('pageread', userp + '/' + G + '/index.html', 1, 'browser: user plugin page'),
        ('pageread', fonts + '/AllFonts.js', 1, 'browser: fonts cache'),
        ('pageread', out + '/picked.png', 1, 'browser: file picked in a dialog'),
        ('pageread', '/etc/hosts', 0, 'browser: /etc/hosts'),
        ('pageread', data + '/data/settings.xml', 0, 'browser: user settings'),
        ('pageread', data + '/data/cache/Cookies', 0, 'browser: cookies'),
        ('pageread', userp + '/cloud_crypto.xml', 0, 'browser: plugins\' encryption keys'),
        ('pageread', out + '/secret.docx', 0, 'browser: a document never opened'),
        ('pageread', app + '-evil/x.html', 0, 'browser: sibling folder with the app prefix'),
        ('gate-xhr', appu + '/editors/web-apps/apps/documenteditor/main/locale/en.json', 1, 'gate: XHR of a locale'),
        ('gate-xhr', 'file:///etc/hosts', 0, 'gate: XHR file:///etc/hosts'),
        ('gate-xhr', 'file://localhost/etc/hosts', 0, 'gate: XHR file://localhost/etc/hosts'),
        ('gate-xhr', appu + '/editors%2F..%2F..%2F..%2F..%2F..%2F..%2F..%2F..%2Fetc%2Fhosts', 0, 'gate: XHR with %2F..'),
        ('gate-xhr', 'file://server/share/x.docx', 0, 'gate: network share'),
        ('gate-xhr', 'file://' + out.replace(' ', '%20') + '/pic.png', 0, 'gate: XHR of a picture outside'),
        ('gate-img', 'file://' + out.replace(' ', '%20') + '/pic.png', 1, 'gate: <img> of a picture outside (pasted HTML)'),
        ('gate-img', 'file://' + out.replace(' ', '%20') + '/secret.docx', 0, 'gate: <img> of a non-picture outside'),
    ]
    return cases


def layout(root):
    for d in ['app/editors/web-apps', 'app/editors/sdkjs-plugins', 'app/login', 'data/recovery/DE__a/media', 'data/data/sdkjs-plugins',
              'data/data/fonts', 'data/data/templates_cache/100', 'data/data/cache', 'tmp/rd-1', 'sysfonts', 'outside', 'docs']:
        os.makedirs(os.path.join(root, d), exist_ok=True)
    png = b'\x89PNG\r\n\x1a\n' + b'\0' * 64
    for f, b in [('outside/pic.png', png), ('outside/picked.png', png), ('outside/secret.docx', b'PK\3\4secret'),
                 ('docs/recent.docx', b'PK\3\4'), ('docs/other.docx', b'PK\3\4')]:
        open(os.path.join(root, f), 'wb').write(b)
    with open(os.path.join(root, 'data/data/fonts/fonts.log'), 'w') as f:
        f.write('ONLYOFFICE_FONTS_VERSION_9\n%s/sysfonts/Arial.ttf\n' % root)
    with open(os.path.join(root, 'data/recents.xml'), 'w') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?><recents><file path="%s/docs/recent.docx" type="65" /></recents>' % root)


def main():
    header = read(SRC + 'file_access.h', missing_ok=True)
    manager_p = read(SRC + 'applicationmanager_p.h')
    utils = read(SRC + 'utils.h')
    capp = read(SRC + 'cefapplication.cpp')
    view = read(SRC + 'cefview.cpp')
    wrapper = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')

    failures = []
    resolver = brace_block(manager_p, '\tclass CLocalFilesResolver\n')
    url_correct = brace_block(utils, 'static void url_correct(')
    a = capp.find('// local files resolver')
    b = capp.find('NSFile::CFileBinary::SetTempPath(sTempDirectory);', a)
    browser_init = capp[a:b]
    renderer_init = brace_block(wrapper, 'if (!g_pLocalResolver.is_init())')
    grh = brace_block(view, 'virtual CefRefPtr<CefResourceHandler> GetResourceHandler(')
    gate = brace_block(grh, 'if (0 == url.find(L"file://"))') if grh else None
    if gate is not None and 'CAscFileAccessDeniedHandler' not in gate:
        gate = None
    for name, v in [('CLocalFilesResolver', resolver), ('url_correct', url_correct), ('browser resolver set-up', browser_init),
                    ('renderer resolver set-up', renderer_init), ('GetResourceHandler', grh)]:
        if not v:
            sys.exit('%s not found' % name)

    # structure that the table below cannot see
    print('file_access.h present:', header is not None)
    first_gate = grh.find('if (0 == url.find(L"file://"))')
    print('GetResourceHandler starts with the file:// gate:', gate is not None and first_gate >= 0 and
          first_gate < grh.find('#ifdef CEF_SUPPORT_STREAMING_CORS_RESOURCE_HANDLER'))
    denied = brace_block(view, 'class CAscFileAccessDeniedHandler') or ''
    print('denied handler answers net::ERR_ACCESS_DENIED:', 'SetError(ERR_ACCESS_DENIED)' in denied)
    gib = brace_block(wrapper, 'else if (name == "GetImageBase64")') or ''
    gib_ok = re.search(r'if \(!bIsAllowed && !bIsNoHeader\)', gib) is not None
    print('GetImageBase64: outside the folders only a picture, never raw bytes:', gib_ok)
    if header is None or gate is None or 'SetError(ERR_ACCESS_DENIED)' not in denied or not gib_ok:
        failures.append('structure (gate / denied handler / GetImageBase64 raw mode)')

    work = tempfile.mkdtemp(prefix='rd1664f-')
    try:
        root = os.path.join(work, 'Root Dir')
        layout(root)
        if header is not None:
            with open(os.path.join(work, 'file_access.h'), 'w', encoding='utf-8') as f:
                f.write(header)
        src = DRIVER.replace('@@FILE_ACCESS_INCLUDE@@', '#include "file_access.h"' if header is not None else '') \
            .replace('@@STUBS@@', STUBS.replace('@@URL_CORRECT@@', url_correct)) \
            .replace('@@RESOLVER@@', resolver) \
            .replace('@@BROWSER_INIT@@', browser_init) \
            .replace('@@RENDERER_INIT@@', renderer_init) \
            .replace('@@GATE@@', gate or '')
        if 'CheckLocalPageRead' in resolver:
            src = '#define HAVE_PAGE_READ\n' + src
        with open(os.path.join(work, 'driver.cpp'), 'w', encoding='utf-8') as f:
            f.write(src)
        exe = os.path.join(work, 'driver')
        r = subprocess.run(['c++', '-std=c++17', '-Wall', '-Wno-deprecated-declarations', '-Wno-unused-function', '-I', work, '-o', exe,
                            os.path.join(work, 'driver.cpp')], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit('compile failed:\n' + r.stderr[-4000:])
        cases = build_cases(root)
        stdin = ''.join('%s\t%s\n' % (op, arg) for op, arg, _, _ in cases)
        out = subprocess.run([exe, root], input=stdin, capture_output=True, text=True, check=True).stdout.split()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for (op, arg, want, desc), got in zip(cases, out):
        if want is None:
            print('     -- %s' % desc)
            continue
        ok = int(got) == want
        print('%-4s %-62s %s (want %s)' % ('ok' if ok else 'FAIL', desc, 'allowed' if got == '1' else 'refused', 'allowed' if want else 'refused'))
        if not ok:
            failures.append(desc)

    if failures:
        print('\nFAIL: %d problem(s)%s' % (len(failures), ' [BASELINE %s]' % BASE_REF if BASELINE else ''))
        sys.exit(1)
    print('\nPASS: file:// pages and the bridge read only the allowed folders (%d checks)' % sum(1 for c in cases if c[2] is not None))


if __name__ == '__main__':
    main()
