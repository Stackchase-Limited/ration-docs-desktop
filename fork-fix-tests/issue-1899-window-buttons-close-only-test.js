/*
 * #1899 "Option to hide minimise/maximise buttons on Linux": GNOME (other than
 * Ubuntu's layout) gives windows only a close button, but our built-in title
 * bar always drew minimize, maximize and close.
 *
 * Cause: desktop-apps win-linux/src/windows/cwindowbase.cpp
 * CWindowBase::createTopPanel adds all three buttons unconditionally for every
 * window with the built-in (custom) title bar, and nothing could change that.
 * Fix: a Linux-only start-page setting "Window buttons" (Minimize, maximize and
 * close / Close only; default unchanged) - settings:init carries windowbuttons
 * from the user registry value "windowButtons" (prop/cmainwindowimpl.cpp),
 * settings:apply stores it (applySettings), CWindowBase's private part reads it
 * and createTopPanel hides minimize/maximize when it is "close"; the editor's
 * centerTitle (ceditorwindow_p.h) counts the visible buttons, not always three.
 *
 * This test
 *  1. extracts the REAL CWindowBase::CWindowBasePrivate, CWindowBase::
 *     createTopPanel, CEditorWindowPrivate's centerTitle, and the settings:apply /
 *     settings:init regions (applySettings, refreshAboutVersion) by brace matching
 *     / markers, compiles them against Qt 5 Widgets (real QSettings, QWidget,
 *     QHBoxLayout, QPushButton; the app classes around them are stubs) in the
 *     rd-linux-verify:24.04 image, runs it offscreen, applies the setting, builds
 *     a title bar, shows it and reports which buttons are visible and the title
 *     label's centring margin;
 *  2. runs the real _on_btn_apply from panelsettings.js with the new select.
 * Baseline: no setting reaches the registry, all three buttons are shown -> FAILS.
 *
 * NOT claimed: the real windows (CMainWindow, CEditorWindow, CPresenterWindow)
 * are not built here - they call the same createTopPanel; the look of the title
 * bar and the restart prompt need a GUI check on Linux. Reading GNOME's
 * button-layout automatically is not done (opt-in setting only).
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
const BASE_REF = process.env.BASE_REF || 'b61080a05^';
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

/* ---- 1. native ---- */
const winbase = src('win-linux/src/windows/cwindowbase.cpp');
const priv = block(winbase, find(winbase, 'class CWindowBase::CWindowBasePrivate')) + ';';
const topPanel = block(winbase, find(winbase, 'QWidget* CWindowBase::createTopPanel(QWidget *parent)'));
const edp = src('win-linux/src/windows/ceditorwindow_p.h');
const center = block(edp, find(edp, 'auto centerTitle(double dpiRatio)->void'));
const wrapper = src('win-linux/src/cascapplicationmanagerwrapper.cpp');
const apply = region(wrapper, 'if ( objRoot.contains("keeprecents") )', '#ifdef _UPDMODULE\n        if ( objRoot.contains("autoupdatemode")');
const init = region(src('win-linux/src/prop/cmainwindowimpl.cpp'), 'GET_REGISTRY_USER(reg_user);',
	'#ifndef __OS_WIN_XP\n    _json_obj["rtl"]');

