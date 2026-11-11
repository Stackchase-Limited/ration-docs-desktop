/*
 * #2235 - "Version of editors_helper.exe that doesn't try and connect to 10+
 * remote addresses when anything is opened": the reporter, offline by choice,
 * saw the app's helper process reach out to several hosts on every launch.
 *
 * Measured on our macOS test app (Chromium net-log + CDP Network on every
 * target + lsof/DNS of all its processes) across: start, opening a
 * docx/xlsx/pptx/pdf from disk, 60 s idle, start-page settings, quit. The ONLY
 * remote hosts were templates.onlyoffice.com (the oforms catalogue, 3 pages)
 * and static-oforms.onlyoffice.com (~750 thumbnails), all fetched at start-up
 * by the start page, from the editors_helper network process.
 *
 * Cause: desktop-apps common/loginpage/src/paneltemplates.js. The Templates
 * panel's init calls _loadTemplates(utils.Lang.id) unconditionally, and
 * _loadTemplates defaulted the gallery to https://templates.onlyoffice.com when
 * localStorage.templatesdomain was unset - i.e. always.
 * Fix: no default gallery; with no templatesdomain nothing is fetched. A second
 * change in desktop-sdk client_app.h passes --disable-background-networking,
 * --disable-domain-reliability and --no-pings from the browser process's
 * OnBeforeCommandLineProcessing. Chromium background traffic was NOT observed
 * on CEF 103/macOS, so that part is hardening, not the cure.
 *
 * This test
 *  1. extracts the real _loadTemplates (brace matching) and runs it with a
 *     recording fetch stub: with no templatesdomain it must fetch nothing
 *     (baseline: fetches templates.onlyoffice.com -> FAILS); with one set it
 *     still fetches from that gallery; and checks init really calls it;
 *  2. extracts CAscClientAppBrowser::OnBeforeCommandLineProcessing from
 *     client_app.h, compiles it (clang++/g++) against a stub CefCommandLine
 *     that records switches, runs it for the browser process and checks the
 *     three switches are appended (baseline: missing -> FAILS).
 *
 * NOT claimed: that Chromium honours these switches in CEF 103 (only that we
 * pass them); traffic on Windows/Linux builds (not measured); requests made on
 * a user action (AI provider, online images, plugin store, a connected cloud),
 * which are intended and untouched.
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_SDK   desktop-sdk checkout  (default ../desktop-sdk)
 *      BASELINE=1 reads both from their BASE_REF / SDK_BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const SDK = path.resolve(process.env.RD_SDK || path.join(__dirname, '..', 'desktop-sdk'));
// Pinned to the parents of the fix commits, never HEAD.
const BASE_REF = process.env.BASE_REF || '230580402^';
const SDK_BASE_REF = process.env.SDK_BASE_REF || 'de4b31a4^';

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

function extract(text, marker, after) {
	const at = text.indexOf(marker, after ? text.indexOf(after) : 0);
	assert.ok(at !== -1 && (!after || text.indexOf(after) !== -1), marker + ' not found');
	return block(text, at);
}

/* ---- 1. the start page's template gallery ---- */
const tpl = src(APPS, BASE_REF, 'common/loginpage/src/paneltemplates.js');
const loadSrc = extract(tpl, 'const _loadTemplates = function');

// init runs it on every start, whatever panel is shown
const initSrc = extract(tpl, 'init: function()');
assert.ok(/_loadTemplates\.call\(this, utils\.Lang\.id\)/.test(initSrc), 'init no longer calls _loadTemplates - test is stale');

function runLoad(storage) {
	const fetched = [];
	const fetchStub = (url) => {
		fetched.push(url);
		// one empty page and stop: we only care about what is contacted
		return Promise.resolve({ json: () => ({ data: [], meta: { pagination: { pageCount: 1 } } }) });
	};
	const _loadTemplates = new Function('localStorage', 'fetch', 'window', 'utils', 'isCloudTmplsLoading', '_on_add_cloud_templates',
		loadSrc + '\nreturn _loadTemplates;')(storage, fetchStub, { utils: {} }, { Lang: {} }, false, () => {});
	_loadTemplates.call({}, 'en-EN');
	return fetched;
}

const plain = runLoad({});
console.log('start page, no templatesdomain: fetched', JSON.stringify(plain));
const custom = runLoad({ templatesdomain: 'https://gallery.example' });
console.log('start page, templatesdomain set: fetched', JSON.stringify(custom));
assert.ok(custom.length === 1 && custom[0].startsWith('https://gallery.example/dashboard/api/oforms?'),
	'an explicitly configured gallery must still load');
assert.deepStrictEqual(plain, [], 'launching contacts a remote template gallery nobody asked for');

/* ---- 2. Chromium switches from the browser process ---- */
const capp = src(SDK, SDK_BASE_REF, 'ChromiumBasedEditors/lib/src/cefwrapper/client_app.h');
let method = extract(capp, 'virtual void OnBeforeCommandLineProcessing', 'class CAscClientAppBrowser');
method = method.replace(/^virtual\s+/, '').replace(/\)\s*OVERRIDE/, ')');

const cpp = `
#include <string>
#include <vector>
#include <cstdio>
#define _MAC
#define CEF_VERSION_ABOVE_86
#define CEF_VERSION_ABOVE_102
#define CHROME_VERSION_MAJOR 103
struct CefString : std::string { CefString(const char* s) : std::string(s) {} CefString(const std::string& s) : std::string(s) {} };
struct CefCommandLine {
	std::vector<std::string> sw;
	void AppendSwitch(const CefString& n) { sw.push_back(n); }
	void AppendSwitchWithValue(const CefString& n, const CefString& v) { sw.push_back(n + "=" + v); }
	bool HasSwitch(const CefString&) { return false; }
};
template <class T> struct CefRefPtr { T* p; CefRefPtr(T* t) : p(t) {} T* operator->() { return p; } };
struct Manager { bool GetDebugInfoSupport() { return false; } };
struct CAppSettings { void Process(CefRefPtr<CefCommandLine>) {} int IsForceDpiRound() { return 0; } };
struct App : CAppSettings {
	Manager mgr; Manager* m_manager = &mgr;
	${method}
};
int main() {
	CefCommandLine cl; App app;
	app.OnBeforeCommandLineProcessing(CefString(""), CefRefPtr<CefCommandLine>(&cl));
	for (auto& s : cl.sw) printf("%s\\n", s.c_str());
	return 0;
}
`;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue2235-'));
try {
	fs.writeFileSync(path.join(tmp, 'drv.cpp'), cpp);
	const cxx = process.env.CXX || (process.platform === 'darwin' ? 'clang++' : 'g++');
	execFileSync(cxx, ['-std=c++14', '-o', path.join(tmp, 'drv'), path.join(tmp, 'drv.cpp')], { stdio: 'inherit' });
	const switches = execFileSync(path.join(tmp, 'drv'), { encoding: 'utf8' }).trim().split('\n');
	console.log('browser process switches:', switches.filter((s) => /disable-|no-pings/.test(s)).join(' '));
	assert.ok(switches.includes('--disable-component-update'), 'stub harness broken: existing switch missing');
	for (const s of ['--disable-background-networking', '--disable-domain-reliability', '--no-pings'])
		assert.ok(switches.includes(s), s + ' is not passed: Chromium may run background network services');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}

console.log('PASS #2235: nothing remote is fetched at start-up; background networking switched off');
