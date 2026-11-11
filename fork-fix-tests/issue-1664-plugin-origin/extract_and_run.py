#!/usr/bin/env python3
"""
#1664 follow-up (PLUGIN_ORIGIN_PLAN.md) - user-installed plugins shared the
editor's origin and its bridge.

A plugin from the user plugins folder was loaded as file:///<user plugins>/{GUID}/
(sdkjs common/Local/common.js UpdateInstallPlugins), or onlyoffice://plugin/<that>
with "onlyofficeScheme". With --allow-file-access-from-files every file:// page is
one origin, so the plugin's script could use parent.document and the editor's
window.AscDesktopEditor - the whole bridge; bridge_access.h also listed the user
plugins folder as trusted, so the plugin's own frame had the full bridge too.

Now each user plugin is rdplugin://<guid>/ (desktop-sdk plugin_scheme.h + the
handler in client_scheme_wrapper.cpp), with the Plugin tier of bridge_access.h:
an allowlist (IsPluginTierMethod). This test runs the REAL code:

1. plugin_scheme.h compiled with a driver against a real temporary user plugins
   folder (with symbolic links pointing out of it, a linked plugin folder, the
   encryption files, backup/ and v1/): which file each rdplugin URL serves.
2. bridge_access.h: rdplugin frame chains (Plugin tier only inside our pages or
   top-level), the user plugins folder no longer trusted for file:// and
   onlyoffice://plugin/, ForContextOrigin, the allowlist and generateNew types.
3. sdkjs: the real UpdateInstallPlugins (Local/common.js) and
   getDesktopUserPluginBaseUrl (editorscommon.js) in node with a stubbed
   AscDesktopEditor: user plugins get rdplugin://<guid>/, system ones keep
   file:// / onlyoffice://plugin/; and the real checkOrigin (common/plugins.js)
   accepts a plugin's messages from its rdplugin origin and refuses another's.
4. Wiring that cannot run without CEF, checked in the source: the scheme is
   registered with a handler, the onlyoffice:// and plugin_content handlers refuse
   the user plugins folder, the factory refuses user plugin requests to
   ascdesktop:// / onlyoffice://, GetResourceHandler refuses file:// pages from the
   user plugins folder, OnContextCreated builds the Plugin-tier bridge, the
   crypto password is not sent into user plugin frames.

NOT claimed here (checked live in a copy of the test app, see the report): CEF's
real behaviour (origins, SecurityError on parent.document, localStorage per
origin, workers/wasm under the scheme, the migration copy). The file dialog +
GetImageBase64 for a picked file was NOT clicked live (no accessibility access);
only the refusal of an unpicked path was seen live.

  RD_REPO=<desktop-sdk checkout>  (default ../../desktop-sdk)
  RD_SDKJS=<sdkjs checkout>       (default ../../sdkjs)
  BASELINE=1   read sources at BASE_REF / SDKJS_BASE_REF; must FAIL
  BASE_REF       default c9b26fce^   (desktop-sdk)
  SDKJS_BASE_REF default ff6eb2e4e3^ (sdkjs)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
SDKJS = os.environ.get('RD_SDKJS') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
BASE_REF = os.environ.get('BASE_REF', 'c9b26fce^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', 'ff6eb2e4e3^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'


def read(repo, ref, rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None
    p = os.path.join(repo, rel)
    return open(p, encoding='utf-8').read() if os.path.exists(p) else None


def sdk(rel):
    return read(REPO, BASE_REF, SRC + rel)


def js(rel):
    return read(SDKJS, SDKJS_BASE_REF, rel)


def block(text, start, opener='{', closer='}'):
    """From the line holding `start` to its matching closing brace (strings skipped)."""
    if text is None:
        return None
    a = text.find(start)
    if a < 0:
        return None
    a = text.rfind('\n', 0, a) + 1
    b = text.find(opener, text.find(start))
    depth = 0
    i = b
    while i < len(text):
        c = text[i]
        if c in '"\'':
            q = c
            i += 1
            while i < len(text) and text[i] != q:
                i += 2 if text[i] == '\\' else 1
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    return None


failures = []


def check(desc, ok, detail=''):
    print('%-4s %s%s' % ('ok' if ok else 'FAIL', desc, ('   [' + detail + ']') if detail else ''))
    if not ok:
        failures.append(desc)


def compile_run(work, name, src, stdin=''):
    cpp = os.path.join(work, name + '.cpp')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(src)
    exe = os.path.join(work, name)
    r = subprocess.run(['c++', '-std=c++17', '-Wall', '-Wno-unused-function', '-I', work, '-o', exe, cpp], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr
    out = subprocess.run([exe], input=stdin, capture_output=True, text=True)
    return out.stdout, out.stderr


# ---------------------------------------------------------------- 1. scheme paths
SCHEME_DRIVER = r'''
#include "plugin_scheme.h"
#include <iostream>
#include <cstdio>
int main()
{
	char line[4096];
	std::string sRoot;
	if (!fgets(line, sizeof(line), stdin)) return 1;
	sRoot = line; sRoot.erase(sRoot.find_last_not_of("\n") + 1);
	std::wstring wRoot = NSFileAccess::Utf8ToWide(sRoot);
	std::vector<std::wstring> arNames;
	while (fgets(line, sizeof(line), stdin))
	{
		std::string s = line; s.erase(s.find_last_not_of("\n") + 1);
		if (s == "--") break;
		arNames.push_back(NSFileAccess::Utf8ToWide(s));
	}
	while (fgets(line, sizeof(line), stdin))
	{
		std::string sUrl = line; sUrl.erase(sUrl.find_last_not_of("\n") + 1);
		std::string sHost, sPath;
		std::wstring sFile;
		if (NSPluginScheme::ParseUrl(sUrl, sHost, sPath))
			sFile = NSPluginScheme::GetFile(wRoot, arNames, sHost, sPath);
		std::cout << (sFile.empty() ? std::string("-") : NSFileAccess::WideToUtf8(sFile)) << "\n";
	}
	return 0;
}
'''


def scheme_tests(work, header):
    root = os.path.join(work, 'Application Support', 'data', 'sdkjs-plugins')
    outside = os.path.join(work, 'outside')
    os.makedirs(outside)
    with open(os.path.join(outside, 'secret.txt'), 'w') as f:
        f.write('secret')
    os.makedirs(os.path.join(outside, 'plugin'))
    with open(os.path.join(outside, 'plugin', 'index.html'), 'w') as f:
        f.write('<p>linked</p>')

    def w(rel, text='x'):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
            f.write(text)

    w('{AAAA0001-0000-4000-8000-000000000001}/index.html')
    w('{AAAA0001-0000-4000-8000-000000000001}/sub dir/x y.js')
    w('{AAAA0001-0000-4000-8000-000000000001}/translations/de-DE.json')
    w('{BBBB0002-0000-4000-8000-000000000002}/config.json')
    w('v1/plugins.js')
    w('pluginBase.js')
    w('plugins.css')
    w('cloud_crypto.xml')
    w('advanced_crypto_data.docx')
    w('addons/a.js')
    w('backup/{CCCC0003-0000-4000-8000-000000000003}/index.html')
    a = os.path.join(root, '{AAAA0001-0000-4000-8000-000000000001}')
    os.symlink(os.path.join(outside, 'secret.txt'), os.path.join(a, 'link.txt'))
    os.symlink(outside, os.path.join(a, 'dirlink'))
    os.symlink(os.path.join(root, 'cloud_crypto.xml'), os.path.join(a, 'keys.txt'))
    os.symlink(os.path.join(outside, 'plugin'), os.path.join(root, '{DDDD0004-0000-4000-8000-000000000004}'))
    os.symlink(os.path.join(outside, 'secret.txt'), os.path.join(root, 'v1', 'evil.js'))

    names = sorted(os.listdir(root))
    A = 'rdplugin://aaaa0001-0000-4000-8000-000000000001/'
    cases = [
        ('own page', A + 'index.html', '{AAAA0001-0000-4000-8000-000000000001}/index.html'),
        ('own file, encoded space, query and fragment', A + 'sub%20dir/x%20y.js?lang=de#top', '{AAAA0001-0000-4000-8000-000000000001}/sub dir/x y.js'),
        ('own translation', A + 'translations/de-DE.json', '{AAAA0001-0000-4000-8000-000000000001}/translations/de-DE.json'),
        ('shared plugin API ../v1/plugins.js', A + 'v1/plugins.js', 'v1/plugins.js'),
        ('shared pluginBase.js', A + 'pluginBase.js', 'pluginBase.js'),
        ('shared plugins.css', A + 'plugins.css', 'plugins.css'),
        ('host in upper case', 'RDPLUGIN://AAAA0001-0000-4000-8000-000000000001/index.html', '{AAAA0001-0000-4000-8000-000000000001}/index.html'),
        ('missing own file (404)', A + 'translations/xx.json', None),
        ('another plugin\'s file through ..', A + '../%7BBBBB0002-0000-4000-8000-000000000002%7D/config.json', None),
        ('another plugin\'s file through %2e%2e', A + '%2e%2e/%7BBBBB0002-0000-4000-8000-000000000002%7D/config.json', None),
        ('encryption keys through %2F..%2F', A + 'sub%20dir%2F..%2F..%2Fcloud_crypto.xml', None),
        ('encryption keys as a "shared" name', A + 'cloud_crypto.xml', None),
        ('advanced_crypto_data.docx', A + 'advanced_crypto_data.docx', None),
        ('addons/', A + 'addons/a.js', None),
        ('backslash', A + 'sub%20dir%5C..%5Cindex.html', None),
        ('link to a file outside', A + 'link.txt', None),
        ('link to the encryption keys beside the plugins', A + 'keys.txt', None),
        ('file in a linked folder outside', A + 'dirlink/secret.txt', None),
        ('plugin folder that is a link outside', 'rdplugin://dddd0004-0000-4000-8000-000000000004/index.html', None),
        ('link in the shared v1/', A + 'v1/evil.js', None),
        ('folder itself', A + 'sub%20dir', None),
        ('empty path', A, None),
        ('backup plugin as a host', 'rdplugin://cccc0003-0000-4000-8000-000000000003/index.html', None),
        ('v1 as a host', 'rdplugin://v1/plugins.js', None),
        ('not installed', 'rdplugin://eeee0005-0000-4000-8000-000000000005/index.html', None),
        ('host that is not a GUID', 'rdplugin://aaaa0001-0000-4000-8000-000000000001.evil/index.html', None),
        ('other scheme', 'file:///etc/hosts', None),
        ('escaped NUL', A + 'index.html%00.png', None),
    ]
    if header is None:
        check('plugin_scheme.h exists (rdplugin:// file mapping)', False)
        return
    with open(os.path.join(work, 'plugin_scheme.h'), 'w', encoding='utf-8') as f:
        f.write(header)
    fa = sdk('file_access.h')
    with open(os.path.join(work, 'file_access.h'), 'w', encoding='utf-8') as f:
        f.write(fa)
    stdin = root + '\n' + '\n'.join(names) + '\n--\n' + '\n'.join(u for _, u, _ in cases) + '\n'
    out, err = compile_run(work, 'scheme', SCHEME_DRIVER, stdin)
    if out is None:
        check('plugin_scheme.h compiles', False, err[:400])
        return
    rroot = os.path.realpath(root)
    for (desc, url, want), got in zip(cases, out.split('\n')):
        want_path = '-' if want is None else os.path.join(rroot, want)
        check('scheme: %-48s -> %s' % (desc, 'served' if want else 'refused'), got == want_path, got if got != want_path else '')

    gate = r'''
#include "plugin_scheme.h"
#include <iostream>
int main(int argc, char** argv)
{
	std::wstring root = NSFileAccess::Utf8ToWide(argv[1]);
	const char* paths[] = { "/{AAAA0001-0000-4000-8000-000000000001}/index.html", "/v1/plugins.js", "/../sdkjs-plugins-other/x.html", NULL };
	for (const char** p = paths; *p; ++p)
		std::cout << NSPluginScheme::IsInUserPluginsDir(root + NSFileAccess::Utf8ToWide(*p), root) << " ";
	int types[] = { 0, 1, 2, 3, 4, 7, 9, 10, 13, 15, 19, 20 };
	for (int t : types) std::cout << NSPluginScheme::IsPageResourceType(t);
	std::cout << " " << NSPluginScheme::GetMimeType(L"/a/b.wasm") << " " << NSPluginScheme::GetMimeType(L"/a/b.JS") << " " << NSPluginScheme::GetMimeType(L"/a.b/c") << "\n";
	return 0;
}
'''
    out, err = compile_run(work, 'gate', gate)
    if out is None:
        check('file:// gate helpers compile', False, err[:300])
        return
    out2 = subprocess.run([os.path.join(work, 'gate'), root], capture_output=True, text=True).stdout.strip()
    check('file:// gate: user plugin pages are in the user plugins folder, a sibling folder is not', out2.startswith('1 1 0 '), out2)
    check('file:// gate: frames, objects, workers and navigation preloads count as pages; css/js/img/xhr do not',
          ' 110001110111 ' in (' ' + out2.split(' ', 3)[3] + ' '), out2)
    check('MIME: wasm is application/wasm (tesseract), .JS is javascript, no extension is octet-stream',
          out2.endswith('application/wasm text/javascript application/octet-stream'), out2)


# ---------------------------------------------------------------- 2. bridge tiers
BRIDGE_DRIVER = r'''
#include "bridge_access.h"
#include <iostream>
#include <cstdio>
int main()
{
	NSBridgeAccess::CPolicy p;
	p.AddDir("/Applications/Ration Docs.app/Contents/Resources");
	@@EXCLUDE@@
	char line[8192];
	while (fgets(line, sizeof(line), stdin))
	{
		std::vector<NSBridgeAccess::CFrame> chain; std::string cur; std::vector<std::string> f;
		for (char* c = line; *c && *c != '\n'; ++c) { if (*c == '\t') { f.push_back(cur); cur.clear(); } else cur += *c; }
		f.push_back(cur);
		for (size_t i = 0; i + 1 < f.size(); i += 2)
		{
			NSBridgeAccess::CFrame fr(f[i], f[i + 1]);
			@@MAIN@@
			chain.push_back(fr);
		}
		std::cout << (int)p.Check(chain) << "\n";
	}
	return 0;
}
'''

APPU = 'file:///Applications/Ration%20Docs.app/Contents/Resources'
USERPU = 'file:///Users/u/Library/Application%20Support/com.stackchase.rationdocs/data/sdkjs-plugins'
API = (APPU + '/editors/web-apps/apps/api/documents/index.html', '')
EDITOR = (APPU + '/editors/web-apps/apps/documenteditor/main/index.html', 'frameEditor')
START = (APPU + '/login/index.html', '')
RD = ('rdplugin://440ebf13-9b19-4bd8-8621-05200e58140b/index.html?lang=en', 'iframe_asc.{440EBF13}')


def bridge_tests(work, header):
    if header is None:
        check('bridge_access.h present', False)
        return
    with open(os.path.join(work, 'bridge_access.h'), 'w', encoding='utf-8') as f:
        f.write(header)
    has_exclude = 'void AddExcludedDir(' in header
    has_main = 'bool Main;' in header
    drv = BRIDGE_DRIVER.replace('@@EXCLUDE@@', 'p.AddExcludedDir("/Users/u/Library/Application Support/com.stackchase.rationdocs/data/sdkjs-plugins");' if has_exclude else
                                'p.AddDir("/Users/u/Library/Application Support/com.stackchase.rationdocs/data/sdkjs-plugins");') \
        .replace('@@MAIN@@', 'if (fr.Name.size() > 5 && fr.Name.substr(fr.Name.size() - 5) == "|main") { fr.Name = fr.Name.substr(0, fr.Name.size() - 5); fr.Main = true; }' if has_main else
                 'if (fr.Name.size() > 5 && fr.Name.substr(fr.Name.size() - 5) == "|main") fr.Name = fr.Name.substr(0, fr.Name.size() - 5);')
    cases = [
        ('rdplugin OCR in the editor', [RD, EDITOR, API], 2),
        ('rdplugin external plugin on the start page', [RD, START], 2),
        ('rdplugin as its own top-level page', [(RD[0], RD[1] + '|main')], 2),
        ('about:blank made by an rdplugin page', [('about:blank', ''), RD, EDITOR, API], 2),
        ('blob:rdplugin in an editor frame (plugin navigated it there)', [('blob:rdplugin://440ebf13-9b19-4bd8-8621-05200e58140b/1', 'x'), EDITOR, API], 2),
        ('rdplugin framed by a remote page', [RD, ('https://evil.example.net/x', ''), EDITOR, API], 0),
        ('rdplugin whose chain is cut (parent in another process)', [RD], 0),
        ('rdplugin with a non-GUID host', [('rdplugin://evil.example.net/x', ''), EDITOR, API], 0),
        ('user plugin as file:// (old way)', [(USERPU + '/%7B440EBF13-9B19-4BD8-8621-05200E58140B%7D/index.html', ''), EDITOR, API], 0),
        ('user plugin as onlyoffice://plugin/ (old onlyofficeScheme way)', [('onlyoffice://plugin/' + USERPU + '/%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD007%7D/index.html', ''), EDITOR, API], 0),
        ('bundled plugin as onlyoffice://plugin/ (AI) keeps the bridge', [('onlyoffice://plugin/' + APPU + '/editors/sdkjs-plugins/%7B9DC93CDB-B576-4F0C-B55E-FCC9C48DD007%7D/index.html', ''), EDITOR, API], 1),
        ('editor keeps the bridge', [EDITOR, API], 1),
    ]
    stdin = ''.join('\t'.join(x for fr in ch for x in fr) + '\n' for _, ch, _ in cases)
    out, err = compile_run(work, 'bridge', drv, stdin)
    if out is None:
        check('bridge_access.h driver compiles', False, err[:300])
        return
    names = {0: 'none', 1: 'full', 2: 'plugin tier'}
    for (desc, _, want), got in zip(cases, out.split()):
        got = int(got)
        check('bridge: %-62s %s' % (desc, names[want]), got == want, 'got ' + names.get(got, str(got)))

    api = r'''
#include "bridge_access.h"
#include <iostream>
int main()
{
	using P = NSBridgeAccess::CPolicy;
	const char* all[] = { "_OpenFilenameDialog", "GetImageBase64", "GetSupportedScaleValues", "generateNew", "getGenerationInfo",
		"LocalFileSaveChanges", "RemoveFile", "ResaveFile", "_createProcess", "execCommand", "PluginInstall", "_DownloadFiles",
		"_convertFile", "GetOpenedFile", "LoadJS", "LocalFileGetImageUrl", "_SaveFilenameDialog", "callToolFunction", "_callToolFunction",
		"Copy", "Paste", "CallInFrame", "_CallInAllWindows", "sendSimpleRequest", NULL };
	for (const char** p = all; *p; ++p) std::cout << P::IsPluginTierMethod(*p);
	std::cout << " " << P::IsPluginGenerateType("docx") << P::IsPluginGenerateType("pdf") << P::IsPluginGenerateType("docx/../x")
			  << P::IsPluginGenerateType("") << P::IsPluginGenerateType("DOCX");
	std::cout << " " << (int)P::ForContextOrigin(NSBridgeAccess::Full, "rdplugin://abc") << (int)P::ForContextOrigin(NSBridgeAccess::Full, "file://")
			  << (int)P::ForContextOrigin(NSBridgeAccess::None, "rdplugin://abc");
	std::vector<NSBridgeAccess::CFrame> ch; ch.push_back(NSBridgeAccess::CFrame("about:blank", "")); ch.push_back(NSBridgeAccess::CFrame("rdplugin://abc-1/x.html", ""));
	std::cout << " " << P::GetRdPluginHost(ch) << "\n";
	return 0;
}
'''
    if 'IsPluginTierMethod' not in header:
        check('bridge: a Plugin tier allowlist exists (IsPluginTierMethod)', False)
        return
    out, err = compile_run(work, 'api', api)
    if out is None:
        check('bridge allowlist driver compiles', False, err[:300])
        return
    out = out.strip()
    check('allowlist: exactly the five methods user plugins use; no path writers, processes, conversions, frames',
          out.startswith('11111' + '0' * 19 + ' '), out)
    check('generateNew type from a plugin: a word only', ' 11000 ' in out, out)
    check('a context with a plugin origin under an editor parent is held to the Plugin tier', ' 210 ' in out, out)
    check('picked files are keyed by the plugin (about:blank child counts as its plugin)', out.endswith(' abc-1'), out)


# ---------------------------------------------------------------- 3. sdkjs
NODE_DRIVER = r'''
const vm = require('vm');
const src = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const sent = [];
const ctx = {
  console, JSON, setTimeout, AscCommon: {},
  window: {}
};
ctx.window = ctx;
ctx.Asc = { editor: { asc_registerCallback() {}, sendEvent() {} } };
ctx.window["Asc"] = ctx.Asc;
ctx.AscDesktopEditor = {
  GetInstallPlugins() {
    return JSON.stringify([
      { url: 'file:///Applications/Ration Docs.app/Contents/Resources/editors/sdkjs-plugins/', pluginsData: [
        { guid: 'asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}', onlyofficeScheme: true, variations: [{ initDataType: 'none' }] },
        { guid: 'asc.{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}', variations: [{ initDataType: 'none' }] } ] },
      { url: 'file:///Users/u/Library/Application Support/x/data/sdkjs-plugins/', pluginsData: [
        { guid: 'asc.{440EBF13-9B19-4BD8-8621-05200E58140B}', variations: [{ initDataType: 'none' }] },
        { guid: 'asc.{F30BDD79-23A0-4B05-8DE3-2AB77D03A1B4}', onlyofficeScheme: true, variations: [{ initDataType: 'none' }] },
        { guid: 'asc.{BAD_GUID.1}', variations: [{ initDataType: 'none' }] } ] }
    ]);
  }
};
ctx.g_asc_plugins = { sendPluginsInit(p) { sent.push(p); } };
vm.createContext(ctx);
try { vm.runInContext(src.helper || '', ctx); } catch (e) { console.log('HELPER-ERROR ' + e.message); }
try { vm.runInContext(src.update, ctx); ctx.UpdateInstallPlugins(); } catch (e) { console.log('UPDATE-ERROR ' + e.message); }
const p = sent[0] ? sent[0].pluginsData : [];
for (const x of p) console.log('BASE ' + x.guid + ' ' + x.baseUrl);
// checkOrigin
const co = vm.runInContext('(' + src.checkOrigin + ')', ctx);
const mgr = { getPluginByGuid(g) { return p.find(function (x) { return x.guid === g; }); } };
ctx.origin = 'file://';
function ev(o) { return { origin: o }; }
console.log('ORIGIN own ' + co.call(mgr, 'asc.{440EBF13-9B19-4BD8-8621-05200E58140B}', ev('rdplugin://440ebf13-9b19-4bd8-8621-05200e58140b')));
console.log('ORIGIN other ' + co.call(mgr, 'asc.{440EBF13-9B19-4BD8-8621-05200E58140B}', ev('rdplugin://f30bdd79-23a0-4b05-8de3-2ab77d03a1b4')));
console.log('ORIGIN system-from-plugin ' + co.call(mgr, 'asc.{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}', ev('rdplugin://440ebf13-9b19-4bd8-8621-05200e58140b')));
'''


def sdkjs_tests(work):
    common = js('common/Local/common.js')
    ec = js('common/editorscommon.js')
    pl = js('common/plugins.js')
    if not (common and ec and pl):
        check('sdkjs sources readable', False)
        return
    update = block(common, 'window["UpdateInstallPlugins"] = function()')
    helper = block(ec, 'AscCommon["getDesktopUserPluginBaseUrl"] = function(')
    co = block(pl, 'checkOrigin : function(guid, event)')
    co = co[co.find('function'):] if co else None
    if not update or not co:
        check('sdkjs functions found', False)
        return
    import json
    srcf = os.path.join(work, 'src.json')
    with open(srcf, 'w') as f:
        json.dump({'update': update, 'helper': helper or '', 'checkOrigin': co}, f)
    drv = os.path.join(work, 'drv.js')
    with open(drv, 'w') as f:
        f.write(NODE_DRIVER)
    out = subprocess.run(['node', drv, srcf], capture_output=True, text=True).stdout
    base = dict(re.findall(r'^BASE (\S+) (.*)$', out, re.M))
    check('sdkjs: user plugin (OCR) baseUrl is rdplugin://<guid>/',
          base.get('asc.{440EBF13-9B19-4BD8-8621-05200E58140B}') == 'rdplugin://440ebf13-9b19-4bd8-8621-05200e58140b/', base.get('asc.{440EBF13-9B19-4BD8-8621-05200E58140B}', out[:200]))
    check('sdkjs: user plugin with onlyofficeScheme also rdplugin (not onlyoffice://plugin/)',
          base.get('asc.{F30BDD79-23A0-4B05-8DE3-2AB77D03A1B4}') == 'rdplugin://f30bdd79-23a0-4b05-8de3-2ab77d03a1b4/', base.get('asc.{F30BDD79-23A0-4B05-8DE3-2AB77D03A1B4}', ''))
    check('sdkjs: bundled onlyofficeScheme plugin unchanged (onlyoffice://plugin/file://...)',
          base.get('asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}', '').startswith('onlyoffice://plugin/file:///Applications/Ration%20Docs.app/'), base.get('asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}', ''))
    check('sdkjs: bundled plugin manager unchanged (file://)',
          base.get('asc.{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}', '').startswith('file:///Applications/Ration%20Docs.app/'), base.get('asc.{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}', ''))
    check('sdkjs: a GUID that cannot be a host keeps file:// (the app refuses to load it)',
          base.get('asc.{BAD_GUID.1}', '').startswith('file:///Users/'), base.get('asc.{BAD_GUID.1}', ''))
    check('plugins.js checkOrigin: a plugin\'s messages from its rdplugin origin are accepted', 'ORIGIN own true' in out)
    check('plugins.js checkOrigin: another plugin\'s origin is refused', 'ORIGIN other false' in out)
    check('plugins.js checkOrigin: a user plugin cannot speak as a system plugin', 'ORIGIN system-from-plugin false' in out)
    usp = block(ec, 'window["UpdateSystemPlugins"] = function()') or ''
    check('sdkjs: UpdateSystemPlugins gives user (k == 1) encryption plugins rdplugin too', 'getDesktopUserPluginBaseUrl' in usp)


# ---------------------------------------------------------------- 4. wiring
def wiring_tests():
    sch = sdk('cefwrapper/client_scheme_wrapper.cpp') or ''
    view = sdk('cefview.cpp') or ''
    rw = sdk('cefwrapper/client_renderer_wrapper.cpp') or ''
    app = sdk('applicationmanager.cpp') or ''
    reg = block(sch, 'void RegisterCustomSchemes(CefRawPtr<CefSchemeRegistrar> registrar') or ''
    check('scheme rdplugin registered standard + secure + CORS + fetch', 'AddCustomScheme(NSPluginScheme::Scheme(), CEF_SCHEME_OPTION_STANDARD | CEF_SCHEME_OPTION_SECURE | CEF_SCHEME_OPTION_CORS_ENABLED | CEF_SCHEME_OPTION_FETCH_ENABLED)' in reg)
    check('scheme rdplugin has a handler factory', 'CefRegisterSchemeHandlerFactory(NSPluginScheme::Scheme()' in sch and 'return new ClientSchemeHandlerRD(' in sch)
    rd = block(sch, 'class ClientSchemeHandlerRD') or ''
    check('rdplugin handler serves NSPluginScheme::GetFile only, 404 otherwise', 'NSPluginScheme::GetFile(' in rd and 'status_(404)' in rd)
    oo = block(sch, 'class ClientSchemeHandlerOO') or ''
    check('onlyoffice://plugin/ handler refuses the user plugins folder', 'IsInUserPlugins(m_pManager' in oo)
    pc = block(sch, 'posFind = url.find("ascdesktop://plugin_content/");') or ''
    check('ascdesktop://plugin_content/ refuses the user plugins folder', 'IsInUserPlugins(m_pManager' in pc)
    fac = block(sch, 'virtual CefRefPtr<CefResourceHandler> Create(') or ''
    check('factory refuses ascdesktop:// and onlyoffice:// requests from user plugins (any-path reads of a local editor)',
          'IsUserPluginRequest(frame, request)' in fac and 'return nullptr;' in fac)
    grh = block(view, 'virtual CefRefPtr<CefResourceHandler> GetResourceHandler(') or ''
    check('GetResourceHandler refuses file:// pages/workers from the user plugins folder',
          'NSPluginScheme::IsPageResourceType' in grh and 'NSPluginScheme::IsInUserPluginsDir' in grh and 'CAscFileAccessDeniedHandler' in grh)
    ole = block(view, 'virtual void OnLoadEnd(') or ''
    ejs = view[view.find('case ASC_MENU_EVENT_TYPE_EXECUTE_JS_CODE:'):][:1200]
    check('encryption password not sent into user plugin frames (OnLoadEnd and the all-frames broadcast)',
          'IsUserPluginFrame(frame)' in ole and 'bIsCryptoSupport = false' in ole and '!IsUserPluginFrame(frame)' in ejs)
    scd = block(sdk('applicationmanager_p.h') or '', 'void SendCryptoData(') or ''
    check('encryption password snippet returns at once in an rdplugin: document (code sent to a frame lands in its next document)',
          'window.location.protocol === \\"rdplugin:\\") return;' in scd)
    check('external user plugins (start page) are rdplugin://', 'if (iterExt->isUser)' in ole and 'NSPluginScheme::Scheme()' in ole)
    occ = block(rw, 'virtual void OnContextCreated(') or ''
    check('OnContextCreated: Plugin tier builds the allowlist bridge (IsPluginTierMethod), no InitJSContext',
          'NSBridgeAccess::Plugin == eAccess' in occ and 'IsPluginTierMethod(*cur)' in occ and 'sUserPluginInit' in occ)
    check('OnContextCreated: context origin checked (ForContextOrigin)', 'ForContextOrigin(eAccess' in occ)
    # the bridge handler's Execute: the refusal comes right after the plugin-scheme one, before any name
    pos = rw.find('if (m_bPluginFrame && NSBridgeAccess::CPolicy::IsPluginRestrictedMethod(name))')
    first = rw.find('if (name == "Copy")', pos)
    check('Execute refuses non-allowlisted names for user plugin bridges',
          pos >= 0 and 0 <= rw.find('if (m_bUserPluginFrame && !NSBridgeAccess::CPolicy::IsPluginTierMethod(name))', pos) < first)
    gib = block(rw, 'else if (name == "GetImageBase64")') or ''
    check('GetImageBase64 for a user plugin: only files picked in its own dialog', 'IsUserPluginPickedFile(' in gib)
    cba = block(rw, 'NSBridgeAccess::Access CheckBridgeAccess(') or ''
    check('CheckBridgeAccess: the user plugins folder is excluded, not added', 'AddExcludedDir(default_params.GetValue("user_plugins_path"))' in cba and 'AddDir(default_params.GetValue("user_plugins_path"))' not in cba)
    check('saved settings: migration list written once, passed to renderers, done before plugin scripts',
          'rdplugin_migrate=' in app and 'MigrateUserPluginStorage(context->GetFrame(), context)' in occ)


def main():
    work = tempfile.mkdtemp(prefix='rd1664po-')
    try:
        scheme_tests(work, sdk('plugin_scheme.h'))
        bridge_tests(work, sdk('bridge_access.h'))
        sdkjs_tests(work)
        wiring_tests()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('\nFAIL: %d problem(s)%s' % (len(failures), ' [BASELINE %s / %s]' % (BASE_REF, SDKJS_BASE_REF) if BASELINE else ''))
        sys.exit(1)
    print('\nPASS: user plugins are rdplugin://<guid>/ with an allowlist bridge; the scheme serves only their own files')


if __name__ == '__main__':
    main()
