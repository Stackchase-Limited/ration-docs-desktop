/*
 * #1548 "Presentation mode in a multi-display setup on Linux (KDE/Wayland)": with
 * three or more screens the slideshow always opened on the same "wrong" screen
 * (a rotated side monitor for the reporter; screen 4 of 7 for a commenter on
 * Windows) and there was no way to choose another.
 *
 * Cause: desktop-apps win-linux/src/utils.cpp WindowHelper::constructFullscreenWidget
 * picks the slideshow's screen by itself - the window's own screen, or in
 * presenter mode the screen at the mirrored index (count - index - 1) of Qt's
 * screen list. With two screens that is "the other one"; with three or more it
 * is an arbitrary screen (even the presenter's own), and nothing could change it.
 * Fix: an opt-in start-page setting "Slideshow screen" (Automatic by default;
 * Windows/Linux): settings:init lists the connected screens and the stored
 * choice (prop/cmainwindowimpl.cpp), settings:apply stores the screen's name as
 * the user registry value "slideshowScreen" or removes it for Automatic
 * (applySettings), and constructFullscreenWidget uses Utils::slideshowScreen()
 * when that screen is connected.
 *
 * This test
 *  1. extracts the REAL WindowHelper::constructFullscreenWidget and
 *     Utils::slideshowScreen (brace matching) and the settings:apply /
 *     settings:init regions (markers), compiles them against Qt 5.15 in the
 *     rd-linux-verify:24.04 image with stubbed app classes, and runs it on the
 *     offscreen platform with three REAL QScreens on one virtual desktop, added
 *     through QWindowSystemInterface::handleScreenAdded ("A" 800x600 primary,
 *     "B" 1920x1080 at x=800, "C" 1280x1024 at x=2720); a presenter on B (the middle screen)
 *     starts the slideshow before and after choosing C, with a screen that is
 *     not connected, and back on Automatic; it reports which QScreen the
 *     full-screen widget ended up on;
 *  2. runs the real _on_btn_apply from panelsettings.js with the new select.
 * Baseline: the setting does not exist, the slideshow stays on B -> FAILS.
 *
 * (On Automatic with the presenter on the middle of three screens the slideshow
 * landed on the presenter's own screen B; a separate commit changes that - see
 * issue-1548-slideshow-middle-screen-test.js. This test accepts either.)
 *
 * NOT claimed: no CEF view or real CTabPanel; whether a window manager
 * (KWin/Mutter under XWayland, Windows) honours the full-screen window's screen
 * needs a GUI check with real monitors; the look of the select is not checked;
 * macOS does not get the setting.
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
const BASE_REF = process.env.BASE_REF || '56c65c602^';
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
const utils = src('win-linux/src/utils.cpp');
const fullscr = block(utils, find(utils, 'auto constructFullscreenWidget(QWidget * panelwidget) -> CFullScrWidget *'));
// absent before the fix; nothing calls it there
const chooser = utils.includes('QScreen * Utils::slideshowScreen()')
	? block(utils, find(utils, 'QScreen * Utils::slideshowScreen()'))
	: 'QScreen * Utils::slideshowScreen() { return nullptr; }';
const wrapper = src('win-linux/src/cascapplicationmanagerwrapper.cpp');
const apply = region(wrapper, 'if ( objRoot.contains("keeprecents") )', '#ifdef _UPDMODULE\n        if ( objRoot.contains("autoupdatemode")');
const init = region(src('win-linux/src/prop/cmainwindowimpl.cpp'), 'GET_REGISTRY_USER(reg_user);',
	'#ifndef __OS_WIN_XP\n    _json_obj["rtl"]');

const cpp = `
#include <QApplication>
#include <QScreen>
#include <QSettings>
#include <QJsonObject>
#include <QJsonArray>
#include <QJsonDocument>
#include <QWidget>
#include <QWindow>
#include <QIcon>
#include <qpa/qplatformscreen.h>
#include <qpa/qwindowsysteminterface.h>
#include <string>
#include <cstdio>

#define REG_GROUP_KEY "Ration"
#define REG_APP_NAME "RationDocs"
#define GET_REGISTRY_USER(variable) QSettings variable(QSettings::NativeFormat, QSettings::UserScope, REG_GROUP_KEY, REG_APP_NAME);
#define GET_REGISTRY_SYSTEM(variable) QSettings variable(QSettings::SystemScope, REG_GROUP_KEY, REG_APP_NAME);
#define qobject_cast dynamic_cast

struct AscAppManager { static std::wstring userSettings(const wchar_t*) { return L""; } static bool isRtlEnabled() { return false; } };
struct Utils { static QIcon appIcon() { return QIcon(); } static QScreen * slideshowScreen(); };
${chooser}

class CFullScrWidget : public QWidget { public: using QWidget::QWidget; };
struct PanelData { QString title() const { return "deck.pptx"; } };
class CTabPanel : public QWidget {
public:
	bool m_reporter = false;
	PanelData d;
	bool reporterMode() const { return m_reporter; }
	PanelData * data() { return &d; }
};

namespace WindowHelper {
${fullscr}
}

// one virtual desktop of three screens, as a multi-monitor X11/Windows session
static QList<QPlatformScreen *> g_desktop;
class Screen : public QPlatformScreen {
public:
	Screen(const QString& n, const QRect& r) : n_(n), r_(r) { g_desktop.append(this); }
	QRect geometry() const override { return r_; }
	int depth() const override { return 32; }
	QImage::Format format() const override { return QImage::Format_ARGB32_Premultiplied; }
	QString name() const override { return n_; }
	QList<QPlatformScreen *> virtualSiblings() const override { return g_desktop; }
	QString n_; QRect r_;
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
	QPlatformScreen * offscreen = QGuiApplication::primaryScreen()->handle();
	QWindowSystemInterface::handleScreenAdded(new Screen("A", QRect(0, 0, 800, 600)), true);
	QWindowSystemInterface::handleScreenAdded(new Screen("B", QRect(800, 0, 1920, 1080)));
	QWindowSystemInterface::handleScreenAdded(new Screen("C", QRect(2720, 0, 1280, 1024)));
	QWindowSystemInterface::handleScreenRemoved(offscreen);
	qa.processEvents();
	App app;
	{ GET_REGISTRY_USER(u) u.clear(); }
	for (int i = 1; i < argc; i++) {
		std::string c = argv[i];
		if (c.rfind("apply:", 0) == 0) {
			app.applySettings(QString::fromStdString(c.substr(6)));
			GET_REGISTRY_USER(u)
			printf("apply %s -> registry slideshowScreen=%s\\n", c.substr(6).c_str(),
				u.value("slideshowScreen", "(unset)").toString().toUtf8().constData());
		} else if (c == "init") {
			printf("settings:init %s\\n", app.settingsInit().toUtf8().constData());
		} else if (c == "reporter" || c == "normal") {
			CTabPanel * panel = new CTabPanel;          // presenter's document, on screen B
			panel->m_reporter = c == "reporter";
			panel->setGeometry(900, 100, 600, 400);
			CFullScrWidget * fs = WindowHelper::constructFullscreenWidget(panel);
			qa.processEvents();
			QScreen * s = fs->windowHandle() ? fs->windowHandle()->screen() : nullptr;
			QRect g = fs->geometry();
			printf("slideshow %s screen=%s geometry=%d,%d %dx%d\\n", c.c_str(),
				s ? s->name().toUtf8().constData() : "(none)", g.x(), g.y(), g.width(), g.height());
			delete fs;
		}
	}
	return 0;
}
`;

const steps = ['init', 'reporter', 'apply:{"slideshowscreen":"C"}', 'init', 'reporter', 'normal',
	'apply:{"slideshowscreen":"GONE"}', 'init', 'reporter', 'apply:{"slideshowscreen":"auto"}', 'init', 'reporter', 'normal'];

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1548-'));
let out;
try {
	fs.writeFileSync(path.join(tmp, 'main.cpp'), cpp);
	fs.writeFileSync(path.join(tmp, 'run.sh'), `set -e
cd /t
QTV=$(pkg-config --modversion Qt5Core)
QTGUI=$(pkg-config --variable=includedir Qt5Gui)/QtGui
g++ -std=c++17 -fPIC -w -o ss main.cpp $(pkg-config --cflags --libs Qt5Widgets) -I$QTGUI/$QTV -I$QTGUI/$QTV/QtGui
HOME=/t/home QT_QPA_PLATFORM=offscreen ./ss ${steps.map((s) => `'${s}'`).join(' ')} 2>/dev/null
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

// what "Automatic" picks for a presenter on B is not this test's subject (B before the
// follow-up commit for the middle screen, A after it); it must just not be C and stay the same
const automatic = at('slideshow', 0);
assert.ok(/^slideshow reporter screen=[AB] /.test(automatic), 'harness broken: the automatic presenter-mode choice is ' + automatic);
const init0 = JSON.parse(at('settings:init', 0).slice('settings:init '.length));
assert.strictEqual(JSON.stringify(init0.screens), '[{"height":600,"name":"A","primary":true,"width":800},' +
	'{"height":1080,"name":"B","primary":false,"width":1920},{"height":1024,"name":"C","primary":false,"width":1280}]',
	'settings:init does not list the connected screens');
assert.strictEqual(init0.slideshowscreen, 'auto', 'settings:init does not carry the slideshow screen, or its default is not Automatic');
assert.strictEqual(at('apply', 0), 'apply {"slideshowscreen":"C"} -> registry slideshowScreen=C', 'settings:apply does not store the chosen screen');
assert.strictEqual(JSON.parse(at('settings:init', 1).slice(14)).slideshowscreen, 'C', 'settings:init does not show the stored screen');
assert.strictEqual(at('slideshow', 1), 'slideshow reporter screen=C geometry=2720,0 1280x1024', 'presenter mode: the slideshow is not on the chosen screen');
assert.strictEqual(at('slideshow', 2), 'slideshow normal screen=C geometry=2720,0 1280x1024', 'normal mode: the slideshow is not on the chosen screen');
assert.strictEqual(JSON.parse(at('settings:init', 2).slice(14)).slideshowscreen, 'GONE', 'a stored screen that is not connected is not shown as stored');
assert.strictEqual(at('slideshow', 3), automatic, 'a screen that is not connected does not fall back to the automatic choice');
assert.strictEqual(at('apply', 2), 'apply {"slideshowscreen":"auto"} -> registry slideshowScreen=(unset)', 'Automatic does not remove the stored screen');
assert.strictEqual(JSON.parse(at('settings:init', 3).slice(14)).slideshowscreen, 'auto', 'settings:init after Automatic is not "auto"');
assert.strictEqual(at('slideshow', 4), automatic, 'Automatic does not give back the automatic presenter-mode choice');
assert.strictEqual(at('slideshow', 5), 'slideshow normal screen=B geometry=800,0 1920x1080', 'Automatic changed the old normal-mode choice');

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
const store = {};
const localStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } };
const names = ['$', 'sdk', 'localStorage', '$userName', '$chOpenMode', '$optsLang', 'appSettings', '$btnApply',
	'$panel', '_validate_user_name', '_lock_createnew', '$optsSlideshowScreen'];
// other selects/switches are not set here (undefined), as when hidden
const extras = [...new Set(applySrc.match(/\$(?:opts|ch)\w+/g))].filter((n) => !names.includes(n));
sent.length = 0;
new Function(...names, ...extras, applySrc + '\nreturn _on_btn_apply;')(
	$, sdk, localStorage, field('Ann'), { prop: () => false }, hidden, { slideshowscreen: 'auto' },
	{ disable: () => {} }, {}, () => true, () => {}, select('C'))({});
assert.strictEqual(sent.length, 1, 'stub harness broken: settings:apply not sent');
console.log('settings:apply', JSON.stringify(sent[0][1]));
assert.ok(/id="opts-slideshow-screen"/.test(ps) && /appSettings\.slideshowscreen/.test(initSrc) && /appSettings\.screens/.test(initSrc),
	'the start page has no "Slideshow screen" setting');
assert.strictEqual(sent[0][1].slideshowscreen, 'C', 'settings:apply does not carry the slideshow screen to the app');
assert.ok(!sent[0][1].restart, 'the slideshow screen must not ask for a restart (it is read when a slideshow starts)');

console.log('PASS #1548: "Slideshow screen" puts the slideshow on the chosen screen; Automatic keeps the old choice');
