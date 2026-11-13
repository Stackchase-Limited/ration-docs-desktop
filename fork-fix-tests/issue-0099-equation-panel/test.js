/*
 * DesktopEditors #99 - equation editing toolbox: "a specific toolbox on the right of the screen should appear
 * when editing a formula. It should provide a quicker access to symbols" (like the shape/table/chart panels).
 *
 * Before: while the cursor is in an equation the right sidebar shows only Paragraph settings; symbols and
 * structures are reached through Insert > Equation or the floating equation bar, one drop-down at a time.
 * Now (web-apps, opt-in): File > Advanced settings > "Show the Equation panel in the right sidebar when
 * editing an equation", stored as <de|pe>-settings-equation-panel, OFF by default (no button, nothing changes).
 * With it on, the right sidebar gets an Equation button/panel (common/main/lib/view/EquationSettings.js),
 * available while the cursor is in an equation and brought up on entering one. The panel has
 *   - the Insert > Equation gallery's structure groups (fraction, script, radical, integral, large operator,
 *     bracket, function, accent, limit/log, operator, matrix) as buttons with the same galleries, inserting
 *     with api.asc_AddMath into the current equation;
 *   - a symbol palette from sdkjs's math symbol table (word/Math/mathContent.js
 *     g_DefaultAutoCorrectMathSymbolsList, via api.asc_getAutoCorrectMathSymbols), searchable by \name
 *     and filtered by category (Greek, operators, relations, arrows, letter-like, other); a click puts the
 *     symbol into the equation (api.asc_insertSymbol);
 *   - Professional / Linear for the current equation (api.asc_ConvertMathView) and Unicode / LaTeX input.
 *
 * What runs: the REAL document and presentation editors - web-apps source tree under test in dev mode (requirejs) with a built
 * sdkjs, in headless Chromium, opened like the desktop app does (api/documents/index.html.desktop -> DocsAPI
 * iframe, stubbed AscDesktopEditor, core's empty docx/pptx). Checked in each:
 *   - setting off (default): cursor in an equation -> no Equation button, the Equation panel stays away;
 *   - the real Advanced settings panel has the checkbox (unchecked) and its Apply stores it and shows the button;
 *   - entering an equation brings the Equation panel up (button enabled); leaving it hides it again;
 *   - typing "alpha" in the search box lists alpha first; a mouse click on it puts the symbol into the
 *     equation (the ParaMath's text), not next to it;
 *   - the Arrows category lists only arrows; clicking one inserts it into the equation;
 *   - the Fraction button's gallery inserts a fraction (CFraction) into the same equation;
 *   - Linear turns the equation into linear text, Professional back into a built-up fraction;
 *   - LaTeX sets the math input type and stores it the way the context menu does (<de|pe>-equation-input-latex).
 *                                                     (BASELINE: no such setting/panel -> FAILS)
 * NOT claimed: the look of the panel in the app (headless Chromium only; styles come from a web-apps deploy's
 * app.css, the panel uses inline styles plus existing classes); keyboard navigation inside the palette; the
 * spreadsheet editor (no panel there: its equations live in shapes, with another right menu).
 *
 * Env: RD_REPO          web-apps checkout (default ../../web-apps)
 *      RD_SDKJS         built sdkjs deploy/sdkjs (default ../../sdkjs/deploy/sdkjs; same branch)
 *      RD_WEBAPPS_DEPLOY a built web-apps deploy/web-apps for app.css + sprites (default ../../web-apps/deploy/web-apps)
 *      RD_CORE          core checkout for Common/empty/docx.bin, pptx.bin (default ../../core)
 *      RD_FONTS         fonts cache dir with AllFonts.js (default ../../../.rd-work/fonts-cache; only read, copied)
 *      RD_PLAYWRIGHT, RD_CHROME, RD_TMP, RD_EDITORS=word,slide, RD_SHOT=<png> (screenshots with the panel up)
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
const EDITORS = (process.env.RD_EDITORS || 'word,slide').split(',');
const BASE_REF = process.env.BASE_REF || 'efb1591bde^';

let failed = 0;
function checkAll(name, ok, detail) {
	if (ok) console.log('ok   - ' + name);
	else { failed++; console.log('FAIL - ' + name + (detail !== undefined ? '\n       ' + JSON.stringify(detail) : '')); }
}

function prepareWebapps(tmp) {
	if (!process.env.BASELINE) return REPO;
	const dir = path.join(tmp, 'web-apps');
	fs.mkdirSync(dir);
	const tar = execFileSync('git', ['-C', REPO, 'archive', BASE_REF, 'apps', 'vendor'], { maxBuffer: 1 << 30 });
	execFileSync('tar', ['-x', '-C', dir], { input: tar, maxBuffer: 1 << 30 });
	return dir;
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const cfg = {
	word:  { ext: 'docx', p: 'de', G: 'DE' },
	slide: { ext: 'pptx', p: 'pe', G: 'PE' },
};

async function run(doctype, webapps, tmp) {
	const c = cfg[doctype], tag = doctype + ': ';
	const fontsCopy = path.join(tmp, 'AllFonts.js');
	if (!fs.existsSync(fontsCopy)) fs.copyFileSync(path.join(FONTS, 'AllFonts.js'), fontsCopy);
	// the right sidebar open, as after the user opened it once
	const o = await openEditor({ webapps, webappsDeploy: DEPLOY, sdkjs: SDKJS, allFonts: fontsCopy, doctype, filetype: c.ext,
		editorBin: path.join(CORE, 'Common', 'empty', c.ext + '.bin'), storage: { [c.p + '-hide-right-settings']: '0' } });
	const f = o.frame;
	const ev = (fn, arg) => f.evaluate(fn, arg);
	const check = (name, ok, detail) => checkAll(tag + name, ok, detail);
	try {
		await f.waitForFunction((G) => window[G] && document.querySelector('#toolbar .panel.active') &&
			window[G].getController('Toolbar').toolbar && window[G].getController('RightMenu').rightmenu && $('#right-menu .tool-menu-btns button:visible').length > 0, c.G, { timeout: 180000 });
		await sleep(2500);
		await ev((G) => {
			window.__G = window[G];
			window.api = __G.getController('Main').api;
			window.rm = __G.getController('RightMenu').rightmenu;
			window.__doc = api.WordControl.m_oLogicDocument;
			window.__pm = () => { const p = __doc.GetCurrentParagraph(); return p && p.Content.find(x => x instanceof AscCommonWord.ParaMath); };
			window.__math = () => { const m = __pm(); return m ? { text: m.GetText(), kinds: m.Root.Content.map(c => c.constructor.name) } : null; };
			window.__btn = () => { const b = document.getElementById('id-right-menu-equation'); return { exists: !!b, visible: !!b && $(b).is(':visible'), disabled: !!b && (b.disabled || $(b).hasClass('disabled')) }; };
			window.__leave = G === 'DE' ? () => { __doc.MoveCursorToEndPos(); __doc.Document_UpdateInterfaceState(); }
				: () => { __doc.GetCurrentController().resetSelection(); __doc.Document_UpdateInterfaceState(); };
			Common.UI.Menu.Manager.hideAll();
			Common.NotificationCenter.trigger('edit:complete');
		}, c.G);
		check('editor is up with the right sidebar open', await ev(() => !rm.minimizedMode));

		// 1. default: off
		await ev(() => api.asc_AddMath());
		await sleep(1500);
		const r1 = await ev(() => ({ inMath: api.getSelectedElements().some(e => e.get_ObjectType() === Asc.c_oAscTypeSelectElement.Math), btn: __btn(), pane: rm.GetActivePane() }));
		check('setting off (default): cursor in an equation, no Equation button, the Equation panel is not shown',
			r1.inMath && !r1.btn.visible && !!r1.pane && r1.pane !== 'id-equation-settings', r1);

		// 2. the Advanced settings checkbox, through the real panel
		const st = await ev((p) => {
			__G.getController('LeftMenu').leftMenu.showMenu('file:opts');
			const opts = __G.getController('LeftMenu').leftMenu.menuFile.panels.opts;
			const panel = opts && opts.chEquationPanel ? opts : _.find(_.values(opts || {}), v => v && v.chEquationPanel);
			if (!panel) return { found: false };
			const r = { found: true, label: panel.chEquationPanel.$el.text().trim(), checked: panel.chEquationPanel.isChecked() };
			panel.chEquationPanel.setValue(true);
			panel.applySettings();
			r.stored = Common.localStorage.getBool(p + '-settings-equation-panel');
			__G.getController('LeftMenu').leftMenu.menuFile.hide();
			return r;
		}, c.p);
		check('Advanced settings has the Equation panel checkbox, unchecked by default; Apply stores it',
			st.found && /Equation panel/.test(st.label) && !st.checked && st.stored, st);
		await sleep(800);
		const r2 = await ev(() => ({ btn: __btn(), pane: rm.GetActivePane() }));
		check('with the setting on and the cursor in the equation: the Equation button is shown, enabled, and its panel is up',
			r2.btn.visible && !r2.btn.disabled && r2.pane === 'id-equation-settings', r2);

		// leave and re-enter: the panel follows the cursor
		await ev(() => __leave());
		await sleep(800);
		const r3 = await ev(() => ({ inMath: !!__pm(), btn: __btn(), pane: rm.GetActivePane() }));
		await ev(() => api.asc_AddMath());
		await sleep(1500);
		const r3b = await ev(() => ({ btn: __btn(), pane: rm.GetActivePane(), inMath: api.getSelectedElements().some(e => e.get_ObjectType() === Asc.c_oAscTypeSelectElement.Math) }));
		check('leaving the equation: the Equation button is disabled and the panel goes; a new equation brings it back',
			!r3.inMath && r3.btn.disabled && r3.pane !== 'id-equation-settings' && !r3b.btn.disabled && r3b.pane === 'id-equation-settings' && r3b.inMath, { r3, r3b });

		// 3. search + click on a symbol
		await f.click('#id-equation-settings .eq-symbol-search input');
		await o.page.keyboard.type('alpha');
		await sleep(400);
		const first = await ev(() => $('#id-equation-settings .eq-symbols .eq-symbol').slice(0, 3).map((i, e) => ({ ch: e.textContent, tip: e.title })).get());
		check('searching "alpha" lists alpha first (with its \\name as the tooltip)', first.length && first[0].ch === 'α' && /\\alpha/.test(first[0].tip), first);
		await f.click('#id-equation-settings .eq-symbols .eq-symbol >> nth=0');
		await sleep(1200);
		const r4 = await ev(() => __math());
		check('clicking it puts alpha into the equation', r4 && r4.text === 'α', r4);

		// 4. Arrows category
		const arrows = await ev(() => {
			const c = rm.equationSettings;
			c.inputSearch.setValue(''); c.cmbCategory.setValue('arrows'); c.fillSymbols();
			return $('#id-equation-settings .eq-symbols .eq-symbol').map((i, e) => parseInt(e.getAttribute('data-code'))).get();
		});
		const isArrow = (c) => (c >= 0x2190 && c <= 0x21FF) || (c >= 0x27F0 && c <= 0x27FF) || (c >= 0x2900 && c <= 0x297F) || (c >= 0x2B04 && c <= 0x2B0D);
		check('the Arrows category lists only arrows (and includes the right arrow)', arrows.length > 10 && arrows.every(isArrow) && arrows.includes(0x2192), arrows.length);
		await f.click('#id-equation-settings .eq-symbols .eq-symbol[data-code="8594"]');
		await sleep(1200);
		const r5 = await ev(() => __math());
		check('clicking the right arrow puts it into the equation', r5 && r5.text === 'α→', r5);

		// 5. Fraction button -> gallery -> first item
		const fracIdx = await ev(() => rm.equationSettings.structureBtns.findIndex(b => b.options.value === Common.define.c_oAscMathMainType.Fraction));
		const nBtns = await ev(() => rm.equationSettings.structureBtns.length);
		check('the panel has the gallery\'s 11 structure groups as buttons', nBtns === 11 && fracIdx >= 0, { nBtns, fracIdx });
		await f.click(`#id-equation-settings .eq-structures > span:nth-child(${fracIdx + 1}) button`);
		await sleep(800);
		const menuItems = await ev((i) => { const m = rm.equationSettings.structureBtns[i].menu; return { open: m.isVisible(), n: m.cmpEl.find('.item-equation').length }; }, fracIdx);
		await f.click(`#id-eq-settings-structure-${FRACTION} .item >> nth=0`).catch(e => menuItems.err = String(e.message).split('\n')[0]);
		await sleep(1500);
		const r6 = await ev(() => __math());
		check('the Fraction gallery opens and its first item puts a fraction into the same equation',
			menuItems.open && menuItems.n > 0 && r6 && r6.kinds.includes('CFraction') && /α→/.test(r6.text), { menuItems, r6 });

		if (process.env.RD_SHOT) { // a picture of the panel, for a look (headless styles)
			await ev(() => { Common.UI.Menu.Manager.hideAll(); const c = rm.equationSettings; c.cmbCategory.setValue('all'); c.fillSymbols(); });
			await o.page.screenshot({ path: process.env.RD_SHOT.replace(/(\.png)?$/, '-' + doctype + '.png') });
		}

		// 6. Linear / Professional
		await f.click('#id-equation-settings .eq-btn-linear button');
		await sleep(1200);
		const lin = await ev(() => __math());
		await f.click('#id-equation-settings .eq-btn-professional button');
		await sleep(1200);
		const prof = await ev(() => __math());
		check('Linear turns the equation into linear text, Professional builds the fraction up again',
			lin && !lin.kinds.includes('CFraction') && /\//.test(lin.text) && prof && prof.kinds.includes('CFraction'), { lin, prof });

		// 7. LaTeX input
		await f.click('#id-equation-settings .eq-radio-latex');
		await sleep(400);
		const r7 = await ev((p) => ({ type: api.asc_GetMathInputType(), latex: Asc.c_oAscMathInputType.LaTeX, stored: Common.localStorage.getBool(p + '-equation-input-latex') }), c.p);
		check('LaTeX sets the math input type and stores it like the context menu does', r7.type === r7.latex && r7.stored, r7);

		const errs = o.errors.filter(e => !/widgetType/.test(e));
		check('no uncaught page errors', errs.length === 0, errs.map(e => e.split('\n')[0]));
	} catch (e) {
		check('run', false, String(e && e.message || e).split('\n')[0]);
	} finally {
		await o.browser.close();
		o.srv.close();
	}
}
const FRACTION = 1; // Common.define.c_oAscMathMainType.Fraction

(async () => {
	for (const [p, what] of [[SDKJS, 'sdkjs deploy (RD_SDKJS)'], [path.join(DEPLOY, 'apps'), 'web-apps deploy (RD_WEBAPPS_DEPLOY)'],
		[path.join(CORE, 'Common', 'empty'), 'core (RD_CORE)'], [path.join(FONTS, 'AllFonts.js'), 'fonts cache (RD_FONTS)']]) {
		if (!fs.existsSync(p)) { console.log(`SKIP #99: ${what} not found: ${p}`); process.exit(0); }
	}
	const tmp = fs.mkdtempSync(path.join(process.env.RD_TMP || os.tmpdir(), 'rd0099-'));
	try {
		const webapps = prepareWebapps(tmp);
		for (const d of EDITORS) await run(d, webapps, tmp);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
	if (failed) {
		console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
		process.exit(1);
	}
	console.log('all checks passed');
})();
