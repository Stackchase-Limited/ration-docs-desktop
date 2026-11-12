/*
 * #2436 - "Add a file-type color indicator to document tabs": a subtle bar
 * across the top of each tab in the colour of its document type (blue text,
 * green spreadsheet, orange presentation, red PDF), because the small type
 * icon is hard to tell apart at a glance.
 *
 * In our tree the tabs already carry a per-type "active" colour, but only the
 * selected tab is filled with it, and in the default themes (theme-white,
 * theme-dark ...) the brand-word/cell/slide/pdf colours are all the same grey,
 * so nothing distinguishes the types.
 *
 * Fix (desktop-apps), as an option (Settings > "Colour tabs by document type",
 * user setting tab-type-colors, off by default):
 *  - win-linux: asctabwidget.cpp tabTypeColor() maps the editor type to a fixed
 *    colour (#3f7ec5 document, #3a8a56 spreadsheet, #e0823a presentation,
 *    #d04545 PDF/form, #6e5bbf diagram), set on the tab (CTabBar::setTabTypeColor)
 *    when it is created and when its type becomes known; Tab::paintEvent
 *    (ctabbar.cpp) draws it as a strip across the top when the bar's
 *    "typecolors" property is on (CTabBar::setTypeColorsVisible: at start and on
 *    settings:apply);
 *  - macOS: +[ASCTabView colorForType:] (same colours) set as the cell's
 *    typeColor in setType:; -[ASCTabViewCell drawWithFrame:inView:] draws the
 *    strip when +[ASCTabView showTypeColors] (set at start and on apply).
 *
 * This test
 *  1. compiles the real tabTypeColor() and the real Tab::paintEvent against
 *     small Qt stand-ins that record what is filled: with the option on, every
 *     tab type gets a top strip of its own distinct colour, selected or not;
 *     with it off, or for a start/portal tab, no strip (baseline: no such code
 *     -> FAILS);
 *  2. compiles the real +colorForType: and the strip block of
 *     -drawWithFrame:inView: into a stub cell (AppKit, ARC), draws a tab into a
 *     bitmap and reads the top and middle pixels back;
 *  3. loads the real panelsettings.js into jsdom: the switch is shown from
 *     settings:init and Apply sends tabtypecolors.
 *
 * NOT claimed: the final look in the real tab bars (GUI check on both
 * platforms; strip height is height/12 on win-linux, 3 pt on macOS); Windows
 * not compiled here (Linux syntax-only and macOS -fsyntax-only were).
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
const BASE_REF = process.env.BASE_REF || 'c2acc77f5^';
const NODE_MODULES = process.env.RD_NODE_MODULES || '/Users/osindero/dev/active/node_modules';

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
function extract(text, marker) {
	const at = text.indexOf(marker);
	return at === -1 ? null : block(text, at);
}

const TYPES = ['etDocument', 'etSpreadsheet', 'etPresentation', 'etPdf', 'etDocumentMasterForm', 'etDraw', 'etPortal'];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue2436-'));
let winOut = '', macOut = '';
try {
	/* ---- 1. win-linux ---- */
	const tw = src('win-linux/src/components/asctabwidget.cpp');
	const tb = src('win-linux/src/components/ctabbar.cpp');
	const colorFn = extract(tw, 'static QString tabTypeColor(');
	const paint = extract(tb, 'void Tab::paintEvent(QPaintEvent *ev)');
	assert.ok(paint, 'Tab::paintEvent not found - test is stale');
	const cpp = `
#include <string>
#include <vector>
#include <map>
#include <cstdio>
struct QString : std::string {
	QString() {} QString(const char *s) : std::string(s) {} QString(const std::string &s) : std::string(s) {}
	bool isEmpty() const { return empty(); }
};
struct QVariant { bool b = false; bool toBool() const { return b; } };
struct QObjectish {
	std::map<std::string, bool> props;
	QVariant property(const char *n) const { auto it = props.find(n); return QVariant{it != props.end() && it->second}; }
	void setProperty(const char *n, bool v) { props[n] = v; }
};
struct QColor { std::string c; QColor(const QString &s) : c(s) {} };
struct QBrush { QColor c; QBrush(QColor c) : c(c) {} };
struct QRect { int x, y, w, h; QRect(int x, int y, int w, int h) : x(x), y(y), w(w), h(h) {}
	QRect adjusted(int a, int b, int c, int d) const { return QRect(x + a, y + b, w - a + c, h - b + d); } };
struct Fill { QRect r; std::string color; };
static std::vector<Fill> fills;
struct QPainter { QPainter(void *) {}
	void fillRect(const QRect &r, const QColor &c) { fills.push_back({r, c.c}); }
	void fillRect(const QRect &r, const QBrush &b) { fills.push_back({r, b.c.c}); } };
typedef QPainter QStylePainter;
struct QPaintEvent {};
struct QFrame : QObjectish { int w = 200, h = 36;
	int width() const { return w; } int height() const { return h; }
	QRect rect() const { return QRect(0, 0, w, h); } int frameWidth() const { return 1; }
	void paintEvent(QPaintEvent *) { fills.push_back({rect(), "theme"}); } };
struct CTabBar : QObjectish {};
struct AscAppManager { static bool isRtlEnabled() { return false; } };
static int qRound(double d) { return int(d + 0.5); }
template <class T> static T qMax(T a, T b) { return a < b ? b : a; }
enum AscEditorType { etUndefined, ${TYPES.join(', ')} };
struct Tab : QFrame { QString tabcolor{"none"}, typecolor; CTabBar *tabBar = nullptr; bool is_active = false; void paintEvent(QPaintEvent *); };
${colorFn || 'static QString tabTypeColor(AscEditorType) { return QString(); }'}
${paint}
int main() {
	const char *names[] = { ${TYPES.map(t => JSON.stringify(t)).join(', ')} };
	AscEditorType types[] = { ${TYPES.join(', ')} };
	CTabBar bar;
	for (int on = 0; on < 2; on++) {
		bar.setProperty("typecolors", on == 1);
		for (int i = 0; i < ${TYPES.length}; i++) for (int sel = 0; sel < 2; sel++) {
			Tab t; t.tabBar = &bar; t.typecolor = tabTypeColor(types[i]);
			t.tabcolor = "#f3f3f3"; t.setProperty("selected", sel == 1);
			fills.clear();
			QPaintEvent e; t.paintEvent(&e);
			std::string strip = "-";
			for (auto &f : fills) if (f.r.y == 0 && f.r.h < t.height() / 4 && f.r.w == t.width()) strip = f.color + "/" + std::to_string(f.r.h);
			printf("%s %s %s strip=%s\\n", on ? "on" : "off", names[i], sel ? "selected" : "normal", strip.c_str());
		}
	}
}`;
	fs.writeFileSync(path.join(tmp, 'tab.cpp'), cpp);
	execFileSync('clang++', ['-std=c++14', '-w', '-o', path.join(tmp, 'tab'), path.join(tmp, 'tab.cpp')], { stdio: 'inherit' });
	winOut = execFileSync(path.join(tmp, 'tab'), { encoding: 'utf8' }).trim();

	/* ---- 2. macOS ---- */
	const tv = src('macos/ONLYOFFICE/Code/Controls/ASCTabs/ASCTabView.m');
	const tc = src('macos/ONLYOFFICE/Code/Controls/ASCTabs/ASCTabViewCell.m');
	const macColor = extract(tv, '+ (NSColor *)colorForType:(ASCTabViewType)type {');
	const stripAt = tc.indexOf('if (self.typeColor && [ASCTabView showTypeColors]) {');
	const strip = stripAt === -1 ? '' : block(tc, stripAt);
	const m = `
#import <Cocoa/Cocoa.h>
#import "ASCTabViewType.h"
#import "NSColor+Extensions.h"
static BOOL s_show = NO;
@interface ASCTabView : NSObject
+ (NSColor *)colorForType:(ASCTabViewType)type;
+ (BOOL)showTypeColors;
@end
@implementation ASCTabView
+ (BOOL)showTypeColors { return s_show; }
${macColor || '+ (NSColor *)colorForType:(ASCTabViewType)type { return nil; }'}
@end
@interface Cell : NSObject
@property (nonatomic) NSColor *typeColor;
- (void)drawWithFrame:(NSRect)cellFrame inView:(NSView *)controlView;
@end
@implementation Cell
- (void)drawWithFrame:(NSRect)cellFrame inView:(NSView *)controlView {
	NSRect rectangleRect = cellFrame;
	[[NSColor colorWithWhite:0.95 alpha:1] setFill];
	NSRectFill(rectangleRect);
	${strip}
}
@end
@interface FlippedView : NSView @end
@implementation FlippedView - (BOOL)isFlipped { return YES; } @end
int main() {
	@autoreleasepool {
		ASCTabViewType types[] = { ASCTabViewTypeDocument, ASCTabViewTypeSpreadsheet, ASCTabViewTypePresentation, ASCTabViewTypePdf, ASCTabViewTypeDraw, ASCTabViewTypePortal };
		const char *names[] = { "document", "spreadsheet", "presentation", "pdf", "draw", "portal" };
		FlippedView *v = [[FlippedView alloc] initWithFrame:NSMakeRect(0, 0, 120, 30)];
		for (int on = 0; on < 2; on++) {
			s_show = on;
			for (int i = 0; i < 6; i++) {
				NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:120 pixelsHigh:30
					bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
				NSGraphicsContext *ctx = [NSGraphicsContext graphicsContextWithBitmapImageRep:rep];
				ctx = [NSGraphicsContext graphicsContextWithCGContext:ctx.CGContext flipped:YES];
				CGContextTranslateCTM(ctx.CGContext, 0, 30); CGContextScaleCTM(ctx.CGContext, 1, -1);
				[NSGraphicsContext saveGraphicsState];
				[NSGraphicsContext setCurrentContext:ctx];
				Cell *c = [Cell new];
				c.typeColor = [ASCTabView colorForType:types[i]];
				[c drawWithFrame:NSMakeRect(0, 0, 120, 30) inView:v];
				[NSGraphicsContext restoreGraphicsState];
				NSColor *top = [[rep colorAtX:60 y:1] colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
				NSColor *mid = [[rep colorAtX:60 y:15] colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
				printf("%s %s top=%02x%02x%02x mid=%02x%02x%02x\\n", on ? "on" : "off", names[i],
					(int)lround(top.redComponent * 255), (int)lround(top.greenComponent * 255), (int)lround(top.blueComponent * 255),
					(int)lround(mid.redComponent * 255), (int)lround(mid.greenComponent * 255), (int)lround(mid.blueComponent * 255));
			}
		}
	}
}`;
	fs.writeFileSync(path.join(tmp, 'cell.m'), m);
	const code = path.join(APPS, 'macos/ONLYOFFICE/Code');
	execFileSync('clang', ['-fobjc-arc', '-w', '-I', path.join(code, 'Enums'), '-I', path.join(code, 'Extensions'),
		'-framework', 'Cocoa', '-o', path.join(tmp, 'cell'), path.join(tmp, 'cell.m')], { stdio: 'inherit' });
	macOut = execFileSync(path.join(tmp, 'cell'), { encoding: 'utf8' }).trim();
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}

