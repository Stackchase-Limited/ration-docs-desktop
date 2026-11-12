/*
 * #2321 - "Use XDG File picker instead of the GTK file picker" (Linux).
 *
 * What there was: win-linux/src/utils.cpp WindowHelper::useGtkDialog() picks the
 * in-process GTK chooser unless the session is Wayland (#2168), the app was started
 * with --xdg-desktop-portal, or that flag was remembered in the user registry
 * ("--xdg-desktop-portal"). On X11 nothing in the UI could switch to the desktop's
 * own dialog (the XDG desktop portal: KDE's dialog on Plasma, etc.).
 * What now: a "Use the desktop's file dialog (portal)" switch in the start page
 * settings, Linux/X11 only, off by default (today's behaviour). settings:init
 * carries xdgportal = !useGtkDialog() (cmainwindowimpl.cpp); settings:apply stores
 * it as the registry value useGtkDialog() already reads
 * (cascapplicationmanagerwrapper.cpp); no restart is needed - every dialog asks
 * useGtkDialog() when it opens. A Wayland session still always gets the portal,
 * so the switch is not shown there; the command-line flags still win.
 *
 * This test
 *  1. compiles the REAL useGtkDialog/isWaylandSession (utils.cpp), the REAL
 *     xdgportal statement of settings:init (cmainwindowimpl.cpp) and the REAL
 *     xdgportal block of settings:apply (cascapplicationmanagerwrapper.cpp), each
 *     extracted by brace matching, against stubs for QSettings/QString/QJsonObject/
 *     InputArgs, and checks: X11 default -> GTK and switch shown off; switch on ->
 *     portal; switch off -> GTK again; Wayland -> portal, switch not shown;
 *  2. runs the REAL _on_btn_apply from panelsettings.js with the switch ticked:
 *     settings:apply must carry xdgportal:true; and checks the settings:init
 *     handler shows the switch only when the app sends xdgportal.
 * BASELINE=1 reads the sources from BASE_REF: no switch, settings:init has no
 * xdgportal and Apply sends none -> FAILS.
 *
 * NOT claimed: the look of the switch; that the portal dialog itself works on a
 * given desktop (xdg-desktop-portal + a backend must be installed - the code path
 * is the one Wayland sessions already use). Needs a Linux GUI check.
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps); BASELINE=1, BASE_REF.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || '116bd6a1d^';

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
function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return '';
		throw new Error(marker + ' not found');
	}
	return block(text, text.lastIndexOf('\n', at) + 1);
}

/* ---- 1. native: useGtkDialog + the settings:init / settings:apply glue ---- */
const utils = src('win-linux/src/utils.cpp');
const fns = [extract(utils, 'auto isWaylandSession() -> bool'), extract(utils, 'auto useGtkDialog() -> bool')].join('\n');
const wrapper = src('win-linux/src/cascapplicationmanagerwrapper.cpp');
const applyBlock = extract(wrapper, 'objRoot.contains("xdgportal")', true);
const impl = src('win-linux/src/prop/cmainwindowimpl.cpp');
const initLine = (impl.match(/\n[^\n]*if \( !WindowHelper::isWaylandSession\(\) \)\n[^\n]*_json_obj\["xdgportal"\][^\n]*;/) || [''])[0];

