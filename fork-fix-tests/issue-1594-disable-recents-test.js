/*
 * #1594 - "Option to disable recent history": the start page always lists the
 * files opened before and there was no way to turn that off (privacy on a
 * shared machine).
 *
 * Cause: desktop-sdk ChromiumBasedEditors/lib/src/applicationmanager_p.h -
 * Recents_Add puts every opened/saved file at the top of m_arRecents and
 * rewrites recents.xml, Recents_Load reads it back on every start; neither
 * consulted any setting. The start page (desktop-apps common/loginpage/src/
 * panelsettings.js) had no switch for it.
 * Fix: a "Keep a list of recent files" switch in the start page settings,
 * sent as keeprecents in settings:apply and stored by the app as the user
 * setting disable-recents (like useai/disable-ai); Recents_Add records nothing
 * and Recents_Load drops the old list while it is set; switching it off also
 * calls LocalFileRemoveAllRecents so the current list is cleared at once.
 *
 * This test
 *  1. extracts the real Recents_Add and Recents_Load (and Recents_IsDisabled
 *     when present) by brace matching, compiles them into a stub class with
 *     clang++/g++ and checks: with disable-recents=1 an opened file is not
 *     recorded and a recents.xml entry is not loaded; without it both still
 *     work (baseline: the file is recorded -> FAILS);
 *  2. extracts the real _on_btn_apply from panelsettings.js and runs it with
 *     the switch unticked: settings:apply must carry keeprecents:false and the
 *     list must be cleared (baseline: neither -> FAILS); and checks the
 *     settings:init handler shows the switch.
 *
 * NOT claimed: the native settings:apply/settings:init glue (win-linux
 * cascapplicationmanagerwrapper.cpp/cmainwindowimpl.cpp, macOS
 * ASCEventsController.mm/ASCCommonViewController.mm) and Utils::addToRecent are
 * not executed here - they need a GUI check; the look of the switch.
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_SDK   desktop-sdk checkout  (default ../desktop-sdk)
 *      BASELINE=1 reads both from BASE_REF / SDK_BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const SDK = path.resolve(process.env.RD_SDK || path.join(__dirname, '..', 'desktop-sdk'));
const BASE_REF = process.env.BASE_REF || '2d2ba2b25a^';
const SDK_BASE_REF = process.env.SDK_BASE_REF || '7597f17a^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return '';
		throw new Error(marker + ' not found');
	}
	// keep the line's leading text (return type) from the line start
	return block(text, text.lastIndexOf('\n', at) + 1);
}

/* ---- 1. desktop-sdk: Recents_Add / Recents_Load ---- */
const amp = src(SDK, SDK_BASE_REF, 'ChromiumBasedEditors/lib/src/applicationmanager_p.h');
const methods = [
	extract(amp, 'bool Recents_IsDisabled()', true),
	extract(amp, 'void Recents_Load()'),
	extract(amp, 'void Recents_Add(const std::wstring& sPathSrc'),
].join('\n');

