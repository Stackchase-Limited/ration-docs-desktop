/*
 * #1611 - "Pinch to zoom" on Windows/Linux touchpads and touchscreens did nothing.
 *
 * Cause: desktop-sdk ChromiumBasedEditors/lib/src/cefwrapper/client_app.h -
 * OnBeforeCommandLineProcessing of every CEF app class appended "--disable-pinch"
 * unconditionally, so Chromium dropped pinch gestures. A user on the issue showed
 * (by patching the switch out of ascdocumentscore.dll on 9.4) that without it a
 * Precision Touchpad pinch zooms the PDF and the toolbar keeps its size.
 * Fix (opt-in, default unchanged): CAppSettings reads the user setting
 * enable-pinch; "1" (Windows/Linux only) leaves --disable-pinch out, anything else
 * keeps it. The start page has a "Pinch to zoom (touchpad, touchscreen) *" switch
 * (restart), shown only when the app sends pinchzoom in settings:init (win-linux
 * cmainwindowimpl.cpp; macOS does not send it - pinch there is unchanged);
 * settings:apply stores it (cascapplicationmanagerwrapper.cpp).
 *
 * This test
 *  1. extracts the real CAppSettings class from client_app.h by brace matching,
 *     compiles it with stub CefCommandLine/CefRefPtr (clang++/g++), and checks the
 *     switches it appends: no setting -> --disable-pinch; enable-pinch=1 -> none
 *     (baseline: CAppSettings never decides about pinch and the app classes add
 *     --disable-pinch themselves -> FAILS); compiled as _MAC enable-pinch=1 still
 *     gives --disable-pinch;
 *  2. checks no app class in client_app.h still appends --disable-pinch itself;
 *  3. extracts the real _on_btn_apply from panelsettings.js and runs it with the
 *     switch ticked: settings:apply must carry pinchzoom:true and ask for a restart.
 *
 * NOT claimed: what Chromium does without --disable-pinch (needs a GUI check on a
 * Windows Precision Touchpad / Linux touchscreen: pinch inside a document should
 * zoom the document like Ctrl+wheel; check whether a pinch over the toolbar, start
 * page or a dialog zooms the whole UI - if it does, that is the cost of the option).
 * Linux X11 touchpads may not deliver pinch at all in CEF 109. The native
 * settings:init/apply glue is only checked to exist, not executed.
 *
 * Env: RD_SDK   desktop-sdk checkout  (default ../desktop-sdk)
 *      RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      BASELINE=1 reads both from SDK_BASE_REF / BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const SDK = path.resolve(process.env.RD_SDK || path.join(__dirname, '..', 'desktop-sdk'));
const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const SDK_BASE_REF = process.env.SDK_BASE_REF || 'cdeb4bb7^';
const BASE_REF = process.env.BASE_REF || 'a37156b0c^';

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

function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) throw new Error(marker + ' not found');
	return block(text, text.lastIndexOf('\n', at) + 1);
}

/* ---- 1. desktop-sdk: CAppSettings ---- */
const capp = src(SDK, SDK_BASE_REF, 'ChromiumBasedEditors/lib/src/cefwrapper/client_app.h');
const cls = extract(capp, 'class CAppSettings') + ';';

