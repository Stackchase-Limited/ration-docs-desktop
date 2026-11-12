/*
 * #1292 - the editors' context menus had no keyboard accelerators: after the
 * Menu key (or a right click) only the arrow keys moved through the items;
 * letters did nothing ("select a row, Menu key, then Down five times for
 * Delete").
 *
 * Cause (web-apps): Common.UI.Menu only knew arrows, Enter and Esc; its
 * type-ahead "search" option is off for context menus, and the
 * keydown.after.bs.dropdown event that extend/Bootstrap.js re-triggers for
 * the menu carried keyCode only - no key, no modifiers.
 *
 * Fix: Bootstrap.js passes ctrlKey/altKey/metaKey and the typed key
 * (typedKey); Menu.onMnemonicKey, inside a menu marked "menu-mnemonics" (the
 * DocumentHolder controllers of the document, spreadsheet, presentation, PDF
 * and diagram editors mark their context menus), picks the visible, enabled
 * item whose caption starts with the letter: the only one is chosen (a
 * submenu opens like with the Right key), several are focused in turn.
 *
 * This loads the REAL jQuery, underscore, Backbone (web-apps vendor), the REAL
 * mods/dropdown.js, extend/Bootstrap.js, BaseView, ToggleManager, MenuItem and
 * Menu into headless Chromium (Playwright) with small stubs for Common.Utils /
 * NotificationCenter / localStorage, builds a spreadsheet-like context menu
 * (Cut, Copy, Paste, Insert >, Delete > [Shift cells up, Entire row],
 * Clear, Sort, Filter, Comment, disabled "Data", hidden "Define name"), renders
 * it the way the DocumentHolder controllers do (menu-container, tabindex,
 * the class from the REAL controller line), opens it and presses real keys.
 * It also checks by text that every DocumentHolder controller marks its menu.
 *
 * NOT claimed: the real editors' menus as drawn and every caption - needs a
 * GUI check; Scroller (maxHeight menus) is stubbed.
 *
 * RD_REPO overrides the web-apps checkout (default ../web-apps). BASELINE=1
 * reads the parent of the fix commit (BASE_REF), where it must fail.
 * PLAYWRIGHT / RD_CHROME as in issue-1664-store-html-test.js.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '9e2a4c5e94^';
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}

let failed = 0;
function check(what, fn) {
	try { fn(); console.log('ok   ' + what); }
	catch (e) { failed++; console.log('FAIL ' + what + ': ' + e.message); }
}

const CONTROLLERS = ['documenteditor', 'spreadsheeteditor', 'presentationeditor', 'pdfeditor', 'visioeditor']
	.map(a => `apps/${a}/main/app/controller/DocumentHolder.js`);

/* the line(s) right after the controllers' tabindex line, as written in the spreadsheet editor */
const sse = read(CONTROLLERS[1]);
const at = sse.indexOf('menu.cmpEl.attr({tabindex: "-1"});');
assert.ok(at > 0, 'tabindex line not found in the spreadsheet DocumentHolder');
const markLine = /^\s*menu\.cmpEl\.addClass\([^)]*\);/.exec(sse.slice(sse.indexOf('\n', at) + 1));
const markCode = markLine ? markLine[0].trim() : '';

