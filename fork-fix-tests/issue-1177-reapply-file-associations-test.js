/*
 * #1177 - "Add an option to re-apply file associations right from ONLYOFFICE
 * client" (Windows). Once another program had taken over .docx/.xlsx/..., the
 * only ways back were Windows' per-type Default apps page or reinstalling; the
 * app's own "make me the default" prompt comes at most once a day, only for the
 * type just opened, and never again after "Do not show this message again".
 *
 * Fix (desktop-apps):
 *  - start page Settings has, on Windows (not the portable package), a "File
 *    types" field with a button "Make Ration Docs the default app for all
 *    supported files" (panelsettings.js, shown when settings:init carries
 *    fileassoc: true - win-linux prop/cmainwindowimpl.cpp); it sends
 *    "settings:fileassoc";
 *  - cascapplicationmanagerwrapper.cpp routes "settings:fileassoc" to
 *    Association::associateAll() (platform_win/association.cpp), which hands every
 *    type the installer registered (Capabilities\FileAssociations, m_extMap) to
 *    the existing associate() - the same path as a Yes to the startup prompt
 *    (the projicons stub's --assoc), regardless of the prompt's opt-out.
 *
 * This test
 *  1. loads the real jQuery, events.js, base.js, utils.js, locale.js and the
 *     whole of panelsettings.js into jsdom, sends settings:init as the Windows
 *     app does and clicks the button: "settings:fileassoc" must reach the app
 *     (baseline: no such button -> FAILS); with no fileassoc (macOS, Linux,
 *     portable) the field stays hidden;
 *  2. compiles, with clang++/g++ and _WIN32 defined, the real "settings" branch
 *     of CAscApplicationManagerWrapper's command dispatch and the real
 *     Association::associateAll() against stubs, sends it "settings:fileassoc",
 *     "settings:apply" and "settings:get", and checks that only the first
 *     associates - all registered types - and the others still reach
 *     applySettings / sendSettings.
 *
 * NOT claimed (no Windows build here): that associate()/the --assoc stub then
 * wins over another default app on a given Windows version (unchanged code,
 * used by the startup prompt); the look of the button.
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_NODE_MODULES  where jsdom lives (default /Users/osindero/dev/active/node_modules)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || 'ae489fe2a^';
const NODE_MODULES = process.env.RD_NODE_MODULES || '/Users/osindero/dev/active/node_modules';
const { JSDOM } = require(path.join(NODE_MODULES, 'jsdom'));

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', APPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(APPS, rel), 'utf8');
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

/* ---- 1. start page ---- */
function startPage(settings) {
	const L = 'common/loginpage/';
	const dom = new JSDOM(`<!doctype html><body>
		<div class="main-column tool-menu"></div><div class="main-column col-center"></div><div id="placeholder"></div>
		</body>`, { runScripts: 'dangerously', url: 'http://localhost/loginpage/index.html' });
	const w = dom.window;
	w.addEventListener('error', e => { w.__err = e.error; });
	const run = (code) => {
		const s = w.document.createElement('script');
		s.textContent = code;
		w.document.body.appendChild(s);
		if (w.__err) throw w.__err;
	};
	run(fs.readFileSync(path.join(APPS, L + 'vendor/jquery/jquery.js'), 'utf8'));
	run('jQuery.fn.selectpicker = function () { return this; };');
	run(src(L + 'src/events.js'));
	run(src(L + 'src/base.js'));
	run(src(L + 'src/utils.js'));
	run(src(L + 'src/locale.js'));
	run(`
		utils.Lang = l10n.en; window.RendererProcessVariable = { theme: { id: 'theme-light', type: 'light' } }; var nativevars = window.RendererProcessVariable;
		var _native = [], _sent = [];
		window.sdk = { on: function (ev, fn) { ev === 'on_native_message' && _native.push(fn); },
			command: function (c, p) { _sent.push(c); }, GetLocalFeatures: function () { return false; } };
	`);
	run(src(L + 'src/panelsettings.js'));
	run('(new ControllerSettings).init();');
	w.eval('_native').forEach(fn => fn('settings:init', JSON.stringify(settings)));
	return w;
}

let w = startPage({ keeprecents: true });
assert.strictEqual(w.$('#sett-box-file-assoc').css('display') || 'none', 'none', 'the file types field shows without fileassoc (macOS/Linux/portable)');
console.log('settings:init without fileassoc: field hidden');

