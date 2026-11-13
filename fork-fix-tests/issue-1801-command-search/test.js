/*
 * DesktopEditors #1801 - command search ("Tell me", as in Microsoft 365): "a search button to search,
 * find all the features we need and click on them once we found it".
 *
 * Before: no way to find a command by name; the user had to look through every ribbon tab.
 * Now (web-apps, opt-in): File > Advanced settings > "Command search (Alt+/)" - stored as
 * <de|pe|sse>-settings-command-search, OFF by default (the shortcut then does nothing, as before).
 * With it on, Alt+/ (Ctrl+Option+/ on macOS; Alt+Q is the chat panel) opens a small box that
 * searches the ribbon's Common.UI.Button items and their menu items by caption and hint
 * (common/main/lib/view/CommandSearch.js; Common.UI.Button keeps itself in its element's data so
 * the ribbon can be read from the DOM, and the panel around a button names its tab). Results show
 * name and tab; Enter switches to the owning tab and clicks the button / opens its menu and clicks
 * the item, the way a mouse click (or an Alt key tip) does; disabled items are greyed and Enter does
 * nothing on them; Up/Down move, Esc closes and gives focus back.
 *
 * What runs: the REAL editors - web-apps source tree under test in dev mode (requirejs) with a built
 * sdkjs, in headless Chromium, opened like the desktop app does (api/documents/index.html.desktop ->
 * DocsAPI iframe, stubbed AscDesktopEditor, core's empty docx/xlsx/pptx templates). For each of the
 * document, spreadsheet and presentation editors:
 *   - setting off (default): the shortcut opens nothing;
 *   - the real Advanced settings panel has the checkbox (unchecked) and its Apply stores the setting;
 *   - the shortcut then opens the box with the focus in it;
 *   - a button found from another tab: Enter switches tab and the click lands in the document
 *     (DE: nonprinting characters shown; SSE: the cell becomes bold; PE: Add slide adds a slide);
 *   - a menu item on another tab: Enter switches to that tab, the button's menu fires item:click
 *     with that item, and the document changes (DE/SSE: landscape; PE: 4:3 slide size);
 *   - a disabled command is listed greyed (aria-disabled) and Enter leaves it alone;
 *   - Up/Down move the selection (wrapping); Esc closes and the focus is back where it was.
 *                                                             (BASELINE: no command search -> FAILS)
 * NOT claimed: the look of the box in the app (only headless Chromium; styles come from a web-apps
 * deploy's app.css because the less sources need generated sprites); macOS/Windows/Linux keyboard
 * layouts where "/" is not a key of its own; menus filled only when they open are not searched
 * until they have been opened once. pdf/visio editors have no command search.
 *
 * Env: RD_REPO          web-apps checkout (default ../../web-apps)
 *      RD_SDKJS         built sdkjs deploy/sdkjs (default ../../sdkjs/deploy/sdkjs; must be built from
 *                       the same branch - an older build lacks api methods the editors call)
 *      RD_WEBAPPS_DEPLOY a built web-apps deploy/web-apps for app.css + sprites (default ../../web-apps/deploy/web-apps)
 *      RD_CORE          core checkout for Common/empty/*.bin (default ../../core)
 *      RD_FONTS         fonts cache dir with AllFonts.js (default ../../../.rd-work/fonts-cache; only read)
 *      RD_PLAYWRIGHT, RD_CHROME, RD_TMP, RD_EDITORS=word,cell,slide
 *      BASELINE=1       web-apps from `git archive BASE_REF` (default the parent of the fix); must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openEditor } = require('./open');

const HERE = __dirname;
const REPO = path.resolve(process.env.RD_REPO || path.join(HERE, '..', '..', 'web-apps'));
const SDKJS = path.resolve(process.env.RD_SDKJS || path.join(HERE, '..', '..', 'sdkjs', 'deploy', 'sdkjs'));
const DEPLOY = path.resolve(process.env.RD_WEBAPPS_DEPLOY || path.join(REPO, 'deploy', 'web-apps'));
const CORE = path.resolve(process.env.RD_CORE || path.join(HERE, '..', '..', 'core'));
const FONTS = path.resolve(process.env.RD_FONTS || path.join(HERE, '..', '..', '..', '.rd-work', 'fonts-cache'));
const BASE_REF = process.env.BASE_REF || 'f069ce1f78^';
const EDITORS = (process.env.RD_EDITORS || 'word,cell,slide').split(',');

let failed = 0;
function check(name, ok, detail) {
	if (ok) console.log('ok   - ' + name);
	else { failed++; console.log('FAIL - ' + name + (detail !== undefined ? '\n       ' + JSON.stringify(detail) : '')); }
}

const cfg = {
	word: { ext: 'docx', p: 'de', G: 'DE',
		button: { query: 'nonprinting', start: 'view', tab: 'home', effect: 'api.get_ShowParaMarks() === true' },
		item: { query: 'landscape', tab: 'layout', btn: 'btnPageOrient', effect: 'api.get_DocumentOrientation() === false' },
		disabled: 'bring forward' },
	cell: { ext: 'xlsx', p: 'sse', G: 'SSE',
		button: { query: 'bold', start: 'view', tab: 'home', effect: 'api.asc_getCellInfo().asc_getXfs().asc_getFontBold() === true' },
		item: { query: 'landscape', tab: 'layout', btn: 'btnPageOrient',
			effect: 'api.asc_getPageOptions(api.asc_getActiveWorksheetIndex()).asc_getPageSetup().asc_getOrientation() === Asc.c_oAscPageOrientation.PageLandscape' },
		disabled: 'bring forward' },
	slide: { ext: 'pptx', p: 'pe', G: 'PE',
		button: { query: 'add slide', start: 'ins', tab: 'ins', static: true, effect: 'api.getCountPages() === window.__pages0 + 1' },
		item: { query: 'standard (4:3)', tab: 'design', btn: 'btnSlideSize',
			effect: 'Math.abs(api.get_PresentationWidth() / api.get_PresentationHeight() - 4 / 3) < 0.01' },
		disabled: 'bold' },
};

function prepareWebapps(tmp) {
	if (!process.env.BASELINE) return REPO;
	const dir = path.join(tmp, 'web-apps');
	fs.mkdirSync(dir);
	const tar = execFileSync('git', ['-C', REPO, 'archive', BASE_REF, 'apps', 'vendor'], { maxBuffer: 1 << 30 });
	execFileSync('tar', ['-x', '-C', dir], { input: tar, maxBuffer: 1 << 30 });
	return dir;
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function runEditor(doctype, webapps, tmp) {
	const c = cfg[doctype];
	const tag = doctype + ': ';
	const bin = path.join(CORE, 'Common', 'empty', c.ext + '.bin');
	const fontsCopy = path.join(tmp, 'AllFonts.js');
	if (!fs.existsSync(fontsCopy)) fs.copyFileSync(path.join(FONTS, 'AllFonts.js'), fontsCopy);
	const o = await openEditor({ webapps, webappsDeploy: DEPLOY, sdkjs: SDKJS, allFonts: fontsCopy, editorBin: bin, doctype, filetype: c.ext });
	const f = o.frame, page = o.page;
	const ev = (fn, arg) => f.evaluate(fn, arg);
	try {
		await f.waitForFunction((G) => window[G] && document.querySelector('#toolbar .panel.active') &&
			window[G].getController('Toolbar').toolbar && $('#toolbar .ribtab:visible').length > 3, c.G, { timeout: 180000 });
		await sleep(2500);
		check(tag + 'editor is up with no modal window', await ev(() => !Common.Utils.ModalWindow.isVisible()));
		await ev((G) => {
			window.__G = window[G];
			window.api = window.__G.getController('Main').api;
			window.tb = window.__G.getController('Toolbar').toolbar;
			window.__box = () => !!document.querySelector('.cmd-search') && $('.cmd-search').is(':visible');
			window.__rows = () => $('.cmd-search li[data-index]').map((i, li) => ({ text: li.textContent, disabled: li.getAttribute('aria-disabled') === 'true',
				selected: li.getAttribute('aria-selected') === 'true' })).get();
			Common.UI.Menu.Manager.hideAll();
			$('.synch-tip-root').remove();
			Common.NotificationCenter.trigger('edit:complete');
		}, c.G);
		await sleep(400);
		const isMac = await ev(() => Common.Utils.isMac);
		const shortcut = isMac ? 'Control+Alt+Slash' : 'Alt+Slash';
		const focusId = () => ev(() => document.activeElement && (document.activeElement.id || document.activeElement.className || document.activeElement.tagName));

		// 1. default: off
		await page.keyboard.press(shortcut);
		await sleep(300);
		check(tag + 'setting off (default): the shortcut opens nothing', !(await ev(() => window.__box())));

		// 2. the Advanced settings checkbox, through the real panel
		const st = await ev((p) => {
			window.__G.getController('LeftMenu').leftMenu.showMenu('file:opts');
			const opts = window.__G.getController('LeftMenu').leftMenu.menuFile.panels.opts;
			const panel = opts && opts.chCommandSearch ? opts : _.find(_.values(opts || {}), v => v && v.chCommandSearch);
			if (!panel) return { found: false };
			const r = { found: true, label: panel.chCommandSearch.$el.text().trim(), checked: panel.chCommandSearch.getValue() === 'checked' || panel.chCommandSearch.isChecked() };
			panel.chCommandSearch.setValue(true);
			panel.applySettings();
			r.stored = Common.localStorage.getBool(p + '-settings-command-search');
			window.__G.getController('LeftMenu').leftMenu.menuFile.hide();
			return r;
		}, c.p);
		check(tag + 'Advanced settings has "Command search (<shortcut>)", unchecked by default; Apply stores it',
			st.found && /^Command search \((Alt\+\/|⌃⌥\/)\)$/.test(st.label) && !st.checked && st.stored, st);
		await ev(() => { Common.NotificationCenter.trigger('edit:complete'); });
		await sleep(500);

		// 3. a button found from another tab
		await ev((t) => { tb.setTab(t); window.__pages0 = api.getCountPages ? api.getCountPages() : 0; Common.NotificationCenter.trigger('edit:complete'); }, c.button.start);
		await sleep(400);
		const focusBefore = await focusId();
		await page.keyboard.press(shortcut);
		await sleep(300);
		check(tag + 'setting on: the shortcut opens the box with the focus in it',
			await ev(() => window.__box() && document.activeElement === document.querySelector('.cmd-search input')));
		await page.keyboard.type(c.button.query);
		await sleep(300);
		const rows1 = await ev(() => window.__rows());
		check(tag + `"${c.button.query}" lists the button first, with its tab, enabled`, rows1.length && !rows1[0].disabled && rows1[0].selected, { rows: rows1.slice(0, 3), val: await ev(() => $('.cmd-search input').val()), n: await ev(() => Common.UI.CommandSearch.search(Common.UI.CommandSearch.buildIndex(tb), $('.cmd-search input').val()).length) });
		await page.keyboard.press('Enter');
		await sleep(1200);
		const r3 = await ev((c) => ({ box: window.__box(), tab: tb.$tabs.filter('.active').find('a').data('tab'), effect: !!eval(c.effect) }), c.button);
		check(tag + `Enter: box closed, ${c.button.static ? 'tab unchanged (static panel)' : 'tab switched to ' + c.button.tab}, the click reached the document`,
			!r3.box && r3.tab === c.button.tab && r3.effect, r3);

		// 4. a menu item on another tab
		await ev(() => {
			const m = window.__clicks = [];
			Common.NotificationCenter.trigger('edit:complete');
			window.__hook = (btn) => btn.menu.on('item:click', (menu, item) => m.push(item.caption));
		});
		await ev((b) => window.__hook(tb[b]), c.item.btn).catch(() => {});
		await sleep(400);
		await page.keyboard.press(shortcut);
		await sleep(300);
		await page.keyboard.type(c.item.query);
		await sleep(300);
		const rows2 = await ev(() => window.__rows());
		await page.keyboard.press('Enter');
		await sleep(1200);
		const r4 = await ev((c) => ({ box: window.__box(), tab: tb.$tabs.filter('.active').find('a').data('tab'), clicks: window.__clicks,
			menuOpen: tb[c.btn] && tb[c.btn].menu.isVisible(), effect: !!eval(c.effect) }), c.item);
		check(tag + `"${c.item.query}": tab switched to ${c.item.tab}, the menu fired item:click for it, menu closed, document changed`,
			rows2.length && !r4.box && r4.tab === c.item.tab && r4.clicks.length === 1 && r4.clicks[0].toLowerCase() === c.item.query && !r4.menuOpen && r4.effect,
			{ first: rows2[0], r4 });

		// 5. disabled command
		await ev(() => { window.__dis = 0; Common.NotificationCenter.trigger('edit:complete'); });
		await sleep(400);
		await page.keyboard.press(shortcut);
		await sleep(300);
		await page.keyboard.type(c.disabled);
		await sleep(300);
		const rows3 = await ev((q) => {
			const e = Common.UI.CommandSearch.search(Common.UI.CommandSearch.buildIndex(tb), q)[0];
			e && e.btn.on('click', () => window.__dis++);
			return window.__rows();
		}, c.disabled);
		await page.keyboard.press('Enter');
		await sleep(500);
		const r5 = await ev(() => ({ box: window.__box(), clicks: window.__dis }));
		check(tag + `"${c.disabled}" is listed greyed (aria-disabled) and Enter does nothing`,
			rows3.length && rows3[0].disabled && r5.box && r5.clicks === 0, { first: rows3[0], r5 });

		// 6. Up / Down, Esc
		await page.keyboard.press(isMac ? 'Meta+A' : 'Control+A');
		await page.keyboard.type('a');
		await sleep(300);
		const sel = async () => (await ev(() => window.__rows())).findIndex(r => r.selected);
		const n = (await ev(() => window.__rows())).length;
		const s0 = await sel();
		await page.keyboard.press('ArrowDown');
		const s1 = await sel();
		await page.keyboard.press('ArrowUp');
		await page.keyboard.press('ArrowUp');
		const s2 = await sel();
		check(tag + 'Down/Up move the selection and wrap', n > 2 && s0 === 0 && s1 === 1 && s2 === n - 1, { n, s0, s1, s2 });
		await page.keyboard.press('Escape');
		await sleep(400);
		const r6 = await ev(() => ({ box: window.__box(), tab: tb.$tabs.filter('.active').find('a').data('tab') }));
		const focusAfter = await focusId();
		check(tag + 'Esc closes the box and the focus is back where it was', !r6.box && focusAfter === focusBefore && !!focusBefore, { r6, focusBefore, focusAfter });

		const errs = o.errors.filter(e => !/widgetType/.test(e));
		check(tag + 'no uncaught page errors', errs.length === 0, errs.map(e => e.split('\n')[0]));
	} catch (e) {
		check(tag + 'run', false, String(e && e.message || e).split('\n')[0]);
	} finally {
		await o.browser.close();
		o.srv.close();
	}
}

(async () => {
	for (const [p, what] of [[SDKJS, 'sdkjs deploy (RD_SDKJS)'], [path.join(DEPLOY, 'apps'), 'web-apps deploy (RD_WEBAPPS_DEPLOY)'],
		[path.join(CORE, 'Common', 'empty'), 'core (RD_CORE)'], [path.join(FONTS, 'AllFonts.js'), 'fonts cache (RD_FONTS)']]) {
		if (!fs.existsSync(p)) { console.log(`SKIP #1801: ${what} not found: ${p}`); process.exit(0); }
	}
	const tmp = fs.mkdtempSync(path.join(process.env.RD_TMP || os.tmpdir(), 'rd1801-'));
	try {
		const webapps = prepareWebapps(tmp);
		for (const d of EDITORS) await runEditor(d, webapps, tmp);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
	if (failed) {
		console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
		process.exit(1);
	}
	console.log('all checks passed');
})();