const STUBS = `
window.define = function(deps, fn) { return fn(window.Backbone); };
window.Common = { UI: {}, Utils: {}, Controllers: {}, Views: {} };
// web-apps adds show/hide to views elsewhere (setVisible calls them)
Backbone.View.prototype.show = function(){ this.$el.show(); };
Backbone.View.prototype.hide = function(){ this.$el.hide(); };
Common.NotificationCenter = _.extend({}, Backbone.Events);
Common.localStorage = { getItem: function(){ return null; }, setItem: function(){}, getKeysFilter: function(){ return ''; } };
Common.UI.isRTL = function(){ return false; };
Common.UI.HintManager = { isHintVisible: function(){ return false; }, clearHints: function(){} };
Common.UI.Scaling = { currentRatio: function(){ return 1; } };
Common.UI.Scroller = function(){ this.update = function(){}; this.scrollTop = function(){ return 0; }; };
Common.UI.Scroller.isMouseCapture = function(){ return false; };
Common.UI.getSuitableIcons = function(){ return []; };
Common.UI.iconsStr = '';
Common.Utils.getPosition = function(el){ var o = $(el).position() || {left:0,top:0}; return {left:o.left, top:o.top}; };
Common.Utils.getOffset = function(el){ return $(el).offset() || {left:0,top:0}; };
Common.Utils.setOffset = function(el, o){ $(el).offset(o); };
Common.Utils.innerWidth = function(){ return window.innerWidth; };
Common.Utils.innerHeight = function(){ return window.innerHeight; };
Common.Utils.croppedGeometry = function(){ return {left:0, top:0, width:window.innerWidth, height:window.innerHeight}; };
Common.Utils.getBoundingClientRect = function(el){ return el.getBoundingClientRect(); };
Common.Utils.isIE = false;
`;

