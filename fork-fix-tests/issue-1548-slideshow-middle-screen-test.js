/*
 * #1548 (part of the report): with three screens and the presenter on the middle
 * one, the presenter-mode slideshow opened on the presenter's own screen, covering
 * the presenter view.
 *
 * Cause: desktop-apps win-linux/src/utils.cpp WindowHelper::constructFullscreenWidget
 * puts the presenter-mode slideshow on the screen at the mirrored index
 * count - index - 1 of Qt's screen list; for an odd count the middle screen
 * mirrors onto itself.
 * Fix: when the mirrored screen is the presenter's own, use the primary screen, or
 * the next screen in the list if the presenter is on the primary. Every other case
 * keeps the old choice. (The opt-in "Slideshow screen" setting overrides both.)
 *
 * This test extracts the REAL constructFullscreenWidget and Utils::slideshowScreen
 * by brace matching, compiles them against Qt 5.15 in rd-linux-verify:24.04 with
 * stubbed app classes, and runs them on the offscreen platform with three REAL
 * QScreens on one virtual desktop ("A" 800x600 primary at x=0, "B" 1920x1080 at
 * x=800, "C" 1280x1024 at x=2720): presenter mode from B (middle), from A and from
 * C, and normal mode from B, all on "Automatic".
 * Baseline: from B the slideshow lands on B -> FAILS.
 *
 * NOT claimed: the "next screen" branch (presenter on a primary screen that is the
 * middle one) is not exercised; the result with real monitors needs a GUI check.
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
const BASE_REF = process.env.BASE_REF || 'f5d2cebf6^';
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
		} else if (c.rfind("reporter", 0) == 0 || c.rfind("normal", 0) == 0) {
			size_t at = c.find('@');
			int x = at == std::string::npos ? 900 : std::stoi(c.substr(at + 1));
			c = c.substr(0, at);
			CTabPanel * panel = new CTabPanel;          // the document's panel, at x (900: screen B)
			panel->m_reporter = c == "reporter";
			panel->setGeometry(x, 100, 600, 400);
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

// the panel's point is mapToGlobal(pos()), i.e. 2*x: 200 is on A, 1800 on B, 2800 on C
const steps = ['reporter@100', 'reporter@900', 'reporter@1400', 'normal@900'];

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue-1548-slideshow-middle-screen-'));
let out;
try {
	fs.writeFileSync(path.join(tmp, 'main.cpp'), cpp);
	fs.writeFileSync(path.join(tmp, 'run.sh'), `set -e
cd /t
QTV=$(pkg-config --modversion Qt5Core)
QTGUI=$(pkg-config --variable=includedir Qt5Gui)/QtGui
g++ -std=c++17 -fPIC -w -o ss main.cpp $(pkg-config --cflags --libs Qt5Widgets) -I$QTGUI/$QTV -I$QTGUI/$QTV/QtGui
for s in ${steps.map((s) => `'${s}'`).join(' ')}; do
  HOME=/t/home QT_QPA_PLATFORM=offscreen timeout 60 ./ss "$s" 2>/dev/null || echo "$s exit=$?"
done
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

const at = (p) => out.find((l) => l.startsWith(p));
const shown = out.filter((l) => l.startsWith('slideshow reporter '));
assert.strictEqual(shown[0], 'slideshow reporter screen=C geometry=2720,0 1280x1024',
	'harness broken: from A (index 0 of 3) the slideshow should still go to C');
console.log('presenter from A, B, C:', shown.map((l) => /screen=(\w*)/.exec(l)[1]).join(', '));
assert.strictEqual(shown[1], 'slideshow reporter screen=A geometry=0,0 800x600',
	'presenter on the middle screen B: the slideshow is not on another screen (the primary, A)');
assert.strictEqual(shown[2], 'slideshow reporter screen=A geometry=0,0 800x600', 'from C the old choice (A) changed');
assert.strictEqual(at('slideshow normal '), 'slideshow normal screen=B geometry=800,0 1920x1080', 'normal mode changed');
console.log('PASS #1548: with three screens the presenter-mode slideshow no longer covers the presenter on the middle screen');