const cpp = `
#include <string>
#include <map>
#include <cstdio>
#include <cstdlib>
#include <strings.h>
namespace Qt { enum CaseSensitivity { CaseInsensitive, CaseSensitive }; }
struct QByteArray { std::string s; bool isEmpty() const { return s.empty(); } };
static QByteArray qgetenv(const char* n) { const char* v = getenv(n); return QByteArray{v ? v : ""}; }
struct QString { std::string s; QString(const QByteArray& b) : s(b.s) {}
	int compare(const char* o, Qt::CaseSensitivity) const { return strcasecmp(s.c_str(), o); } };
struct QVariant { bool b; bool toBool() const { return b; } };
static std::map<std::string, bool> g_reg;
struct QSettings { QVariant value(const char* k, bool d) { auto i = g_reg.find(k); return {i == g_reg.end() ? d : i->second}; }
	void setValue(const char* k, bool v) { g_reg[k] = v; } };
#define GET_REGISTRY_USER(v) QSettings v;
namespace InputArgs { static bool contains(const wchar_t*) { return false; } }
struct QJsonValue { bool set = false, b = false; bool toBool(bool d) const { return set ? b : d; }
	QJsonValue& operator=(bool v) { set = true; b = v; return *this; } };
struct QJsonObject { std::map<std::string, QJsonValue> m;
	bool contains(const char* k) const { return m.count(k) > 0; } QJsonValue& operator[](const char* k) { return m[k]; } };
namespace WindowHelper {
${fns}
}
static void init(QJsonObject& _json_obj) { ${initLine} }
static void apply(QJsonObject& objRoot) { QSettings _reg_user; ${applyBlock} }
static void show(const char* what) {
	QJsonObject o; init(o);
	printf("%s: dialog=%s switch=%s\\n", what, WindowHelper::useGtkDialog() ? "gtk" : "portal",
		!o.contains("xdgportal") ? "hidden" : (o["xdgportal"].toBool(false) ? "on" : "off"));
}
int main() {
	setenv("XDG_SESSION_TYPE", "x11", 1); unsetenv("WAYLAND_DISPLAY");
	show("x11 default");
	{ QJsonObject a; a["xdgportal"] = true; apply(a); } show("x11 switch on");
	{ QJsonObject a; a["xdgportal"] = false; apply(a); } show("x11 switch off");
	setenv("XDG_SESSION_TYPE", "wayland", 1); show("wayland");
	return 0;
}
`;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue2321-'));
let lines;
try {
	fs.writeFileSync(path.join(tmp, 'drv.cpp'), cpp);
	const cxx = process.env.CXX || (process.platform === 'darwin' ? 'clang++' : 'g++');
	execFileSync(cxx, ['-std=c++14', '-w', '-o', path.join(tmp, 'drv'), path.join(tmp, 'drv.cpp')], { stdio: 'inherit' });
	lines = execFileSync(path.join(tmp, 'drv'), { encoding: 'utf8' }).trim().split('\n');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
lines.forEach((l) => console.log('native ' + l));
assert.ok(/^x11 default: dialog=gtk/.test(lines[0]), 'stub harness broken: X11 default is not GTK');
assert.ok(/^wayland: dialog=portal switch=hidden/.test(lines[3]), 'Wayland must keep the portal and not offer the switch');
assert.strictEqual(lines[0], 'x11 default: dialog=gtk switch=off', 'settings:init does not offer the portal switch on X11');
assert.strictEqual(lines[1], 'x11 switch on: dialog=portal switch=on', 'turning the switch on does not make the file dialogs use the portal');
assert.strictEqual(lines[2], 'x11 switch off: dialog=gtk switch=off', 'turning the switch off does not bring the GTK dialog back');

/* ---- 2. start page: the switch and what Apply sends ---- */
const ps = src('common/loginpage/src/panelsettings.js');
const applySrc = extract(ps, 'function _on_btn_apply(e)');
const initSrc = extract(ps, 'function _on_app_message(cmd, param)');
const sent = [];
const hidden = { is: () => false, find: () => hidden, val: () => undefined, selectpicker: () => hidden };
const $ = () => hidden;
const sdk = { command: (c, p) => sent.push([c, JSON.parse(p)]), LocalFileRemoveAllRecents: () => {} };
const field = (v) => ({ val: (x) => (x === undefined ? v : field(v)), removeClass: () => {}, addClass: () => {} });
const checkbox = (v) => ({ prop: () => v });
const store = {};
const localStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } };
const appSettings = { keeprecents: true, xdgportal: false };
const names = ['$', 'sdk', 'localStorage', '$userName', '$chOpenMode', '$optsLang', '$optsUIScaling', '$optsUITheme',
	'$optsLaunchMode', '$optsAutoupdateMode', '$optsSpellcheckMode', '$chGpu', '$chUseAI', '$chKeepRecents', '$chXdgPortal',
	'appSettings', '$btnApply', '$panel', '_validate_user_name', '_lock_createnew'];
// selects/switches added to the page by other changes are not set here (undefined), as when hidden
const extras = [...new Set(applySrc.match(/\$(?:opts|ch)\w+/g))].filter((n) => !names.includes(n));
new Function(...names, ...extras, applySrc + '\nreturn _on_btn_apply;')(
	$, sdk, localStorage, field('Ann'), checkbox(false), hidden, undefined, undefined,
	undefined, undefined, undefined, undefined, undefined, checkbox(true), checkbox(true),
	appSettings, { disable: () => {} }, {}, () => true, () => {})({});
assert.strictEqual(sent.length, 1, 'stub harness broken: settings:apply not sent');
console.log('settings:apply sent', JSON.stringify(sent[0][1]));
assert.ok(/sett-xdg-portal/.test(ps) && /appSettings\.xdgportal !== undefined/.test(initSrc),
	'the start page has no "Use the desktop\'s file dialog (portal)" switch');
assert.strictEqual(sent[0][1].xdgportal, true, 'settings:apply does not carry the switch to the app');

console.log('PASS #2321: on X11 the file dialogs can use the desktop portal; GTK stays the default');
