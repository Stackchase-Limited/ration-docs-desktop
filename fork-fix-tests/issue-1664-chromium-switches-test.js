/*
 * #1664 (security round) - Chromium hardening switches in desktop-sdk
 * ChromiumBasedEditors/lib/src/cefwrapper/client_app.h,
 * CAscClientAppBrowser::OnBeforeCommandLineProcessing.
 *
 * Bug: the browser process passes --disable-site-isolation-trials, so every
 * cross-site frame shares the renderer process of the file:// editor that
 * embeds it. The YouTube plugin loads
 * https://onlyoffice.github.io/sdkjs-plugins/content/youtube/desktop-player.html,
 * which nests the https://www.youtube.com embed (and its ads). Both ran inside
 * the editor's process, with the AscDesktopEditor bridge - and in that process
 * the bridge's local-file resolver allows any path, because the process's first
 * frame was file:// (CLocalFilesResolver::m_bIsLocalUrl). Measured in the macOS
 * test app: a remote frame in the editor's process got the text of a local
 * .docx back from AscDesktopEditor.convertFileExternal().
 *
 * Why the switch itself stays: every browser->renderer reply of the bridge is
 * sent to the MAIN frame's process (SEND_MESSAGE_TO_RENDERER_PROCESS) and
 * looked up by frame id there. With --site-per-process the onlyoffice://plugin
 * frames (AI agent on the start page, AI plugin in the editors) become
 * out-of-process frames and their callbacks never arrive (measured:
 * convertFileExternal times out; it answers without the flag). Upstream added
 * the switch for the same reason ("Fix private rooms bug", 6f194451).
 *
 * Fix: keep the switch and add --isolate-origins for the three remote origins
 * the bundled plugins embed. Chromium honours --isolate-origins alongside
 * --disable-site-isolation-trials (verified via CDP Target.getTargets: both
 * player frames become "iframe" targets in their own processes).
 *
 * --allow-file-access-from-files is required (without it, measured: 96 blocked
 * locale/*.json, *.template and svg.json XHRs, exceptions, and the api page is
 * refused access to frameEditor) and must stay.
 *
 * This test extracts the real OnBeforeCommandLineProcessing, compiles it
 * (clang++/g++) against a stub CefCommandLine that records switches, runs it
 * for the browser process and checks:
 *   - --isolate-origins lists the three origins          (baseline: FAILS)
 *   - a user-supplied --isolate-origins is not overridden
 *   - --disable-site-isolation-trials and --allow-file-access-from-files are
 *     still passed (removing them breaks the AI agent / the editors, see above)
 *
 * NOT claimed: that a renderer exploit is contained - the renderer sandbox is
 * still off (no_sandbox), so an isolated process is not a security boundary
 * against code execution; this only keeps the editor's memory and the bridge's
 * file permission out of those frames' process. Remote frames from other
 * origins (e.g. a marketplace plugin's iframe) still share the editor process.
 * Windows/Linux not run (the switch code is shared).
 *
 * Env: RD_REPO   desktop-sdk checkout (default ../desktop-sdk)
 *      BASELINE=1 reads client_app.h from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const SDK = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-sdk'));
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || 'dfe2625c^';
const REL = 'ChromiumBasedEditors/lib/src/cefwrapper/client_app.h';

const capp = process.env.BASELINE
	? execFileSync('git', ['-C', SDK, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
	: fs.readFileSync(path.join(SDK, REL), 'utf8');

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const cls = capp.indexOf('class CAscClientAppBrowser');
const at = capp.indexOf('virtual void OnBeforeCommandLineProcessing', cls);
assert.ok(cls !== -1 && at !== -1, 'CAscClientAppBrowser::OnBeforeCommandLineProcessing not found - test is stale');
const method = block(capp, at).replace(/^virtual\s+/, '').replace(/\)\s*OVERRIDE/, ')');

// Same build defines as the macOS (CEF 109) library.
const cpp = `
#include <string>
#include <vector>
#include <cstdio>
#include <cstring>
#define _MAC
#define CEF_VERSION_ABOVE_86
#define CEF_VERSION_ABOVE_102
#define CHROME_VERSION_MAJOR 109
struct CefString : std::string { CefString(const char* s) : std::string(s) {} CefString(const std::string& s) : std::string(s) {} };
struct CefCommandLine {
	std::vector<std::string> sw;
	std::vector<std::string> given;
	void AppendSwitch(const CefString& n) { sw.push_back(n); }
	void AppendSwitchWithValue(const CefString& n, const CefString& v) { sw.push_back(n + "=" + v); }
	bool HasSwitch(const CefString& n) { for (auto& g : given) if (g == n) return true; return false; }
};
template <class T> struct CefRefPtr { T* p; CefRefPtr(T* t) : p(t) {} T* operator->() { return p; } };
struct Manager { bool GetDebugInfoSupport() { return false; } };
struct CAppSettings { void Process(CefRefPtr<CefCommandLine>) {} int IsForceDpiRound() { return 0; } };
struct App : CAppSettings {
	Manager mgr; Manager* m_manager = &mgr;
	${method}
};
int main(int argc, char** argv) {
	CefCommandLine cl; App app;
	for (int i = 1; i < argc; i++) cl.given.push_back(argv[i]);
	app.OnBeforeCommandLineProcessing(CefString(""), CefRefPtr<CefCommandLine>(&cl));
	for (auto& s : cl.sw) printf("%s\\n", s.c_str());
	return 0;
}
`;

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1664-'));
try {
	fs.writeFileSync(path.join(tmp, 'drv.cpp'), cpp);
	const cxx = process.env.CXX || (process.platform === 'darwin' ? 'clang++' : 'g++');
	execFileSync(cxx, ['-std=c++14', '-o', path.join(tmp, 'drv'), path.join(tmp, 'drv.cpp')], { stdio: 'inherit' });
	const run = (...given) => execFileSync(path.join(tmp, 'drv'), given, { encoding: 'utf8' }).trim().split('\n');

	const sw = run();
	console.log('browser process switches:', sw.filter((s) => /site-isolation|isolate-origins|file-access/.test(s)).join(' '));
	assert.ok(sw.includes('--disable-component-update'), 'stub harness broken: an unrelated existing switch is missing');

	assert.ok(sw.includes('--allow-file-access-from-files'),
		'--allow-file-access-from-files is gone: the file:// editors cannot XHR their locale/templates and do not load');
	assert.ok(sw.includes('--disable-site-isolation-trials'),
		'--disable-site-isolation-trials is gone: onlyoffice:// plugin frames (AI agent) become out-of-process and lose bridge callbacks');

	const iso = sw.filter((s) => s.startsWith('--isolate-origins='));
	assert.strictEqual(iso.length, 1, 'no --isolate-origins: the YouTube player frames share the editor\'s renderer process and its local-file permission');
	const origins = iso[0].slice('--isolate-origins='.length).split(',');
	for (const o of ['https://onlyoffice.github.io', 'https://www.youtube.com', 'https://www.youtube-nocookie.com'])
		assert.ok(origins.includes(o), o + ' is not isolated');
	// file:// and onlyoffice:// must never be listed: those frames need the shared process
	assert.ok(!origins.some((o) => /^(file|onlyoffice|ascdesktop):/.test(o)), 'a local scheme was isolated');

	const user = run('isolate-origins');
	assert.ok(!user.some((s) => s.startsWith('--isolate-origins=')), 'a user-supplied --isolate-origins was overridden');
	console.log('user-supplied --isolate-origins: left alone');

	console.log('PASS #1664: YouTube player origins isolated; site-isolation-trials and file-access switches kept');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
