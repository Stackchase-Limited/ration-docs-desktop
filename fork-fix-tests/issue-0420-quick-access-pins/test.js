/*
 * DesktopEditors #420 - pin a toolbar button to the quick access toolbar ("give an option to put
 * commands on top", as Microsoft Office's "Add to Quick Access Toolbar").
 *
 * Before: the quick access toolbar of the header was a fixed set (Save, Print, Quick print, Undo, Redo,
 * Start slideshow - Header.js onChangeQuickAccess); ribbon buttons had no context menu and could not be
 * put there.
 * Now (web-apps, opt-in): File > Advanced settings > "Allow pinning toolbar buttons to the quick access
 * toolbar" - <de|sse|pe>-settings-quick-access-pins, OFF by default (no right-click menu, no pins, as
 * before). With it on, right-click on a plain ribbon button (own id, icon, no menu, not split) offers
 * "Add to quick access toolbar" (common/main/lib/view/QuickAccessPins.js). The pin is a header button with
 * the source's icon and hint, before the Customize Quick Access button; it follows the source's disabled
 * and pressed state and a click on it clicks the source. Pins are stored per editor in
 * <de|sse|pe>-quick-access-pins (button ids, at most 10). Right-click on the pin ("Remove from quick
 * access toolbar") or unchecking it in the Customize Quick Access menu removes it.
 *
 * What runs: the REAL editors - web-apps source tree under test in dev mode (requirejs) with a built
 * sdkjs, in headless Chromium, opened like the desktop app does (api/documents/index.html.desktop ->
 * DocsAPI iframe, stubbed AscDesktopEditor, core's empty docx/xlsx/pptx templates). Right-clicks and
 * clicks are real mouse events (Playwright).
 * Document editor:
 *   - setting off (default): right-click on Bold shows no menu, no pins;
 *   - the real Advanced settings panel has the checkbox (unchecked) and its Apply stores the setting;
 *   - right-click on Bold -> "Add to quick access toolbar" -> a header pin with Bold's icon and hint,
 *     stored as de-quick-access-pins = ["id-toolbar-btn-bold"];
 *   - typed text, selected, a click on the pin: the selection becomes bold (and the pin shows pressed);
 *   - a split button (Highlight colour) and a menu button (Table) get no menu;
 *   - when the editor's lock code disables Bold, the pin is disabled and a click on it does nothing;
 *     enabled again with Bold;
 *   - page reload: the pin is back (from localStorage) and still makes the selection bold;
 *   - right-click on the pin -> "Remove from quick access toolbar" removes it; the Customize Quick
 *     Access menu lists a pin checked and unchecking it removes it;
 *   - 10 pins at most (the 11th is refused and "Add" is greyed); setting off hides the pins.
 * Spreadsheet / presentation editors: the checkbox exists and is off by default; with it on, a button is
 *   pinned by right-click (spreadsheet: Bold, and a click on the pin makes the selected cell bold;
 *   presentation: the first enabled plain Home button - Bold is disabled with nothing selected - and a
 *   click on the pin is one click on it); the pin has its icon, hint and disabled state.
 *                                                                  (BASELINE: no pinning -> FAILS)
 * NOT claimed: the look in the app (only headless Chromium; styles come from a web-apps deploy's app.css);
 * the disabled check drives Bold's lock through Common.Utils.lockControls (the editors' own lock path),
 * not through a particular document state; Windows/Linux, where the title bar is native and its buttons
 * (ceditorwindow_p.h) do NOT show pins - only the in-page header (macOS, and the in-page row) does; large
 * ribbon buttons whose icon has no 20px variant; pdf/visio editors have no pinning. A button can only be
 * pinned while it is enabled: the browser gives a disabled <button> no mouse events, so no right-click.
 *
 * Env: RD_REPO          web-apps checkout (default ../../web-apps)
 *      RD_SDKJS         built sdkjs deploy/sdkjs (default ../../sdkjs/deploy/sdkjs)
 *      RD_WEBAPPS_DEPLOY a built web-apps deploy/web-apps for app.css + sprites (default ../../web-apps/deploy/web-apps)
 *      RD_CORE          core checkout for Common/empty/*.bin (default ../../core)
 *      RD_FONTS         fonts cache dir with AllFonts.js (default ../../../.rd-work/fonts-cache; only read)
 *      RD_PLAYWRIGHT, RD_CHROME, RD_TMP, RD_EDITORS=word,cell,slide
 *      BASELINE=1       web-apps from `git archive BASE_REF` (default the parent of the change); must FAIL.
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
const BASE_REF = process.env.BASE_REF || '12a95aaeda^';
const EDITORS = (process.env.RD_EDITORS || 'word,cell,slide').split(',');

let failed = 0;
function check(name, ok, detail) {
	if (ok) console.log('ok   - ' + name);
	else { failed++; console.log('FAIL - ' + name + (detail !== undefined ? '\n       ' + JSON.stringify(detail) : '')); }
}

const cfg = {
	word: { ext: 'docx', p: 'de', G: 'DE', bold: 'api.WordControl.m_oLogicDocument.GetCalculatedTextPr().Bold === true' },
	cell: { ext: 'xlsx', p: 'sse', G: 'SSE', bold: 'api.asc_getCellInfo().asc_getXfs().asc_getFontBold() === true' },
	slide: { ext: 'pptx', p: 'pe', G: 'PE', bold: null },
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

// page-side helpers, installed after every (re)load
function installHelpers(G) {
	window.__G = window[G];
	window.api = window.__G.getController('Main').api;
	window.tb = window.__G.getController('Toolbar').toolbar;
	window.__menuItems = () => $('.dropdown-menu:visible li:visible > a').map((i, a) => ({ text: a.textContent.trim(),
		disabled: $(a).parent().hasClass('disabled') })).get();
	window.__pins = () => $('#box-document-title .qa-pin').map((i, s) => {
		const b = $(s).children().first();
		return { id: s.getAttribute('data-pin-id'), icon: b.find('.icon').attr('class') || '', disabled: b.is('[disabled]') || b.hasClass('disabled'),
			active: b.hasClass('active'), hint: b.attr('data-original-title') || b.attr('title') || ($(b).data('ui-button') || {options: {}}).options.hint || '',
			beforeQa: !!$(s).nextAll('#slot-btn-dt-quick-access').length };
	}).get();
	Common.UI.Menu.Manager.hideAll();
	$('.synch-tip-root').remove();
	Common.NotificationCenter.trigger('edit:complete');
}

async function waitReady(f, G) {
	await f.waitForFunction((G) => window[G] && document.querySelector('#toolbar .panel.active') &&
		window[G].getController('Toolbar').toolbar && $('#toolbar .ribtab:visible').length > 3, G, { timeout: 180000 });
	await sleep(2500);
	await f.evaluate(installHelpers, G);
	await sleep(400);
}

async function runEditor(doctype, webapps, tmp) {
	const c = cfg[doctype];
	const tag = doctype + ': ';
	const bin = path.join(CORE, 'Common', 'empty', c.ext + '.bin');
	const fontsCopy = path.join(tmp, 'AllFonts.js');
	if (!fs.existsSync(fontsCopy)) fs.copyFileSync(path.join(FONTS, 'AllFonts.js'), fontsCopy);
	const o = await openEditor({ webapps, webappsDeploy: DEPLOY, sdkjs: SDKJS, allFonts: fontsCopy, editorBin: bin, doctype, filetype: c.ext });
	const page = o.page;
	const ev = (fn, arg) => o.frame.evaluate(fn, arg);
	const key = c.p + '-quick-access-pins';
	const rightClick = async (sel) => { await o.frame.click(sel, { button: 'right', timeout: 10000 }); await sleep(400); };
	const closeMenus = () => ev(() => { Common.UI.Menu.Manager.hideAll(); Common.NotificationCenter.trigger('edit:complete'); });
	const clickMenuItem = async (text) => {
		const a = o.frame.locator('.dropdown-menu:visible li:visible > a', { hasText: text }).first();
		await a.click();
		await sleep(500);
	};
	const pinSel = (id) => `#box-document-title .qa-pin[data-pin-id="${id}"] > button`;
	const BOLD = 'id-toolbar-btn-bold';
	try {
		await waitReady(o.frame, c.G);
		await ev(() => tb.setTab('home'));
		await sleep(300);
		// the button pinned: Bold; in the presentation editor Bold is disabled with nothing selected (and a disabled
		// <button> gets no mouse events), so there the first enabled plain button of the Home tab
		const BTN = doctype !== 'slide' ? BOLD : await ev(() => $('#toolbar .panel[data-tab="home"] button[id]:visible').map((i, b) => $(b).data('ui-button')).get()
			.filter(b => b && b.cmpEl[0].tagName === 'BUTTON' && !b.menu && !b.split && b.options.id && b.options.iconCls && !b.isDisabled())
			.map(b => b.options.id)[0]);
		const name = BTN === BOLD ? 'Bold' : BTN;
		const iconRe = new RegExp('\\b' + (await ev((id) => $('#' + id).data('ui-button').options.iconCls.split(/\s+/).pop(), BTN)) + '\\b');
		await ev((id) => { window.__srcClicks = 0; $('#' + id).data('ui-button').on('click', () => window.__srcClicks++); }, BTN);

		// 1. default: off
		await rightClick('#' + BTN);
		const m0 = await ev(() => window.__menuItems());
		check(tag + `setting off (default): right-click on ${name} shows no menu and there are no pins`,
			!m0.some(i => /quick access/i.test(i.text)) && (await ev(() => window.__pins())).length === 0, m0);
		await closeMenus();

		// 2. the Advanced settings checkbox, through the real panel
		const st = await ev((p) => {
			window.__G.getController('LeftMenu').leftMenu.showMenu('file:opts');
			const opts = window.__G.getController('LeftMenu').leftMenu.menuFile.panels.opts;
			const panel = opts && opts.chQuickAccessPins ? opts : _.find(_.values(opts || {}), v => v && v.chQuickAccessPins);
			if (!panel) return { found: false };
			const r = { found: true, label: panel.chQuickAccessPins.$el.text().trim(), checked: panel.chQuickAccessPins.isChecked() };
			panel.chQuickAccessPins.setValue(true);
			panel.applySettings();
			r.stored = Common.localStorage.getBool(p + '-settings-quick-access-pins');
			window.__G.getController('LeftMenu').leftMenu.menuFile.hide();
			return r;
		}, c.p);
		check(tag + 'Advanced settings has "Allow pinning toolbar buttons to the quick access toolbar", unchecked by default; Apply stores it',
			st.found && st.label === 'Allow pinning toolbar buttons to the quick access toolbar' && !st.checked && st.stored, st);
		await ev(() => { tb.setTab('home'); Common.NotificationCenter.trigger('edit:complete'); });
		await sleep(500);

		// 3. right-click on Bold -> Add
		await rightClick('#' + BTN);
		const m1 = await ev(() => window.__menuItems());
		check(tag + `setting on: right-click on ${name} offers "Add to quick access toolbar" (only)`,
			m1.length === 1 && m1[0].text === 'Add to quick access toolbar' && !m1[0].disabled, m1);
		if (m1.some(i => i.text === 'Add to quick access toolbar')) await clickMenuItem('Add to quick access toolbar');
		const p1 = await ev(() => window.__pins());
		const srcInfo = await ev((id) => { const b = $('#' + id).data('ui-button'); return { hint: b.options.hint, disabled: b.isDisabled() }; }, BTN);
		check(tag + `a pin appears in the header quick access toolbar with ${name}'s icon and hint, and is stored`,
			p1.length === 1 && p1[0].id === BTN && iconRe.test(p1[0].icon) && p1[0].hint === srcInfo.hint && p1[0].beforeQa &&
			(await ev((k) => Common.localStorage.getItem(k), key)) === JSON.stringify([BTN]), { p1, srcInfo });
		check(tag + 'the pin\'s disabled state is its source\'s', p1.length === 1 && p1[0].disabled === srcInfo.disabled, { p1, srcInfo });

		// 4. a click on the pin is a click on Bold
		if (c.bold) {
			if (doctype === 'word') {
				await ev(() => Common.NotificationCenter.trigger('edit:complete'));
				await page.keyboard.type('Pinned bold');
				await sleep(300);
				await ev(() => { const d = api.WordControl.m_oLogicDocument; d.SelectAll(); d.Document_UpdateSelectionState && d.Document_UpdateSelectionState(); });
				await sleep(500);
			}
			const before = await ev((e) => !!eval(e), c.bold);
			await o.frame.click(pinSel(BOLD));
			await sleep(800);
			const after = await ev((e) => !!eval(e), c.bold);
			const pp = await ev(() => window.__pins());
			check(tag + 'click on the pin: the selection becomes bold' + (doctype === 'word' ? ' and the pin shows pressed' : ''),
				!before && after && (doctype !== 'word' || pp[0].active), { before, after, pp });
		} else {
			await o.frame.click(pinSel(BTN));
			await sleep(800);
			check(tag + 'click on the pin: one click on its source button', await ev(() => window.__srcClicks) === 1, await ev(() => window.__srcClicks));
		}

		if (doctype === 'word') {
			// 5. split / menu buttons get no menu
			await closeMenus();
			await rightClick('#id-toolbar-btn-highlight > button >> nth=0');
			const m2 = await ev(() => window.__menuItems());
			await closeMenus();
			await ev(() => tb.setTab('ins'));
			await sleep(300);
			await rightClick('#tlbtn-inserttable');
			const m3 = await ev(() => window.__menuItems());
			await closeMenus();
			check(tag + 'split (Highlight colour) and menu (Table) buttons are not offered', !m2.some(i => /quick access/i.test(i.text)) &&
				!m3.some(i => /quick access/i.test(i.text)), { m2, m3 });
			await ev(() => tb.setTab('home'));

			// 6. disabled with its source
			await ev(() => { window.__boldClicks = 0; $('#id-toolbar-btn-bold').data('ui-button').on('click', () => window.__boldClicks++); });
			await ev(() => Common.Utils.lockControls(Common.enumLock.viewMode, true, { array: [tb.btnBold] }));
			await sleep(200);
			const d1 = (await ev(() => window.__pins()))[0];
			await o.frame.click(pinSel(BOLD), { force: true }).catch(() => {});
			await sleep(300);
			const clicksDisabled = await ev(() => window.__boldClicks);
			const boldStill = await ev((e) => !!eval(e), c.bold);
			await ev(() => Common.Utils.lockControls(Common.enumLock.viewMode, false, { array: [tb.btnBold] }));
			await sleep(200);
			const d2 = (await ev(() => window.__pins()))[0];
			check(tag + 'Bold disabled by the lock code -> the pin is disabled and a click does nothing; enabled again with Bold',
				d1 && d1.disabled && clicksDisabled === 0 && boldStill && d2 && !d2.disabled, { d1, d2, clicksDisabled, boldStill });

			// 7. reload: the pin is back and still works
			o.frame = await o.reload();
			await waitReady(o.frame, c.G);
			const p2 = await ev(() => window.__pins());
			check(tag + 'after a reload the pin is back from ' + key, p2.length === 1 && p2[0].id === BOLD && /\bbtn-bold\b/.test(p2[0].icon), p2);
			await ev(() => Common.NotificationCenter.trigger('edit:complete'));
			await page.keyboard.type('Again');
			await ev(() => { const d = api.WordControl.m_oLogicDocument; d.SelectAll(); d.Document_UpdateSelectionState && d.Document_UpdateSelectionState(); });
			await sleep(500);
			const b0 = await ev((e) => !!eval(e), c.bold);
			if (p2.length) await o.frame.click(pinSel(BOLD));
			await sleep(800);
			check(tag + 'after the reload a click on the pin makes the selection bold', !b0 && await ev((e) => !!eval(e), c.bold), { b0 });

			// 8. unpin by right-click on the pin
			if (p2.length) await rightClick(pinSel(BOLD));
			const m4 = await ev(() => window.__menuItems());
			if (m4.some(i => i.text === 'Remove from quick access toolbar')) await clickMenuItem('Remove from quick access toolbar');
			check(tag + 'right-click on the pin -> "Remove from quick access toolbar" removes it',
				m4.length === 1 && m4[0].text === 'Remove from quick access toolbar' && (await ev(() => window.__pins())).length === 0 &&
				(await ev((k) => Common.localStorage.getItem(k), key)) === '[]', m4);

			// 9. unpin from the Customize Quick Access menu
			await ev(() => { tb.setTab('home'); Common.NotificationCenter.trigger('edit:complete'); });
			await sleep(300);
			await rightClick('#id-toolbar-btn-italic');
			if ((await ev(() => window.__menuItems())).some(i => i.text === 'Add to quick access toolbar')) await clickMenuItem('Add to quick access toolbar');
			const p3 = await ev(() => window.__pins());
			await o.frame.click('#slot-btn-dt-quick-access button');
			await sleep(400);
			const cm = await ev(() => $('#slot-btn-dt-quick-access .dropdown-menu li:visible > a').map((i, a) => ({ text: a.textContent.trim(),
				checked: $(a).hasClass('checked') })).get());
			const it = cm.find(i => /italic/i.test(i.text));
			if (it) await clickMenuItem(it.text);
			await closeMenus();
			check(tag + 'the Customize Quick Access menu lists the pin (checked); unchecking it removes the pin',
				p3.length === 1 && it && it.checked && (await ev(() => window.__pins())).length === 0, { p3, cm });

			// 10. at most 10 pins; setting off hides them
			const lim = await ev(() => {
				const ids = $('#toolbar button[id]').map((i, b) => $(b).data('ui-button')).get().filter(b => Common.UI.QuickAccessPins.canPin(b));
				const ok = ids.slice(0, 11).map(b => Common.UI.QuickAccessPins.pin(b));
				return { n: ids.length, ok, pins: window.__pins().length };
			});
			await ev(() => tb.setTab('home'));
			await sleep(300);
			const unpinned = await ev(() => $('#toolbar button[id]').map((i, b) => $(b).data('ui-button')).get()
				.find(b => Common.UI.QuickAccessPins.canPin(b) && $(b.cmpEl).is(':visible') && !window.__pins().some(p => p.id === b.options.id)));
			let m5 = [];
			if (unpinned) {
				await rightClick('#' + (await ev(() => $('#toolbar button[id]').map((i, b) => $(b).data('ui-button')).get()
					.find(b => Common.UI.QuickAccessPins.canPin(b) && $(b.cmpEl).is(':visible') && !window.__pins().some(p => p.id === b.options.id)).options.id)));
				m5 = await ev(() => window.__menuItems());
				await closeMenus();
			}
			check(tag + 'at most 10 pins: the 11th is refused and "Add" is greyed', lim.n > 11 && lim.ok.filter(Boolean).length === 10 && !lim.ok[10] &&
				lim.pins === 10 && m5.length === 1 && m5[0].disabled, { lim, m5 });
			const off = await ev((p) => {
				Common.localStorage.setBool(p + '-settings-quick-access-pins', false);
				Common.NotificationCenter.trigger('quickaccess:pins');
				return window.__pins().length;
			}, c.p);
			await rightClick('#' + BOLD);
			const m6 = await ev(() => window.__menuItems());
			await closeMenus();
			check(tag + 'setting off again: no pins shown and no menu', off === 0 && !m6.some(i => /quick access/i.test(i.text)), { off, m6 });
		}

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
		if (!fs.existsSync(p)) { console.log(`SKIP #420: ${what} not found: ${p}`); process.exit(0); }
	}
	const tmp = fs.mkdtempSync(path.join(process.env.RD_TMP || os.tmpdir(), 'rd0420-'));
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
