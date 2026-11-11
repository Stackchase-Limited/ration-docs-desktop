#!/usr/bin/env python3
"""
#1664 (security follow-up) - a symbolic link inside an allowed folder let
file:// pages and the bridge read any file.

desktop-sdk 67c62bc5 limited what our file:// pages (browser: the file://
gate in cefview.cpp GetResourceHandler) and the bridge's file functions
(renderer: NSSystem::CLocalFilesResolver in applicationmanager_p.h) may read
to a list of folders: the application, system and user plugins, recovery,
temp, fonts and templates caches. The folders were compared as TEXT
(file_access.h NormalizePath + IsInDir): "..", "%2e%2e" and "%2F.." were
refused, but a symbolic link (or a Windows junction) inside a folder was not
looked at. A plugin folder copied or cloned into the user plugins folder with
"data.txt -> ~/.ssh/id_rsa" (or a linked sub-folder) was served to any file://
page by XHR and handed out by GetImageBase64/getOfficeFileType/"get"; a link
named like an ordinary file could also point at the excluded encryption files
(cloud_crypto.xml) beside it. CheckFont (LoadFontBase64, and Check() for every
bridge function) looked only at the folder of the path: any link in a font
folder passed. The onlyoffice://plugin and ascdesktop:// scheme handlers checked
the path WITH its "?lang=" / "__ascdesktopeditor__param__" suffix and then
opened the path without it.

Now:
- file_access.h ResolvePath: what the file system opens (realpath on macOS and
  Linux; CreateFileW + GetFinalPathNameByHandleW on Windows), a missing name as
  its resolved folder plus the name, a link to nowhere refused; IsFontFile.
- CLocalFilesResolver::CheckFolders: in a folder as text AND the resolved path
  in one of the folders' resolved paths (so links in the folders' own paths,
  /var -> /private/var, and the app bundle's framework links still match), and
  the excluded names checked on the resolved name. CheckFont: a link that leads
  out of the font folders must lead to a font.
- client_scheme_wrapper.cpp: the plugin handlers check the file that is opened
  (asc_scheme::get_opened_file), the fonts handler too.

This compiles the REAL file_access.h, the REAL CLocalFilesResolver (brace
matching from applicationmanager_p.h), the REAL resolver set-up of the browser
and the renderer, the REAL file:// gate of GetResourceHandler and the REAL
asc_scheme::get_url_params/get_opened_file, against stubs (copied from
issue-1664-file-access), in a temporary tree laid out like the app's folders
whose ROOT IS ITSELF REACHED THROUGH A SYMBOLIC LINK, and checks a table: the
reads the app makes (incl. through a framework-style Versions/Current link, a
link inside one plugin, a font linked from another font folder, a file picked
in a dialog that is a link, a missing file) are allowed; links to outside
files/folders, to the excluded keys, dangling links, a missing file under a
linked folder, a link in a font folder to a non-font, and the scheme suffix
trick are refused; "..", "%2e%2e", "%2F.." stay refused.

BASELINE=1 reads the sources at BASE_REF: the link rows are allowed - FAIL.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read sources at BASE_REF; must FAIL
  BASE_REF                         default 8a118ef3^ (the parent of the fix)

NOT claimed here: the Windows branch of ResolvePath (not compiled here: junctions,
"\\\\?\\UNC\\" prefixes); that CEF opens exactly the checked path (a link swapped in
between check and open is not stopped - the check narrows, it is not a sandbox);
hard links (they are the file itself; our unzip makes none, see file_access.h);
macOS Finder aliases and Windows .lnk files are not followed by any file call, so
they need nothing. The running app was checked separately (see the report).
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
BASE_REF = os.environ.get('BASE_REF', '8a118ef3^')
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

// --- scheme handlers (client_scheme_wrapper.cpp): what IsResolveLocalFile is asked about the file
// read_file_with_urls opens; at the baseline the path as it came (with its query/range suffix)
namespace asc_scheme {
@@SCHEME_FUNCS@@
}
static std::wstring SchemeCheckedPath(const std::wstring& sFile)
{
#ifdef HAVE_OPENED_FILE
	return asc_scheme::get_opened_file(sFile);
#else
	return sFile;
#endif
}

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
		else if (op == "scheme")
			res = oInternal.m_oLocalFilesResolver.Check(SchemeCheckedPath(U2W(arg))) ? 1 : 0;
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


G = '{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}'
EVIL = '{EEEEEEEE-0000-0000-0000-000000000001}'
FONT = b'\x00\x01\x00\x00' + b'\x00' * 60
PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 64


def layout(real_root, root):
    """real_root: the directory; root: a symbolic link to it (all folders are reached through it)."""
    for d in ['app/editors/web-apps', 'app/editors/sdkjs-plugins/' + G, 'app/login', 'app/Frameworks/X.framework/Versions/A/Resources',
              'data/recovery/DE__a/media', 'data/data/sdkjs-plugins/' + G, 'data/data/fonts', 'data/data/templates_cache/100',
              'data/data/cache', 'tmp/rd-1', 'sysfonts', 'otherfonts', 'outside/dir', 'docs']:
        os.makedirs(os.path.join(real_root, d), exist_ok=True)
    os.symlink(real_root, root)
    R = root
    files = [('outside/secret.txt', b'id_rsa'), ('outside/dir/index.html', b'<script>evil</script>'), ('outside/pic.png', PNG),
             ('data/data/sdkjs-plugins/cloud_crypto.xml', b'<keys/>'), ('data/data/sdkjs-plugins/' + G + '/real.js', b'1'),
             ('data/data/sdkjs-plugins/' + G + '/index.html', b'<html>'), ('data/recovery/DE__a/media/image1.png', PNG),
             ('app/Frameworks/X.framework/Versions/A/Resources/Info.plist', b'<plist/>'), ('app/login/index.html', b'<html>'),
             ('sysfonts/Arial.ttf', FONT), ('otherfonts/Real.ttf', FONT), ('data/data/fonts/AllFonts.js', b'1')]
    for f, b in files:
        open(os.path.join(real_root, f), 'wb').write(b)
    up = R + '/data/data/sdkjs-plugins'
    links = [
        # (link, target) - targets as a cloned/copied plugin could carry them
        (up + '/' + G + '/data.txt', R + '/outside/secret.txt'),
        (up + '/' + G + '/rel.txt', '../../../../outside/secret.txt'),
        (up + '/' + G + '/keys.txt', '../cloud_crypto.xml'),
        (up + '/' + G + '/ok.js', 'real.js'),
        (up + '/' + G + '/dangling.txt', R + '/outside/nothing'),
        (up + '/' + G + '/pic.png', R + '/outside/pic.png'),
        (up + '/' + EVIL, R + '/outside/dir'),
        (R + '/data/recovery/DE__a/media/image2.png', R + '/outside/secret.txt'),
        (R + '/tmp/rd-1/x.bin', R + '/outside/secret.txt'),
        # macOS framework layout inside the application
        (R + '/app/Frameworks/X.framework/Versions/Current', 'A'),
        (R + '/app/Frameworks/X.framework/Resources', 'Versions/Current/Resources'),
        (R + '/sysfonts/evil.ttf', R + '/outside/secret.txt'),
        (R + '/sysfonts/linked.ttf', R + '/otherfonts/Real.ttf'),
        (R + '/outside/picked-link.png', 'pic.png'),
    ]
    for link, target in links:
        os.symlink(target, link)
    with open(os.path.join(real_root, 'data/data/fonts/fonts.log'), 'w') as f:
        f.write('ONLYOFFICE_FONTS_VERSION_9\n%s/sysfonts/Arial.ttf\n%s/sysfonts/linked.ttf\n' % (R, R))
    with open(os.path.join(real_root, 'data/recents.xml'), 'w') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?><recents></recents>')


def build_cases(R):
    app = R + '/app'
    up = R + '/data/data/sdkjs-plugins'
    rec = R + '/data/recovery'
    appu = 'file://' + app.replace(' ', '%20')
    upu = 'file://' + up.replace(' ', '%20')
    P = up + '/' + G
    PU = upu + '/' + G
    cases = [
        ('page-local', appu + '/editors/web-apps/apps/documenteditor/main/index.html', None, 'renderer of a local editor page'),
        ('dialog', R + '/outside/picked-link.png', None, 'user picks a file in a dialog (it is a link)'),
        # still allowed
        ('check', P + '/real.js', 1, 'bridge: user plugin file (root reached through a link)'),
        ('check', P + '/ok.js', 1, 'bridge: link to a file of the same plugin'),
        ('check', P + '/missing.json', 1, 'bridge: missing file in a plugin (no link)'),
        ('check', rec + '/DE__a/media/image1.png', 1, 'bridge: document media'),
        ('check', app + '/Frameworks/X.framework/Resources/Info.plist', 1, 'bridge: app file through framework links'),
        ('check', R + '/outside/picked-link.png', 1, 'bridge: dialog file that is a link'),
        ('checkfont', R + '/sysfonts/Arial.ttf', 1, 'LoadFontBase64: font'),
        ('checkfont', R + '/sysfonts/linked.ttf', 1, 'LoadFontBase64: link to a font elsewhere'),
        ('pageread', P + '/index.html', 1, 'browser: user plugin page'),
        ('pageread', app + '/Frameworks/X.framework/Resources/Info.plist', 1, 'browser: app file through framework links'),
        ('pageread', app + '/login/index.html', 1, 'browser: start page'),
        ('gate-xhr', PU + '/ok.js', 1, 'gate: XHR of a link inside the plugin'),
        ('gate-xhr', appu + '/login/index.html', 1, 'gate: start page'),
        ('gate-img', PU + '/pic.png', 1, 'gate: <img> link to a picture outside (as before)'),
        ('scheme', P + '/real.js__ascdesktopeditor__param__0__ascdesktopeditor__param__10', 1, 'scheme: range request of a plugin file'),
        # refused now
        ('check', P + '/data.txt', 0, 'bridge: plugin link -> outside file (absolute)'),
        ('check', P + '/rel.txt', 0, 'bridge: plugin link -> outside file (relative)'),
        ('check', P + '/keys.txt', 0, 'bridge: plugin link -> excluded cloud_crypto.xml'),
        ('check', P + '/dangling.txt', 0, 'bridge: dangling link'),
        ('check', up + '/' + EVIL + '/index.html', 0, 'bridge: linked plugin folder -> outside'),
        ('check', up + '/' + EVIL + '/new.txt', 0, 'bridge: missing file under a linked folder'),
        ('check', rec + '/DE__a/media/image2.png', 0, 'bridge: recovery link -> outside'),
        ('checknofont', R + '/tmp/rd-1/x.bin', 0, 'get/GetOpenedFile: temp link -> outside'),
        ('check', R + '/sysfonts/evil.ttf', 0, 'bridge: font-folder link -> non-font'),
        ('checkfont', R + '/sysfonts/evil.ttf', 0, 'LoadFontBase64: font-folder link -> non-font'),
        ('pageread', P + '/data.txt', 0, 'browser: plugin link -> outside file'),
        ('pageread', up + '/' + EVIL + '/index.html', 0, 'browser: page in a linked plugin folder'),
        ('gate-xhr', PU + '/data.txt', 0, 'gate: XHR of plugin link -> outside'),
        ('gate-xhr', PU + '/keys.txt', 0, 'gate: XHR of plugin link -> keys'),
        ('gate-xhr', upu + '/' + EVIL + '/index.html', 0, 'gate: navigation into a linked plugin folder'),
        ('gate-img', PU + '/data.txt', 0, 'gate: <img> of plugin link -> non-picture'),
        ('scheme', P + '/data.txt__ascdesktopeditor__param__0', 0, 'scheme: link with range suffix'),
        # textual escapes (refused since 67c62bc5, kept here)
        ('gate-xhr', PU + '/../../settings.xml', 0, 'gate: ".." in a file URL'),
        ('gate-xhr', PU + '/%2e%2e/%2e%2e/settings.xml', 0, 'gate: "%2e%2e" in a file URL'),
        ('gate-xhr', PU + '%2F..%2F..%2Fsettings.xml', 0, 'gate: "%2F.." in a file URL'),
        ('check', P + '/../../settings.xml', 0, 'bridge: ".." in a path'),
    ]
    return cases


def main():
    header = read(SRC + 'file_access.h', missing_ok=True)
    manager_p = read(SRC + 'applicationmanager_p.h')
    utils = read(SRC + 'utils.h')
    capp = read(SRC + 'cefapplication.cpp')
    view = read(SRC + 'cefview.cpp')
    wrapper = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')
    scheme = read(SRC + 'cefwrapper/client_scheme_wrapper.cpp')

    failures = []
    resolver = brace_block(manager_p, '\tclass CLocalFilesResolver\n')
    url_correct = brace_block(utils, 'static void url_correct(')
    a = capp.find('// local files resolver')
    b = capp.find('NSFile::CFileBinary::SetTempPath(sTempDirectory);', a)
    browser_init = capp[a:b]
    renderer_init = brace_block(wrapper, 'if (!g_pLocalResolver.is_init())')
    grh = brace_block(view, 'virtual CefRefPtr<CefResourceHandler> GetResourceHandler(')
    gate = brace_block(grh, 'if (0 == url.find(L"file://"))') if grh else None
    get_url_params = brace_block(scheme, 'std::vector<std::wstring> get_url_params(std::wstring& sUrl)')
    get_opened = brace_block(scheme, 'static std::wstring get_opened_file(')
    for name, v in [('file_access.h', header), ('CLocalFilesResolver', resolver), ('url_correct', url_correct),
                    ('browser resolver set-up', browser_init), ('renderer resolver set-up', renderer_init), ('file:// gate', gate),
                    ('get_url_params', get_url_params)]:
        if not v:
            sys.exit('%s not found' % name)

    # wiring the table cannot see: each scheme handler checks what read_binary_file opens, i.e.
    # after it cut "?lang=" off (the table's "scheme" rows cover the range suffix)
    reads = [m.start() for m in re.finditer(r'read_binary_file\(sFile, true\);', scheme)]
    wired = len(reads) == 2
    for pos in reads:
        before = scheme[max(0, pos - 300):pos]
        if 'IsResolveLocalFile(asc_scheme::get_opened_file(sFile))' not in before:
            wired = False
    fonts = brace_block(scheme, 'posFind = url.find("ascdesktop://fonts/");') or ''
    wired = wired and 'IsResolveLocalFile(asc_scheme::get_opened_file(sFile))' in fonts
    print('%-4s %s' % ('ok' if wired else 'FAIL', 'scheme handlers (plugin_content, onlyoffice://plugin, fonts) check the opened file'))
    if not wired:
        failures.append('scheme handler wiring')

    work = tempfile.mkdtemp(prefix='rd1664s-')
    try:
        real_root = os.path.join(work, 'real root')
        root = os.path.join(work, 'Root Dir')
        layout(real_root, root)
        with open(os.path.join(work, 'file_access.h'), 'w', encoding='utf-8') as f:
            f.write(header)
        src = DRIVER.replace('@@FILE_ACCESS_INCLUDE@@', '#include "file_access.h"') \
            .replace('@@STUBS@@', STUBS.replace('@@URL_CORRECT@@', url_correct)) \
            .replace('@@RESOLVER@@', resolver) \
            .replace('@@BROWSER_INIT@@', browser_init) \
            .replace('@@RENDERER_INIT@@', renderer_init) \
            .replace('@@GATE@@', gate) \
            .replace('@@SCHEME_FUNCS@@', get_url_params + '\n' + (get_opened or ''))
        src = '#define HAVE_PAGE_READ\n' + ('#define HAVE_OPENED_FILE\n' if get_opened else '') + src
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
    print('\nPASS: links inside the allowed folders are followed before the check (%d checks)' % (1 + sum(1 for c in cases if c[2] is not None)))


if __name__ == '__main__':
    main()
