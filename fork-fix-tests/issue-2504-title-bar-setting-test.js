/*
 * #2504 "Add settings option to toggle native window title bars" (also #926,
 * #1085, #220): on Linux the window manager's own title bar was only available
 * through the --system-title-bar command-line switch.
 *
 * Cause: the Linux windows already support both title bars - CWindowBase's
 * private part (desktop-apps win-linux/src/windows/cwindowbase.cpp) reads the
 * user registry value "titlebar", which initializeApp
 * (cascapplicationmanagerwrapper.cpp) writes from --system-title-bar /
 * --custom-title-bar - but nothing in the UI could set it. Also, the editor's
 * document name was hidden from its header (it is in the system title bar
 * already) only when --system-title-bar was on the CURRENT command line, so a
 * stored "system" from an earlier run showed the name twice.
 * Fix: a Linux-only "Title bar" setting on the start page (common/loginpage/src/
 * panelsettings.js): settings:init carries titlebar from the registry
 * (prop/cmainwindowimpl.cpp), settings:apply writes it back (applySettings), a
 * change asks for a restart; the webapps:entry handler asks the window holding
 * the editor whether it has the system title bar instead of the command line.
 *
 * This test
 *  1. extracts the REAL code by brace matching / markers - the startup switch
 *     handling (initializeApp), the settings:apply region of applySettings, the
 *     settings:init region of CMainWindowImpl::refreshAboutVersion, the
 *     webapps:entry "if ( ptr )" block, and class CWindowBase::CWindowBasePrivate -
 *     compiles them against Qt 5 (QSettings/QJsonObject are real; the app
 *     classes around them are stubs) in the rd-linux-verify:24.04 image and runs
 *     a start / apply / restart sequence on a real QSettings store;
 *  2. runs the real _on_btn_apply from panelsettings.js with the new select and
 *     checks the settings:init handler and page template know the setting.
 * Baseline: settings:init has no titlebar, Apply does not store it, and a stored
 * "system" without the switch leaves the document name visible -> FAILS.
 *
 * NOT claimed: no window is created here (the existing CX11Decoration /
 * frameless switch is not exercised), the restart prompt and the look of the
 * select need a GUI check on Linux; Windows/macOS do not get the setting.
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_IMAGE docker image (default rd-linux-verify:24.04)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || 'dedc2f770^';
const IMAGE = process.env.RD_IMAGE || 'rd-linux-verify:24.04';

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

function find(text, marker, from) {
	const at = text.indexOf(marker, from || 0);
	if (at === -1) throw new Error(marker + ' not found - the extractor needs updating');
	return at;
}

function region(text, startMarker, endMarker) {
	const a = find(text, startMarker);
	return text.slice(a, find(text, endMarker, a));
}

/* ---- 1. native: start / apply / settings:init / webapps:entry ---- */
const wrapper = src('win-linux/src/cascapplicationmanagerwrapper.cpp');
const startup = region(wrapper, 'if ( InputArgs::contains(L"--system-title-bar") )\n        reg_user.setValue',
	'// read installation time');
const apply = region(wrapper, 'if ( objRoot.contains("keeprecents") )', '#ifdef _UPDMODULE\n        if ( objRoot.contains("autoupdatemode")');
const entryAt = find(wrapper, 'if ( !(cmd.find(L"webapps:entry") == std::wstring::npos) )');
const entry = block(wrapper, find(wrapper, 'if ( ptr ) {', entryAt));
const init = region(src('win-linux/src/prop/cmainwindowimpl.cpp'), 'GET_REGISTRY_USER(reg_user);',
	'#ifndef __OS_WIN_XP\n    _json_obj["rtl"]');
const winbase = src('win-linux/src/windows/cwindowbase.cpp');
const priv = block(winbase, find(winbase, 'class CWindowBase::CWindowBasePrivate')) + ';';