const cpp = `
#include <QApplication>
#include <QSettings>
#include <QJsonObject>
#include <QJsonDocument>
#include <QWidget>
#include <QLabel>
#include <QHBoxLayout>
#include <QPushButton>
#include <QVector>
#include <QMap>
#include <functional>
#include <string>
#include <cstdio>

#define REG_GROUP_KEY "Ration"
#define REG_APP_NAME "RationDocs"
#define GET_REGISTRY_USER(variable) QSettings variable(QSettings::NativeFormat, QSettings::UserScope, REG_GROUP_KEY, REG_APP_NAME);
#define GET_REGISTRY_SYSTEM(variable) QSettings variable(QSettings::SystemScope, REG_GROUP_KEY, REG_APP_NAME);
#define TOOLBTN_WIDTH 40
#define TITLEBTN_WIDTH 28
#define ICON_SPACER_WIDTH 9

struct AscAppManager { static std::wstring userSettings(const wchar_t*) { return L""; } static bool isRtlEnabled() { return false; } };
class CPushButton : public QPushButton { public: using QPushButton::QPushButton; };

class CWindowBase {
public:
	class CWindowBasePrivate;
	CWindowBase();
	virtual ~CWindowBase() {}
	bool isCustomWindowStyle();
	enum BtnType { Btn_Minimize, Btn_Maximize, Btn_Close };
	CPushButton* createToolButton(QWidget* parent, const QString& name) {
		CPushButton* b = new CPushButton(parent); b->setObjectName(name); b->setFixedSize(TITLEBTN_WIDTH, 28); return b;
	}
	QWidget* createTopPanel(QWidget *parent);
	void onMinimizeEvent() {} void onMaximizeEvent() {} void onCloseEvent() {}
	QVector<CPushButton*> m_pTopButtons = QVector<CPushButton*>(3, nullptr);
	QWidget* m_boxTitleBtns = nullptr;
	double m_dpiRatio = 1.0;
	CWindowBasePrivate* pimpl;
};
${priv}
CWindowBase::CWindowBase() : pimpl(new CWindowBasePrivate) {}
bool CWindowBase::isCustomWindowStyle() { return pimpl->is_custom_window_; }
${topPanel}

struct Data { bool hasError() const { return false; } };
struct Panel { Data d; Data* data() { return &d; } };
struct EditorPriv {
	CWindowBase* window;
	QMap<QString, QWidget*> m_mapTitleButtons;
	int leftBtnsCount = 4;
	QLabel* iconuser = nullptr;
	QWidget* boxtitlelabel = nullptr;
	Panel p; Panel* m_panel = &p;
	bool viewerMode() const { return false; }
	bool fillformMode() const { return false; }
	${center}
};

struct App {
	void setUserSettings(const wchar_t*, const wchar_t*) {}
	void applySettings(const QString& j) {
		QJsonObject objRoot = QJsonDocument::fromJson(j.toUtf8()).object();
		GET_REGISTRY_USER(_reg_user)
		${apply}
	}
	QString settingsInit() {
		QJsonObject _json_obj;
		${init}
		return QString::fromUtf8(QJsonDocument(_json_obj).toJson(QJsonDocument::Compact));
	}
};

int main(int argc, char** argv) {
	QApplication qa(argc, argv);
	App app;
	{ GET_REGISTRY_USER(u) u.clear(); u.setValue("titlebar", "custom"); }
	for (int i = 1; i < argc; i++) {
		std::string c = argv[i];
		if (c.rfind("apply:", 0) == 0) {
			app.applySettings(QString::fromStdString(c.substr(6)));
			GET_REGISTRY_USER(u)
			printf("apply %s -> registry windowButtons=%s\\n", c.substr(6).c_str(),
				u.value("windowButtons", "(unset)").toString().toUtf8().constData());
		} else if (c == "init") {
			printf("settings:init %s\\n", app.settingsInit().toUtf8().constData());
		} else if (c == "window") {
			CWindowBase w;
			QWidget top; top.resize(800, 28);
			QHBoxLayout* l = new QHBoxLayout(&top);
			l->setContentsMargins(0, 0, 0, 0);
			w.m_boxTitleBtns = w.createTopPanel(&top);
			l->addWidget(w.m_boxTitleBtns);
			EditorPriv ep; ep.window = &w;
			ep.boxtitlelabel = new QWidget(w.m_boxTitleBtns);
			ep.centerTitle(1.0);
			top.show(); qa.processEvents();
			QString vis;
			for (auto* b : w.m_pTopButtons) if (b && b->isVisible()) vis += (vis.isEmpty() ? "" : ",") + b->objectName().mid(10);
			QMargins m = ep.boxtitlelabel->contentsMargins();
			printf("window buttons=%s title_margin_left=%d right=%d\\n", vis.toUtf8().constData(), m.left(), m.right());
		}
	}
	return 0;
}
`;