(async () => {
	for (const c of CONTROLLERS)
		check(`${c.split('/')[1]} marks its context menu`, () =>
			assert.ok(/menu\.cmpEl\.attr\(\{tabindex: "-1"\}\);\s*\n\s*menu\.cmpEl\.addClass\('menu-mnemonics'\)/.test(read(c))));

	const { chromium } = require(PLAYWRIGHT);
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	try {
		const page = await browser.newPage();
		const errors = [];
		page.on('pageerror', e => errors.push(e.message));
		await page.setContent('<!doctype html><html><body><div id="holder" style="position:relative;width:800px;height:600px"></div></body></html>');
		const vendor = rel => fs.readFileSync(path.join(REPO, rel), 'utf8');
		await page.addScriptTag({ content: vendor('vendor/jquery/jquery.js') });
		await page.addScriptTag({ content: vendor('vendor/underscore/underscore.js') });
		await page.addScriptTag({ content: vendor('vendor/backbone/backbone.js') });
		await page.addScriptTag({ content: STUBS });
		for (const rel of ['apps/common/main/lib/mods/dropdown.js', 'apps/common/main/lib/extend/Bootstrap.js',
			'apps/common/main/lib/component/BaseView.js', 'apps/common/main/lib/component/ToggleManager.js',
			'apps/common/main/lib/component/MenuItem.js', 'apps/common/main/lib/component/Menu.js'])
			await page.addScriptTag({ content: read(rel) });

		const built = await page.evaluate((markCode) => {
			window.__clicked = [];
			var item = function(caption, extra) {
				var it = new Common.UI.MenuItem(_.extend({ caption: caption }, extra || {}));
				it.on('click', function() { __clicked.push(caption); });
				return it;
			};
			var sub = new Common.UI.Menu({ menuAlign: 'tl-tr', items: [item('Shift cells up'), item('Entire row')] });
			var defName = item('Define name', { visible: false });
			var menu = new Common.UI.Menu({ items: [
				item('Cut'), item('Copy'), item('Paste'), { caption: '--' },
				item('Insert', { menu: new Common.UI.Menu({ menuAlign: 'tl-tr', items: [item('Shift cells down')] }) }),
				item('Delete', { menu: sub }), item('Clear'), { caption: '--' },
				item('Sort'), item('Filter'), item('Comment'), item('Data', { disabled: true }), defName
			] });
			window.__menu = menu; window.__sub = sub;
			// as showPopupMenu does
			var menuContainer = $('<div id="menu-container-' + menu.id + '" style="position: absolute; z-index: 10000;"><div class="dropdown-toggle" data-toggle="dropdown"></div></div>');
			$('#holder').append(menuContainer);
			menu.render(menuContainer);
			menu.cmpEl.attr({tabindex: "-1"});
			if (markCode) eval(markCode);
			menuContainer.css({ left: 100, top: 50 });
			menu.show();
			menu.cmpEl.focus();
			return { open: menuContainer.hasClass('open'), focused: document.activeElement === menu.cmpEl[0] };
		}, markCode);
		check('the harness opened the real menu and focused it', () => {
			assert.deepStrictEqual(errors, [], errors.join('; '));
			assert.ok(built.open && built.focused, JSON.stringify(built));
		});

		const state = () => page.evaluate(() => ({
			focused: $(document.activeElement).text().trim(),
			clicked: __clicked.slice(),
			open: $('#menu-container-' + __menu.id).hasClass('open'),
			subOpen: __sub.cmpEl.parent().hasClass('over'),
		}));
		const reopen = () => page.evaluate(() => {
			__clicked.length = 0;
			Common.UI.Menu.Manager.hideAll();
			__menu.show();
			__menu.cmpEl.focus();
		});

		/* unchanged on both trees: arrows still move */
		await page.keyboard.press('ArrowDown');
		const afterDown = await state();
		check('Down focuses "Cut"', () => assert.strictEqual(afterDown.focused, 'Cut'));

		await reopen();
		await page.keyboard.press('f');
		const f = await state();
		check('"f" chooses the only item starting with F (Filter) and closes the menu', () => {
			assert.deepStrictEqual(f.clicked, ['Filter']);
			assert.strictEqual(f.open, false);
		});

		await reopen();
		await page.keyboard.press('Shift+D');
		await page.waitForTimeout(400);
		const d = await state();
		check('"D" opens the Delete submenu and focuses its first item', () => {
			assert.deepStrictEqual(d.clicked, []);
			assert.ok(d.subOpen, 'submenu not open');
			assert.strictEqual(d.focused, 'Shift cells up');
		});
		await page.keyboard.press('e');
		const e = await state();
		check('"e" in the submenu chooses "Entire row"', () => assert.deepStrictEqual(e.clicked, ['Entire row']));

		await reopen();
		await page.keyboard.press('c');
		const c1 = await state();
		await page.keyboard.press('c');
		const c2 = await state();
		await page.keyboard.press('c');
		const c3 = await state();
		await page.keyboard.press('c');
		const c4 = await state();
		check('"c" with several matches (Cut, Copy, Clear, Comment) focuses them in turn, chooses none', () => {
			assert.deepStrictEqual([c1.focused, c2.focused, c3.focused, c4.focused], ['Cut', 'Copy', 'Clear', 'Comment']);
			assert.deepStrictEqual(c4.clicked, []);
		});
		await page.keyboard.press('Enter');
		const enter = await state();
		check('Enter then chooses the focused one', () => assert.deepStrictEqual(enter.clicked, ['Comment']));

		await reopen();
		await page.keyboard.press('Control+f');
		await page.keyboard.press('x');
		const mod = await state();
		check('Ctrl+F and a letter no visible enabled item starts with choose nothing', () => {
			assert.deepStrictEqual(mod.clicked, []);
			assert.strictEqual(mod.open, true);
		});
		await page.keyboard.press('Escape');
		await reopen();
		await page.keyboard.press('Shift+D');
		await page.waitForTimeout(400);
		await page.keyboard.press('ArrowLeft');
		await page.keyboard.press('d');
		await page.waitForTimeout(400);
		const dd = await state();
		check('a disabled item (Data) and a hidden one (Define name) are skipped: "d" still means Delete', () =>
			assert.strictEqual(dd.focused, 'Shift cells up'));
		await page.keyboard.press('Escape');
	} finally {
		await browser.close();
	}

	if (failed) {
		console.log(`${failed} check(s) FAILED`);
		process.exit(1);
	}
	console.log('PASS #1292 context menu letters');
})().catch(e => { console.log('FAIL ' + (e && e.stack || e)); process.exit(1); });