const cpp = `
#include <QCoreApplication>
#include <QApplication>
#include <QScreen>
#include <QJsonArray>
#include <QSettings>
#include <QJsonObject>
#include <QJsonDocument>
#include <QString>
#include <map>
#include <string>
#include <vector>
#include <cstdio>
#include <cstring>

#define REG_GROUP_KEY "Ration"
#define REG_APP_NAME "RationDocs"
#define GET_REGISTRY_USER(variable) QSettings variable(QSettings::NativeFormat, QSettings::UserScope, REG_GROUP_KEY, REG_APP_NAME);
#define GET_REGISTRY_SYSTEM(variable) QSettings variable(QSettings::SystemScope, REG_GROUP_KEY, REG_APP_NAME);
#define TOOLBTN_HEIGHT 28
using std::wstring;

static std::vector<std::wstring> g_args;
struct InputArgs { static bool contains(const wchar_t* a) { for (auto& s : g_args) if (s == a) return true; return false; } };
struct Utils { static QString stringifyJson(const QJsonObject& o) { return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact)); } };
struct AscAppManager { static std::wstring userSettings(const wchar_t*) { return L""; } };

class CWindowBase {
public:
	class CWindowBasePrivate;
	CWindowBase();
	virtual ~CWindowBase() {}
	bool isCustomWindowStyle();
	CWindowBasePrivate* pimpl;
};
${priv}
CWindowBase::CWindowBase() : pimpl(new CWindowBasePrivate) {}
bool CWindowBase::isCustomWindowStyle() { return pimpl->is_custom_window_; }
class CEditorWindow : public CWindowBase {};
class CMainWindow : public CWindowBase {};

struct CCefView { int id = 1; };
struct CAscExecCommand { std::wstring param; const std::wstring& get_Param() const { return param; } };
struct Receiver { void onWebAppsFeatures(int, const std::wstring&) {} };
struct Event { int get_SenderId() const { return 1; } };

struct App {
	CMainWindow* main = nullptr;
	CEditorWindow* detached = nullptr;
	std::map<int, Receiver*> m_receivers;
	std::vector<std::string> sent;
	CMainWindow* mainWindow() { return main; }
	CEditorWindow* editorWindowFromViewId(int) const { return detached; }
	void sendCommandTo(CCefView*, const std::wstring& cmd, const std::wstring& arg) {
		sent.push_back(QString::fromStdWString(cmd + L" " + arg).toStdString());
	}
	void setUserSettings(const wchar_t*, const wchar_t*) {}

	void startup() {
		GET_REGISTRY_SYSTEM(reg_system)
		GET_REGISTRY_USER(reg_user)
		reg_user.setFallbacksEnabled(false);
		${startup}
	}
	void applySettings(const QString& j) {
		QJsonObject objRoot = QJsonDocument::fromJson(j.toUtf8()).object();
		GET_REGISTRY_USER(_reg_user)
		${apply}
	}
	QString settingsInit() {
		QJsonObject _json_obj;
		${init}
		return Utils::stringifyJson(_json_obj);
	}
	void webappsEntry(bool in_window) {
		CMainWindow mw; CEditorWindow ew;
		main = &mw; detached = in_window ? &ew : nullptr;
		CCefView view; CCefView* ptr = &view;
		CAscExecCommand data; CAscExecCommand* pData = &data;
		Event ev; Event* event = &ev; int sid = 1;
		sent.clear();
		${entry}
		bool hidden = false;
		for (auto& s : sent) if (s.find("title-doc-name{display:none}") != std::string::npos) hidden = true;
		CWindowBase* w = in_window ? static_cast<CWindowBase*>(&ew) : &mw;
		printf("entry %s window=%s docname=%s\\n", in_window ? "detached" : "tab",
			w->isCustomWindowStyle() ? "custom" : "system", hidden ? "hidden" : "shown");
		main = nullptr; detached = nullptr;
	}
};

int main(int argc, char** argv) {
	QApplication qa(argc, argv);      // settings:init lists the screens (#1548)
	App app;
	for (int i = 1; i < argc; i++) {
		std::string c = argv[i];
		if (c == "reset") {
			{ GET_REGISTRY_USER(u) u.clear(); }
			{ GET_REGISTRY_SYSTEM(s) s.clear(); }
			printf("reset\\n");
		} else if (c == "sysforce") {
			GET_REGISTRY_SYSTEM(s) s.setValue("titlebar", "custom");
			printf("system config titlebar=custom\\n");
		} else if (c.rfind("start", 0) == 0) {
			g_args.clear();
			if (c.size() > 6) g_args.push_back(QString::fromStdString(c.substr(6)).toStdWString());
			app.startup();
			GET_REGISTRY_USER(u)
			printf("%s -> registry titlebar=%s\\n", c.c_str(), u.value("titlebar").toString().toUtf8().constData());
		} else if (c.rfind("apply:", 0) == 0) {
			app.applySettings(QString::fromStdString(c.substr(6)));
			GET_REGISTRY_USER(u)
			printf("apply %s -> registry titlebar=%s\\n", c.substr(6).c_str(), u.value("titlebar").toString().toUtf8().constData());
		} else if (c == "init") {
			printf("settings:init %s\\n", app.settingsInit().toUtf8().constData());
		} else if (c == "tab" || c == "detached") {
			app.webappsEntry(c == "detached");
		}
	}
	return 0;
}
`;