console.log(winOut.split('\n').map(l => 'win-linux ' + l).join('\n'));
console.log(macOut.split('\n').map(l => 'macOS ' + l).join('\n'));

const winLines = winOut.split('\n');
const offStrips = winLines.filter(l => l.startsWith('off ') && !/strip=-$/.test(l));
assert.strictEqual(offStrips.length, 0, 'win-linux draws a strip with the option off');
const onDocs = winLines.filter(l => l.startsWith('on ') && !/etPortal/.test(l));
const winColors = new Set();
for (const l of onDocs) {
	const mm = /strip=(#[0-9a-f]{6})\/(\d+)$/.exec(l);
	assert.ok(mm, `win-linux: no type strip on "${l.replace(/ strip=.*/, '')}" with the option on`);
	winColors.add(l.split(' ')[1] + mm[1]);
}
assert.ok(winLines.filter(l => /^on etPortal/.test(l)).every(l => /strip=-$/.test(l)), 'win-linux: a portal tab got a type strip');
const byType = {};
for (const c of winColors) { const [t, col] = [c.replace(/#.*/, ''), c.replace(/^[^#]*/, '')]; byType[t] = col; }
assert.ok(new Set([byType.etDocument, byType.etSpreadsheet, byType.etPresentation, byType.etPdf, byType.etDraw]).size === 5,
	'win-linux: document types do not get distinct strip colours');

const macLines = macOut.split('\n');
assert.ok(macLines.filter(l => l.startsWith('off ')).every(l => /top=f2f2f2/.test(l)), 'macOS draws a strip with the option off');
const macTop = {};
for (const l of macLines.filter(l => l.startsWith('on '))) {
	const [, , name, top, mid] = /^(on) (\w+) top=(\w+) mid=(\w+)$/.exec(l);
	assert.strictEqual(mid, 'f2f2f2', `macOS: the ${name} strip covers the tab`);
	if (name === 'portal') assert.strictEqual(top, 'f2f2f2', 'macOS: a portal tab got a type strip');
	else { assert.notStrictEqual(top, 'f2f2f2', `macOS: no type strip on a ${name} tab with the option on`); macTop[name] = top; }
}
assert.strictEqual(new Set(Object.values(macTop)).size, 5, 'macOS: document types do not get distinct strip colours');
assert.strictEqual(macTop.document, byType.etDocument.slice(1), 'macOS and win-linux use different colours for documents');

/* ---- 3. the setting ---- */
const { JSDOM } = require(path.join(NODE_MODULES, 'jsdom'));
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
	utils.Lang = l10n.en; window.RendererProcessVariable = { theme: { id: 'theme-light', type: 'light' } };
	var _native = [], _sent = [];
	window.sdk = { on: function (ev, fn) { ev === 'on_native_message' && _native.push(fn); },
		command: function (c, p) { _sent.push([c, p]); }, GetLocalFeatures: function () { return false; } };
`);
run(src(L + 'src/panelsettings.js'));
run('(new ControllerSettings).init();');
w.eval('_native').forEach(fn => fn('settings:init', JSON.stringify({ keeprecents: true, tabtypecolors: false })));
const $sw = w.$('#sett-tab-type-colors');
assert.ok($sw.length && $sw.closest('.settings-field').css('display') !== 'none', 'Settings has no switch for tab type colours');
console.log(`switch "${w.$('label[for=sett-tab-type-colors]').text().trim()}" shown, checked=${$sw.prop('checked')}`);
$sw.prop('checked', true).trigger('change');
w.$('.sett-btn--apply').first().trigger('click');
const applied = w.eval('_sent').filter(c => c[0] === 'settings:apply').map(c => JSON.parse(c[1]));
console.log('settings:apply', JSON.stringify(applied[applied.length - 1]));
assert.ok(applied.length && applied[applied.length - 1].tabtypecolors === true, 'Apply does not hand the option to the app');

console.log('PASS #2436: with the option on, every document tab shows a strip in its type\'s colour (win-linux and macOS)');