const cpp = `
#include <string>
#include <vector>
#include <map>
#include <cstdio>
struct CTemporaryCS { CTemporaryCS(void*) {} };
struct CAscEditorFileInfo {
	int m_nId = 0; std::wstring m_sPath, m_sUrl, m_sExternalCloudId, m_sParentUrl, m_sDate;
	int m_nFileType = 0; bool m_bIsCrypted = false, m_bPin = false;
	void UpdateDate() { m_sDate = L"now"; }
};
namespace XmlUtils {
	struct CXmlNode {
		std::wstring path;
		bool FromXmlFile(const std::wstring&) { return true; }
		std::vector<CXmlNode> GetNodes(const std::wstring&) { CXmlNode n; n.path = L"/old/kept.docx"; return {n}; }
		std::wstring GetAttribute(const std::wstring& a) { return a == L"path" ? path : L""; }
		int ReadAttributeInt(const std::wstring&) { return 65; }
	};
}
struct Settings { std::wstring recover_path = L"/r"; };
struct Main { Settings m_oSettings; };
struct Mgr {
	std::map<std::string, std::string> m_mapSettings;
	std::vector<CAscEditorFileInfo> m_arRecents;
	int m_oCS_LocalFiles = 0; int dumps = 0;
	Main main; Main* m_pMain = &main;
	void Recents_Dump(bool = true, const int& = -1) { dumps++; }
	${methods}
};
int main() {
	for (int off = 0; off < 2; off++) {
		Mgr m;
		if (off) m.m_mapSettings["disable-recents"] = "1";
		m.Recents_Load();
		size_t loaded = m.m_arRecents.size();
		m.Recents_Add(L"/home/u/secret.docx", 65);
		printf("%s loaded=%zu after_open=%zu\\n", off ? "disabled" : "default", loaded, m.m_arRecents.size());
	}
	return 0;
}
`;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1594-'));
let lines;
try {
	fs.writeFileSync(path.join(tmp, 'drv.cpp'), cpp);
	const cxx = process.env.CXX || (process.platform === 'darwin' ? 'clang++' : 'g++');
	execFileSync(cxx, ['-std=c++14', '-w', '-o', path.join(tmp, 'drv'), path.join(tmp, 'drv.cpp')], { stdio: 'inherit' });
	lines = execFileSync(path.join(tmp, 'drv'), { encoding: 'utf8' }).trim().split('\n');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
lines.forEach((l) => console.log('recents ' + l));
assert.strictEqual(lines[0], 'default loaded=1 after_open=2', 'stub harness broken: recents not kept by default');
assert.strictEqual(lines[1], 'disabled loaded=0 after_open=0',
	'with disable-recents=1 the app still loads/records recent files');

/* ---- 2. start page: the switch and what Apply sends ---- */
const ps = src(APPS, BASE_REF, 'common/loginpage/src/panelsettings.js');
const applySrc = extract(ps, 'function _on_btn_apply(e)');
const initSrc = extract(ps, 'function _on_app_message(cmd, param)');

const sent = [];
let cleared = 0;
const hidden = { is: () => false, find: () => hidden, val: () => undefined, selectpicker: () => hidden };
const $ = () => hidden;
const sdk = { command: (c, p) => sent.push([c, JSON.parse(p)]), LocalFileRemoveAllRecents: () => { cleared++; } };
const field = (v) => ({ val: (x) => (x === undefined ? v : field(v)), removeClass: () => {}, addClass: () => {} });
const checkbox = (v) => ({ prop: () => v });
const btn = { disable: () => {} };
const store = {};
const localStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } };
const appSettings = { useai: true, keeprecents: true };

const names = ['$', 'sdk', 'localStorage', '$userName', '$chOpenMode', '$optsLang', '$optsUIScaling', '$optsUITheme',
	'$optsLaunchMode', '$optsAutoupdateMode', '$optsSpellcheckMode', '$chGpu', '$chUseAI', '$chKeepRecents',
	'appSettings', '$btnApply', '$panel', '_validate_user_name', '_lock_createnew'];
// selects/switches added to the page later are not set here (undefined), as when hidden
const extras = [...new Set(applySrc.match(/\$(?:opts|ch)\w+/g))].filter((n) => !names.includes(n));
const apply = new Function(...names, ...extras, applySrc + '\nreturn _on_btn_apply;')(
	$, sdk, localStorage, field('Ann'), checkbox(false), hidden, undefined, undefined,
	undefined, undefined, undefined, undefined, checkbox(true), checkbox(false),
	appSettings, btn, {}, () => true, () => {});
apply({});
assert.strictEqual(sent.length, 1, 'stub harness broken: settings:apply not sent');
console.log('settings:apply sent', JSON.stringify(sent[0][1]), 'list cleared', cleared);
assert.ok(/sett-keep-recents/.test(ps) && /keeprecents/.test(initSrc), 'the start page has no "Keep a list of recent files" switch');
assert.strictEqual(sent[0][1].keeprecents, false, 'settings:apply does not carry the switch to the app');
assert.strictEqual(cleared, 1, 'switching the list off did not clear the files already listed');

// switching it back on does not clear anything
cleared = 0; sent.length = 0;
appSettings.keeprecents = false;
new Function(...names, ...extras, applySrc + '\nreturn _on_btn_apply;')(
	$, sdk, localStorage, field('Ann'), checkbox(false), hidden, undefined, undefined,
	undefined, undefined, undefined, undefined, checkbox(true), checkbox(true),
	appSettings, btn, {}, () => true, () => {})({});
assert.ok(sent[0][1].keeprecents === true && cleared === 0, 'turning the list back on must not clear it');

console.log('PASS #1594: with "Keep a list of recent files" off nothing is recorded and the old list is cleared');