const steps = [
	'reset', 'start', 'init', 'tab',                               // A first start: built-in, as today
	'apply:{"titlebar":"system"}', 'start', 'init', 'tab', 'detached', // B chosen in Settings, restarted
	'apply:{"titlebar":"bogus"}',                                 // C junk is ignored
	'apply:{"titlebar":"custom"}', 'start', 'init', 'tab',        // D back to built-in
	'reset', 'start:--system-title-bar', 'start', 'tab',          // E switch on an earlier run only
	'reset', 'sysforce', 'start', 'init',                         // F system config forces built-in
];

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue2504-'));
let out;
try {
	fs.writeFileSync(path.join(tmp, 'main.cpp'), cpp);
	fs.writeFileSync(path.join(tmp, 'run.sh'), `set -e
cd /t
g++ -std=c++17 -fPIC -w -o tb main.cpp $(pkg-config --cflags --libs Qt5Widgets)
QT_QPA_PLATFORM=offscreen HOME=/t/home XDG_CONFIG_HOME=/t/home/.config XDG_CONFIG_DIRS=/t/etc ./tb ${steps.map((s) => `'${s}'`).join(' ')}
`);
	const r = spawnSync('docker', ['run', '--rm', '--memory=2g', '-v', `${tmp}:/t`, IMAGE, 'sh', '/t/run.sh'], { encoding: 'utf8' });
	if (r.status !== 0) {
		process.stderr.write((r.stdout || '') + (r.stderr || ''));
		throw new Error('native harness failed to build/run');
	}
	out = r.stdout.trim().split('\n');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
out.forEach((l) => console.log('native ' + l));
const at = (prefix, n) => out.filter((l) => l.startsWith(prefix))[n];

// A: default unchanged - harness sanity, same on baseline
assert.strictEqual(at('start ->', 0), 'start -> registry titlebar=custom', 'harness broken: default is not the built-in title bar');
assert.strictEqual(at('entry', 0), 'entry tab window=custom docname=shown', 'harness broken: built-in title bar hides the document name');
// E: a stored "system" without the switch on this run - the document name must be hidden
assert.strictEqual(at('entry', 4), 'entry tab window=system docname=hidden',
	'with the system title bar stored from an earlier run the editor header still shows the document name a second time');
// B..D, F: the setting
assert.ok(/"titlebar":"custom"/.test(at('settings:init', 0)), 'settings:init does not tell the start page the title bar in use');
assert.strictEqual(at('apply', 0), 'apply {"titlebar":"system"} -> registry titlebar=system', 'settings:apply does not store the title bar');
assert.strictEqual(at('start ->', 1), 'start -> registry titlebar=system', 'a title bar chosen in Settings does not survive a restart');
assert.ok(/"titlebar":"system"/.test(at('settings:init', 1)), 'settings:init does not show the stored title bar');
assert.strictEqual(at('entry', 1), 'entry tab window=system docname=hidden', 'system title bar from Settings: tab editor shows the name twice');
assert.strictEqual(at('entry', 2), 'entry detached window=system docname=hidden', 'system title bar from Settings: window editor shows the name twice');
assert.strictEqual(at('apply', 1), 'apply {"titlebar":"bogus"} -> registry titlebar=system', 'an unknown title bar value was stored');
assert.strictEqual(at('apply', 2), 'apply {"titlebar":"custom"} -> registry titlebar=custom', 'switching back to the built-in title bar is not stored');
assert.strictEqual(at('entry', 3), 'entry tab window=custom docname=shown', 'built-in title bar hides the document name');
assert.ok(!/titlebar/.test(at('settings:init', 3)), 'setting offered although the system config forces the built-in title bar');

/* ---- 2. start page: the select and what Apply sends ---- */
const ps = src('common/loginpage/src/panelsettings.js');
const applySrc = block(ps, ps.lastIndexOf('\n', find(ps, 'function _on_btn_apply(e)')) + 1);
const initSrc = block(ps, ps.lastIndexOf('\n', find(ps, 'function _on_app_message(cmd, param)')) + 1);

const sent = [];
const hidden = { is: () => false, find: () => hidden, val: () => undefined, selectpicker: () => hidden };
const $ = () => hidden;
const sdk = { command: (c, p) => sent.push([c, JSON.parse(p)]), LocalFileRemoveAllRecents: () => {} };
const field = (v) => ({ val: (x) => (x === undefined ? v : field(v)), removeClass: () => {}, addClass: () => {} });
const select = (v) => ({ val: () => v, selectpicker: () => {} });
const checkbox = (v) => ({ prop: () => v });
const store = {};
const localStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } };
const names = ['$', 'sdk', 'localStorage', '$userName', '$chOpenMode', '$optsLang', '$optsUIScaling', '$optsUITheme',
	'$optsLaunchMode', '$optsTitleBar', '$optsAutoupdateMode', '$optsSpellcheckMode', '$chGpu', '$chUseAI', '$chKeepRecents',
	'appSettings', '$btnApply', '$panel', '_validate_user_name', '_lock_createnew'];
