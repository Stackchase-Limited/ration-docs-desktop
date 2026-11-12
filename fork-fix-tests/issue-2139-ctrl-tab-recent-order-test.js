/*
 * #2139 - "Ctrl+Tab to navigate between the most recent files": the reporter
 * asks for a setting that makes Ctrl+Tab go to the most recently used tab, as
 * in Firefox, instead of the next one in the tab bar.
 *
 * Today (unchanged by default): win-linux CMainWindow::onKeyDown (VK_TAB) and
 * macOS AppDelegate (keyCode 9 -> ASCTabsControl selectNextTab /
 * selectPreviouseTab) walk the tab bar left to right, the start page counting
 * as the position before the first tab.
 *
 * Fix (desktop-apps): Settings > "Ctrl+Tab goes to the most recently used tab"
 * (user setting tab-switch-mru, off by default; settings:init/apply on both
 * platforms). When on, Ctrl+Tab steps through the start page and the tabs in
 * most-recently-used order: win-linux CTabMruOrder in windows/cmainwindow.cpp
 * (touched from onTabChanged), macOS -[ASCTabsControl selectRecentTab:]
 * (touched from selectTab:). While Ctrl is held the order is frozen, so each
 * further Tab goes one further back (Shift+Tab goes the other way); when Ctrl
 * is let go - watched with a 50 ms timer, the key release goes to the page -
 * the tab reached becomes the most recent.
 *
 * This test
 *  1. compiles the real CTabMruOrder (brace-extracted from cmainwindow.cpp) and
 *  2. compiles the real touchRecentTab / selectRecentTab: / finishRecentCycle
 *     methods of ASCTabsControl.m into a stub class (Foundation/AppKit, ARC),
 *     and drives both through the same session: open A, B, C (C current);
 *     Ctrl+Tab, release -> B; Ctrl+Tab, release -> C (back and forth);
 *     Ctrl+Tab+Tab, release -> A (two back); then Ctrl+Shift+Tab walks the
 *     other way; a tab closed is skipped. Baseline: no such code -> FAILS.
 *  3. loads the real panelsettings.js into jsdom: settings:init with
 *     tabswitchmru shows the switch; ticking it and Apply sends
 *     tabswitchmru: true in settings:apply.
 *
 * NOT claimed: the key routing in onKeyDown/AppDelegate and the Ctrl-release
 * timer (compiled - Linux syntax-only, macOS clang -fsyntax-only - but need a
 * GUI check); Windows not compiled here.
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
const BASE_REF = process.env.BASE_REF || '52e500360^';
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
function extract(text, marker, what) {
	const at = text.indexOf(marker);
	if (at === -1) {
		console.log(`${what}: not found - Ctrl+Tab has no most-recently-used order`);
		return null;
	}
	return block(text, at);
}

// One session, as key presses: 'open X' selects a new tab X, 'tab'/'stab' is
// Ctrl+Tab / Ctrl+Shift+Tab with Ctrl held, 'up' lets Ctrl go, 'close X'.
const SESSION = ['open A', 'open B', 'open C',
	'tab', 'up', 'tab', 'up', 'tab', 'tab', 'up', 'stab', 'up', 'close B', 'tab', 'up'];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue2139-'));
const results = {};
try {
	/* ---- 1. win-linux ---- */
	const cw = src('win-linux/src/windows/cmainwindow.cpp');
	const mru = extract(cw, 'struct CTabMruOrder', 'win-linux CTabMruOrder');
	if (mru) {
		const cpp = `
#include <vector>
#include <algorithm>
#include <string>
#include <cstdio>
#include <map>
${mru};
int main() {
	CTabMruOrder m;
	std::vector<int> open{-1};      // start page always there
	std::map<int, char> name{{-1, 'h'}};
	int cur = -1, next = 1;
	m.touch(-1);
	auto show = [&](int id){ cur = id; m.touch(id); };
	const char *steps[] = { ${SESSION.map(s => JSON.stringify(s)).join(', ')} };
	std::string out;
	for (auto s : steps) {
		std::string st(s);
		if (st.rfind("open ", 0) == 0) { int id = next++; name[id] = st[5]; open.push_back(id); show(id); }
		else if (st.rfind("close ", 0) == 0) {
			for (auto it = open.begin(); it != open.end(); ++it) if (name[*it] == st[6]) { open.erase(it); break; }
		}
		else if (st == "tab" || st == "stab") { show(m.step(st == "stab", open)); }
		else if (st == "up") { m.finish(); out += (name[cur] == 'h' ? std::string("home") : std::string(1, name[cur])) + " "; }
	}
	printf("%s\\n", out.c_str());
}`;
		fs.writeFileSync(path.join(tmp, 'mru.cpp'), cpp);
		execFileSync('clang++', ['-std=c++14', '-w', '-o', path.join(tmp, 'mru'), path.join(tmp, 'mru.cpp')], { stdio: 'inherit' });
		results.winlinux = execFileSync(path.join(tmp, 'mru'), { encoding: 'utf8' }).trim();
	}

	/* ---- 2. macOS ---- */
	const tc = src('macos/ONLYOFFICE/Code/Controls/ASCTabs/ASCTabsControl.m');
	const touch = extract(tc, '- (void)touchRecentTab:(ASCTabView *)tab {', 'macOS touchRecentTab');
	const select = extract(tc, '- (void)selectRecentTab:(BOOL)back {', 'macOS selectRecentTab:');
	const finish = extract(tc, '- (void)finishRecentCycle {', 'macOS finishRecentCycle');
	const selectTab = extract(tc, '- (void)selectTab:(ASCTabView *)selectedTab {', 'selectTab:');
	if (touch && select && finish) {
		assert.ok(/\[self touchRecentTab:selectedTab\]/.test(selectTab), 'selectTab: does not record the selected tab');
		const m = `
#import <Cocoa/Cocoa.h>
@interface ASCTabView : NSObject
@property (nonatomic) NSString *uuid;
@end
@implementation ASCTabView
@end
@interface ASCTabsControl : NSObject
@property (nonatomic) NSMutableArray *tabs;
@property (nonatomic) NSMutableArray<NSString *> *recentOrder;
@property (nonatomic) NSArray<NSString *> *recentCycle;
@property (nonatomic) NSUInteger recentPos;
@property (nonatomic) NSTimer *recentCtrlWatch;
@property (nonatomic) ASCTabView *current;
@end
@implementation ASCTabsControl
- (ASCTabView *)tabWithUUID:(NSString *)uuid {
	for (ASCTabView *t in self.tabs) if ([t.uuid isEqualToString:uuid]) return t;
	return nil;
}
// selectTab: as in the app, minus drawing: record, then show
- (void)selectTab:(ASCTabView *)selectedTab { [self touchRecentTab:selectedTab]; self.current = selectedTab; }
${touch}
${select}
${finish}
@end
int main() {
	@autoreleasepool {
		ASCTabsControl *c = [ASCTabsControl new];
		c.tabs = [NSMutableArray array];
		[c selectTab:nil];
		NSArray *steps = @[ ${SESSION.map(s => '@' + JSON.stringify(s)).join(', ')} ];
		NSMutableString *out = [NSMutableString string];
		for (NSString *s in steps) {
			if ([s hasPrefix:@"open "]) { ASCTabView *t = [ASCTabView new]; t.uuid = [s substringFromIndex:5]; [c.tabs addObject:t]; [c selectTab:t]; }
			else if ([s hasPrefix:@"close "]) { [c.tabs removeObject:[c tabWithUUID:[s substringFromIndex:6]]]; }
			else if ([s isEqualToString:@"tab"] || [s isEqualToString:@"stab"]) { [c selectRecentTab:[s isEqualToString:@"stab"]]; }
			else if ([s isEqualToString:@"up"]) {
				[c.recentCtrlWatch invalidate];   // the timer would see Ctrl up and call this
				[c finishRecentCycle];
				[out appendFormat:@"%@ ", c.current ? c.current.uuid : @"home"];
			}
		}
		printf("%s\\n", [[out stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]] UTF8String]);
	}
}`;
		fs.writeFileSync(path.join(tmp, 'mru.m'), m);
		execFileSync('clang', ['-fobjc-arc', '-w', '-framework', 'Cocoa', '-o', path.join(tmp, 'mrum'), path.join(tmp, 'mru.m')], { stdio: 'inherit' });
		results.macos = execFileSync(path.join(tmp, 'mrum'), { encoding: 'utf8' }).trim();
	}
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}