const cpp = `
#include <string>
#include <map>
#include <vector>
#include <cstdio>
struct CefCommandLine {
	std::vector<std::string> sw;
	void AppendSwitch(const std::string& s) { sw.push_back(s); }
	void AppendSwitchWithValue(const std::string& s, const std::string& v) { sw.push_back(s + "=" + v); }
};
template <class T> using CefRefPtr = T*;
${cls}
static void run(const char* name, std::map<std::string, std::string> m) {
	CAppSettings s(m);
	CefCommandLine c;
	s.Process(&c);
	bool pinchOff = false;
	for (auto& x : c.sw) if (x == "--disable-pinch") pinchOff = true;
	printf("%s disable-pinch=%d\\n", name, pinchOff ? 1 : 0);
}
int main() {
	run("default", {});
	run("enable0", {{"enable-pinch", "0"}});
	run("enable1", {{"enable-pinch", "1"}});
	return 0;
}
`;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1611-'));
const out = {};
try {
	fs.writeFileSync(path.join(tmp, 'drv.cpp'), cpp);
	const cxx = process.env.CXX || (process.platform === 'darwin' ? 'clang++' : 'g++');
	for (const plat of ['other', 'mac']) {
		const exe = path.join(tmp, 'drv-' + plat);
		execFileSync(cxx, ['-std=c++14', '-w', ...(plat === 'mac' ? ['-D_MAC'] : ['-D_LINUX']), '-o', exe, path.join(tmp, 'drv.cpp')], { stdio: 'inherit' });
		out[plat] = execFileSync(exe, { encoding: 'utf8' }).trim().split('\n');
		out[plat].forEach((l) => console.log(plat + ' ' + l));
	}
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
assert.deepStrictEqual(out.other.slice(0, 2), ['default disable-pinch=1', 'enable0 disable-pinch=1'],
	'without the option pinch must stay disabled (default unchanged)');
assert.strictEqual(out.other[2], 'enable1 disable-pinch=0', 'enable-pinch=1 does not let pinch through on Windows/Linux');
assert.strictEqual(out.mac[2], 'enable1 disable-pinch=1', 'macOS must keep its current pinch handling');

/* ---- 2. no app class adds the switch on its own any more ---- */
const outsideSettings = capp.replace(cls.slice(0, -1), '');
assert.ok(!/AppendSwitch\("--disable-pinch"\)/.test(outsideSettings),
	'an app class still appends --disable-pinch regardless of the setting');

/* ---- 3. start page: the switch and what Apply sends ---- */
const ps = src(APPS, BASE_REF, 'common/loginpage/src/panelsettings.js');
const applySrc = extract(ps, 'function _on_btn_apply(e)');
const sent = [];
const hidden = { is: () => false, find: () => hidden, val: () => undefined, selectpicker: () => hidden };
const $ = () => hidden;
const sdk = { command: (c, p) => sent.push([c, JSON.parse(p)]), LocalFileRemoveAllRecents: () => {} };
const field = (v) => ({ val: (x) => (x === undefined ? v : field(v)), removeClass: () => {}, addClass: () => {} });
const checkbox = (v) => ({ prop: () => v });
const store = {};
const localStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } };
const appSettings = { pinchzoom: false };
const fixed = { $, sdk, localStorage, $userName: field('Ann'), $chOpenMode: checkbox(false), $optsLang: hidden, appSettings,
	$btnApply: { disable: () => {} }, $panel: {}, _validate_user_name: () => true, _lock_createnew: () => {},
	$chPinchZoom: checkbox(true) };
// every other select/switch is left undefined, as when hidden
const others = [...new Set(applySrc.match(/\$(?:opts|ch)\w+/g))].filter((n) => !(n in fixed));
const names = [...Object.keys(fixed), ...others];
new Function(...names, applySrc + '\nreturn _on_btn_apply;')(...Object.values(fixed))({});
assert.strictEqual(sent.length, 1, 'stub harness broken: settings:apply not sent');
console.log('settings:apply sent', JSON.stringify(sent[0][1]));
assert.ok(/id="sett-pinch-zoom"/.test(ps) && /appSettings\.pinchzoom !== undefined/.test(ps), 'the start page has no pinch-to-zoom switch');
assert.strictEqual(sent[0][1].pinchzoom, true, 'settings:apply does not carry the pinch switch');
assert.strictEqual(sent[0][1].restart, true, 'changing the pinch switch must ask for a restart');

const wrap = src(APPS, BASE_REF, 'win-linux/src/cascapplicationmanagerwrapper.cpp');
const init = src(APPS, BASE_REF, 'win-linux/src/prop/cmainwindowimpl.cpp');
assert.ok(/setUserSettings\(L"enable-pinch"/.test(wrap) && /_json_obj\["pinchzoom"\]/.test(init),
	'Windows/Linux settings glue for enable-pinch missing');

console.log('PASS #1611: "Pinch to zoom" (off by default) leaves --disable-pinch out on Windows/Linux');