// selects/switches added to the page later are not set here (undefined), as when hidden
const extras = [...new Set(applySrc.match(/\$(?:opts|ch)\w+/g))].filter((n) => !names.includes(n));
function runApply(appSettings, titleBar) {
	sent.length = 0;
	new Function(...names, ...extras, applySrc + '\nreturn _on_btn_apply;')(
		$, sdk, localStorage, field('Ann'), checkbox(false), hidden, undefined, undefined,
		undefined, select(titleBar), undefined, undefined, undefined, undefined, undefined,
		appSettings, { disable: () => {} }, {}, () => true, () => {})({});
	assert.strictEqual(sent.length, 1, 'stub harness broken: settings:apply not sent');
	return sent[0][1];
}
const changed = runApply({ titlebar: 'custom' }, 'system');
console.log('settings:apply (changed)', JSON.stringify(changed));
assert.ok(/id="opts-title-bar"/.test(ps) && /appSettings\.titlebar/.test(initSrc), 'the start page has no "Title bar" setting');
assert.strictEqual(changed.titlebar, 'system', 'settings:apply does not carry the title bar to the app');
assert.strictEqual(changed.restart, true, 'changing the title bar does not ask for the restart it needs');
const same = runApply({ titlebar: 'system' }, 'system');
console.log('settings:apply (unchanged)', JSON.stringify(same));
assert.strictEqual(same.restart, false, 'an unchanged title bar must not ask for a restart');

console.log('PASS #2504: the title bar is chosen in Settings, survives a restart, and the editor header no longer repeats the name');