const steps = ['init', 'window', 'apply:{"windowbuttons":"close"}', 'init', 'window',
	'apply:{"windowbuttons":"odd"}', 'apply:{"windowbuttons":"all"}', 'window'];

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1899-'));
let out;
try {
	fs.writeFileSync(path.join(tmp, 'main.cpp'), cpp);
	fs.writeFileSync(path.join(tmp, 'run.sh'), `set -e
cd /t
g++ -std=c++17 -fPIC -w -o wb main.cpp $(pkg-config --cflags --libs Qt5Widgets)
HOME=/t/home QT_QPA_PLATFORM=offscreen ./wb ${steps.map((s) => `'${s}'`).join(' ')} 2>/dev/null
`);
	const r = spawnSync('docker', ['run', '--rm', '-v', `${tmp}:/t`, IMAGE, 'sh', '/t/run.sh'], { encoding: 'utf8' });
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

const all = at('window', 0);
assert.ok(/^window buttons=Minimize,Maximize,Close /.test(all), 'harness broken: default title bar is not minimize/maximize/close');
assert.ok(/"windowbuttons":"all"/.test(at('settings:init', 0)), 'settings:init does not tell the start page the window buttons');
assert.strictEqual(at('apply', 0), 'apply {"windowbuttons":"close"} -> registry windowButtons=close', 'settings:apply does not store "Close only"');
assert.ok(/"windowbuttons":"close"/.test(at('settings:init', 1)), 'settings:init does not show the stored "Close only"');
const closeOnly = at('window', 1);
assert.ok(/^window buttons=Close /.test(closeOnly), 'with "Close only" the title bar still shows minimize/maximize');
const margin = (l) => Number(/right=(-?\d+)/.exec(l)[1]) - Number(/left=(-?\d+)/.exec(l)[1]);
assert.ok(margin(closeOnly) > margin(all), 'the title is still centred as if three buttons were on the right');
assert.strictEqual(at('apply', 1), 'apply {"windowbuttons":"odd"} -> registry windowButtons=close', 'an unknown value was stored');
assert.strictEqual(at('apply', 2), 'apply {"windowbuttons":"all"} -> registry windowButtons=all', 'switching back to all buttons is not stored');
assert.ok(/^window buttons=Minimize,Maximize,Close /.test(at('window', 2)), 'switching back does not bring the buttons back');

/* ---- 2. start page ---- */
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
	'$optsLaunchMode', '$optsTitleBar', '$optsWindowButtons', '$optsAutoupdateMode', '$optsSpellcheckMode', '$chGpu',
	'$chUseAI', '$chKeepRecents', 'appSettings', '$btnApply', '$panel', '_validate_user_name', '_lock_createnew'];
// selects/switches added to the page later are not set here (undefined), as when hidden
const extras = [...new Set(applySrc.match(/\$(?:opts|ch)\w+/g))].filter((n) => !names.includes(n));
function runApply(appSettings, buttons) {
	sent.length = 0;
	new Function(...names, ...extras, applySrc + '\nreturn _on_btn_apply;')(
		$, sdk, localStorage, field('Ann'), checkbox(false), hidden, undefined, undefined,
		undefined, undefined, select(buttons), undefined, undefined, undefined, undefined, undefined,
		appSettings, { disable: () => {} }, {}, () => true, () => {})({});
	assert.strictEqual(sent.length, 1, 'stub harness broken: settings:apply not sent');
	return sent[0][1];
}
const changed = runApply({ windowbuttons: 'all' }, 'close');
console.log('settings:apply (changed)', JSON.stringify(changed));
assert.ok(/id="opts-window-buttons"/.test(ps) && /appSettings\.windowbuttons/.test(initSrc), 'the start page has no "Window buttons" setting');
assert.strictEqual(changed.windowbuttons, 'close', 'settings:apply does not carry the window buttons to the app');
assert.strictEqual(changed.restart, true, 'changing the window buttons does not ask for the restart it needs');
assert.strictEqual(runApply({ windowbuttons: 'close' }, 'close').restart, false, 'an unchanged value must not ask for a restart');

console.log('PASS #1899: "Close only" hides minimize/maximize from the built-in title bar and keeps the title centred');