/*
 * Expected, step by step (order most recent first; h = start page):
 *  open A,B,C          C B A h
 *  tab -> B, up        B C A h
 *  tab -> C, up        C B A h   (Ctrl+Tab flips between the last two)
 *  tab -> B, tab -> A, up   A C B h
 *  stab -> h (backwards from A wraps to the oldest), up   h A C B
 *  close B; tab -> A, up    A h C
 */
const expected = 'B C A home A';
console.log(`session: ${SESSION.join(', ')}`);
console.log(`win-linux: ${results.winlinux || '(none)'}`);
console.log(`macOS:     ${results.macos || '(none)'}`);
console.log(`expected:  ${expected}`);
assert.strictEqual(results.winlinux, expected, 'win-linux Ctrl+Tab does not follow the most-recently-used order');
assert.strictEqual(results.macos, expected, 'macOS Ctrl+Tab does not follow the most-recently-used order');

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
w.eval('_native').forEach(fn => fn('settings:init', JSON.stringify({ keeprecents: true, tabswitchmru: false })));
const $sw = w.$('#sett-tab-mru');
assert.ok($sw.length && $sw.closest('.settings-field').css('display') !== 'none', 'Settings has no Ctrl+Tab order switch');
console.log(`switch "${w.$('label[for=sett-tab-mru]').text().trim()}" shown, checked=${$sw.prop('checked')}`);
$sw.prop('checked', true).trigger('change');
w.$('.sett-btn--apply').first().trigger('click');
const applied = w.eval('_sent').filter(c => c[0] === 'settings:apply').map(c => JSON.parse(c[1]));
console.log('settings:apply', JSON.stringify(applied[applied.length - 1]));
assert.ok(applied.length && applied[applied.length - 1].tabswitchmru === true, 'Apply does not hand the Ctrl+Tab order to the app');

console.log('PASS #2139: with the setting on, Ctrl+Tab goes through tabs in most-recently-used order (win-linux and macOS)');