w = startPage({ keeprecents: true, fileassoc: true });
const $box = w.$('#sett-box-file-assoc');
const $btn = $box.find('button');
console.log(`settings:init with fileassoc: field ${$box.length && $box.css('display') !== 'none' ? 'shown' : 'missing'}, button ${JSON.stringify($btn.text().trim())}`);
assert.ok($box.length && $box.css('display') !== 'none' && $btn.length,
	'Settings has no way to make the app the default for its file types again');
const before = w.eval('_sent.length');
$btn.trigger('click');
const sent = w.eval('_sent').slice(before);
console.log('clicking it sends', JSON.stringify(sent));
assert.ok(sent.includes('settings:fileassoc'), 'the button does not ask the app to take the file types back');

/* ---- 2. native: command dispatch + associateAll ---- */
const wrapper = src('win-linux/src/cascapplicationmanagerwrapper.cpp');
const at = wrapper.indexOf('if ( cmd.compare(0, 8, L"settings") == 0 ) {');
assert.ok(at !== -1, 'settings dispatch not found - test is stale');
const dispatch = block(wrapper, at);
const assoc = src('win-linux/src/platform_win/association.cpp');
const aat = assoc.indexOf('void Association::associateAll()');
const associateAll = aat === -1 ? '' : block(assoc, aat);

const cpp = `
#include <string>
#include <vector>
#include <map>
#include <cstdio>
#define _WIN32 1
using std::wstring;
struct AssociationPrivate {
	std::map<std::wstring, std::wstring> m_extMap { {L".docx", L"RationDocs.Docx"}, {L".xlsx", L"RationDocs.Xlsx"}, {L".pdf", L"RationDocs.Pdf"} };
	std::vector<std::wstring> associated;
	void associate(const std::vector<std::wstring> &e) { associated = e; }
};
struct Association {
	AssociationPrivate *pimpl = new AssociationPrivate;
	static Association& instance() { static Association a; return a; }
	void associateAll();
};
${associateAll || 'void Association::associateAll() {}'}
struct Data { std::wstring p; std::wstring get_Param() { return p; } };
static std::vector<std::string> calls;
static void applySettings(const std::wstring&) { calls.push_back("applySettings"); }
static void sendSettings(const std::wstring&) { calls.push_back("sendSettings"); }
static void checkSettings(const std::wstring&) { calls.push_back("checkSettings"); }
// what the dispatch may also touch once other settings land (#2436 refreshes the tab bar)
struct CTabBarStub { void setTypeColorsVisible(bool) {} };
struct CTabWidgetStub { CTabBarStub b; CTabBarStub *tabBar() { return &b; } };
struct CMainWindow { CTabWidgetStub t; CTabWidgetStub *tabWidget() { return &t; } };
static CMainWindow *mainWindow() { return nullptr; }
static std::wstring userSettings(const std::wstring &) { return L""; }
static bool route(const std::wstring &cmd) {
	Data d; Data *pData = &d;
	${dispatch}
	return false;
}
int main() {
	const wchar_t *cmds[] = { L"settings:fileassoc", L"settings:apply", L"settings:get" };
	for (auto c : cmds) {
		calls.clear();
		Association::instance().pimpl->associated.clear();
		route(c);
		printf("%ls ->", c);
		for (auto &x : calls) printf(" %s", x.c_str());
		printf(" associated=%zu\\n", Association::instance().pimpl->associated.size());
	}
}
`;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1177-'));
let lines;
try {
	fs.writeFileSync(path.join(tmp, 'drv.cpp'), cpp);
	const cxx = process.env.CXX || (process.platform === 'darwin' ? 'clang++' : 'g++');
	execFileSync(cxx, ['-std=c++14', '-w', '-o', path.join(tmp, 'drv'), path.join(tmp, 'drv.cpp')], { stdio: 'inherit' });
	lines = execFileSync(path.join(tmp, 'drv'), { encoding: 'utf8' }).trim().split('\n');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
lines.forEach(l => console.log('native ' + l));
assert.strictEqual(lines[1], 'settings:apply -> applySettings associated=0', 'settings:apply no longer reaches applySettings');
assert.strictEqual(lines[2], 'settings:get -> sendSettings associated=0', 'settings:get no longer reaches sendSettings');
assert.strictEqual(lines[0], 'settings:fileassoc -> associated=3', '"settings:fileassoc" does not associate every registered file type');

console.log('PASS #1177: Settings can make the app the default for all its file types again (Windows)');
