/*
 * #1548 (follow-up found while fixing it): starting a slideshow with two or more
 * screens aborted the app when the editor window hung off the edge of the desktop.
 *
 * Cause: desktop-apps win-linux/src/utils.cpp WindowHelper::constructFullscreenWidget
 * looks up QApplication::screenAt(pt) for a point near the window's top-left corner
 * (pt is mapToGlobal(pos()), so it is even offset twice) and uses the result
 * unchecked. When that point is on no screen - a window dragged partly off the
 * left/top edge, or a corner in the gap between screens of different sizes -
 * presenter mode indexes the screen list with count - (-1) - 1 = count (QList::at
 * out of range: an assert abort, undefined behaviour in release builds) and normal
 * mode dereferences the null screen.
 * Fix: fall back to the window's own screen (its QWindow::screen), else the
 * primary screen.
 *
 * This test extracts the REAL constructFullscreenWidget and Utils::slideshowScreen
 * by brace matching, compiles them against Qt 5.15 in rd-linux-verify:24.04 with
 * stubbed app classes, and runs each case in its own process on the offscreen
 * platform with three REAL QScreens on one virtual desktop ("A" 800x600 primary at
 * x=0, "B" at x=800, "C" at x=2720), the document's panel at x=-900 (off the left
 * edge), in presenter and in normal mode.
 * Expected: the window counts as on its fallback screen A, so presenter mode puts
 * the slideshow on the mirrored screen C and normal mode on A.
 * Baseline: presenter mode aborts (exit 134, QList::at assert), normal mode
 * segfaults (exit 139) -> FAILS.
 *
 * NOT claimed: in the harness the panel is an unshown top-level widget, so the
 * fallback is the primary screen; in the app it is the editor window's screen.
 * Needs a GUI check with real monitors. Qt < 5.11 builds (the #if branch above it)
 * are not changed.
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
const BASE_REF = process.env.BASE_REF || 'f0ccf9f00^';
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

const steps = ['reporter@-900', 'normal@-900'];

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue-1548-slideshow-offscreen-window-crash-'));
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

const line = (m) => out.find((l) => l.startsWith(`slideshow ${m} `) || l.startsWith(`${m}@-900 exit=`));
// presenter mode: the window counts as on A (the fallback), the slideshow goes to the mirrored C
assert.strictEqual(line('reporter'), 'slideshow reporter screen=C geometry=2720,0 1280x1024',
	'presenter mode: a window off the edge of the desktop crashed the slideshow, or it is not on a screen');
assert.strictEqual(line('normal'), 'slideshow normal screen=A geometry=0,0 800x600',
	'normal mode: a window off the edge of the desktop crashed the slideshow, or it is not on a screen');
console.log('PASS #1548: a slideshow from a window off the edge of the desktop opens on a screen instead of crashing');
