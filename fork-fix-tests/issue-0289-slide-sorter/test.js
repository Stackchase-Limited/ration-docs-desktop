/*
 * DesktopEditors #289 - slide sorter view in the presentation editor ("a view showing all slides as thumbnails
 * to reorder them, as in PowerPoint / Impress").
 *
 * Before: the sorter mode existed only as a stub - sdkjs slide/apiDefines.js c_oAscPresentationViewMode.sorter = 2,
 * an empty `case sorter` in slide/Drawing/HtmlPage.js UpdateViewMode, and only a comment in web-apps
 * presentationeditor controller/ViewTab.js changeViewMode; there was no button and nothing to switch to.
 * Now: View tab > "Slide Sorter" (between Normal and Slide Master) switches to a full-area grid of slide
 * thumbnails. It is the thumbnails panel itself (same drawing, hit-testing, selection, drag and drop, keys and
 * context menu) stretched over the editor area with the slide view, notes and animation pane hidden; only the
 * layout (CThumbnailsManager.CalculateSorterPlaces), the drop position, the insertion line and a few keys differ.
 * A "Sorter zoom" slider next to it sets the thumbnails per row (api.asc_SetSorterColumns). Click, Ctrl+click and
 * Shift+click select; dragging and Ctrl+Up/Down move the selected slides through the same document operations as
 * the panel (shiftSlides / moveSlidesNextPos), so Undo works; Delete, Ctrl+C/X/V and Duplicate act on the
 * selection; the arrow keys move through the grid; double click or Enter opens the slide in Normal view; hidden
 * slides are drawn dimmed. Undo of an earlier normal-view change no longer throws the user out of the sorter
 * (Presentation.SetSelectionState only switches between master and slide views).
 *
 * What runs: the REAL presentation editor - web-apps source tree under test in dev mode with a built sdkjs, in
 * headless Chromium, opened like the desktop app (api/documents/index.html.desktop -> DocsAPI iframe, stubbed
 * AscDesktopEditor, core's empty pptx). Four slides are made (the 4th hidden), then with real mouse and keyboard
 * events:
 *   - the View tab has "Slide Sorter"; clicking it switches the sdk to sorter mode, presses only that button,
 *     enables the zoom slider, hides the slide view and gives the thumbnails canvas the whole editor area;
 *   - the slider sets thumbnails per row and the slides are laid out as a grid (2 per row: two rows);
 *   - click / Ctrl+click / Shift+click select;
 *   - dragging slide 3 onto the left half of slide 1 moves it before slide 1; Undo restores the order and
 *     the view stays the sorter;
 *   - Ctrl+Down moves the selected slide one place; arrow keys move through the grid (Down = next row);
 *   - Delete, Duplicate (Ctrl+D), Ctrl+C / Ctrl+V act on the selected slides (and undo);
 *   - the hidden slide's thumbnail is dimmed on the canvas;
 *   - double click opens slide 3 in Normal view (Normal pressed, slide view shown, current slide 3);
 *     Enter in the sorter opens the selected slide too.
 *                                                    (BASELINE: no Slide Sorter button, sorter mode does nothing -> FAILS)
 * NOT claimed: the look in the real app (headless Chromium only; styles and sprites come from a web-apps deploy, so
 * the new icon is only checked to exist as files); touch/mobile; right-to-left interface (the grid is laid out
 * left to right); the thumbnails' own context menu items are the panel's and are not re-tested here.
 *
 * Env: RD_REPO           web-apps checkout (default ../../web-apps)
 *      RD_SDKJS          built sdkjs deploy/sdkjs of the fix (default ../../sdkjs/deploy/sdkjs)
 *      RD_SDKJS_REPO     sdkjs checkout, for BASELINE (default ../../sdkjs)
 *      RD_WEBAPPS_DEPLOY a built web-apps deploy/web-apps for app.css + sprites (default ../../web-apps/deploy/web-apps)
 *      RD_CORE           core checkout for Common/empty/pptx.bin (default ../../core)
 *      RD_FONTS          fonts cache dir with AllFonts.js (default ../../../.rd-work/fonts-cache; only read, copied)
 *      RD_PLAYWRIGHT, RD_CHROME, RD_TMP
 *      BASELINE=1        web-apps from `git archive BASE_REF` (in RD_REPO) and sdkjs built (build/build.py, concatenation only)
 *                        from `git archive SDKJS_BASE_REF`; must FAIL.
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
const SDKJS_REPO = path.resolve(process.env.RD_SDKJS_REPO || path.join(HERE, '..', '..', 'sdkjs'));
const DEPLOY = path.resolve(process.env.RD_WEBAPPS_DEPLOY || path.join(REPO, 'deploy', 'web-apps'));
const CORE = path.resolve(process.env.RD_CORE || path.join(HERE, '..', '..', 'core'));
const FONTS = path.resolve(process.env.RD_FONTS || path.join(HERE, '..', '..', '..', '.rd-work', 'fonts-cache'));
const BASE_REF = process.env.BASE_REF || '5359a7c021^';
const SDKJS_BASE_REF = process.env.SDKJS_BASE_REF || 'f76943b391^';

let failed = 0;
function check(name, ok, detail) {
	if (ok) console.log('ok   - ' + name);
	else { failed++; console.log('FAIL - ' + name + (detail !== undefined ? '\n       ' + JSON.stringify(detail) : '')); }
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function gitArchive(repo, ref, dir, paths) {
	fs.mkdirSync(dir, { recursive: true });
	execFileSync('bash', ['-c', 'set -o pipefail; git -C "$1" archive "$2" "${@:4}" | tar -x -C "$3"', 'bash', repo, ref, dir].concat(paths || []),
		{ stdio: ['ignore', 'ignore', 'inherit'], shell: false });
}

function prepare(tmp) {
	if (!process.env.BASELINE) return { webapps: REPO, sdkjs: SDKJS };
	const webapps = path.join(tmp, 'web-apps');
	gitArchive(REPO, BASE_REF, webapps, ['apps', 'vendor']);
	const sdk = path.join(tmp, 'sdkjs');
	gitArchive(SDKJS_REPO, SDKJS_BASE_REF, sdk);
	execFileSync('python3', [path.join(sdk, 'build', 'build.py'), '--beta=false', '--minimize', '--desktop', '--product', 'slide'], { cwd: path.join(sdk, 'build'), stdio: 'ignore' });
	return { webapps, sdkjs: path.join(sdk, 'deploy', 'sdkjs') };
}

async function run(webapps, sdkjs, tmp) {
	const bin = path.join(CORE, 'Common', 'empty', 'pptx.bin');
	const fontsCopy = path.join(tmp, 'AllFonts.js');
	fs.copyFileSync(path.join(FONTS, 'AllFonts.js'), fontsCopy);
	const o = await openEditor({ webapps, webappsDeploy: DEPLOY, sdkjs, allFonts: fontsCopy, editorBin: bin, doctype: 'slide', filetype: 'pptx' });
	const f = o.frame, page = o.page;
	const ev = (fn, arg) => f.evaluate(fn, arg);
	try {
		await f.waitForFunction(() => window.PE && document.querySelector('#toolbar .panel.active') &&
			window.PE.getController('Toolbar').toolbar && $('#toolbar .ribtab:visible').length > 3, null, { timeout: 180000 });
		await sleep(2500);
		await ev(() => {
			window.api = PE.getController('Main').api;
			window.tb = PE.getController('Toolbar').toolbar;
			window.vt = PE.getController('ViewTab').view;
			window.__ids = () => api.WordControl.m_oLogicDocument.Slides.map(s => s.Get_Id());
			window.__th = () => api.WordControl.Thumbnails;
			window.__sel = () => __th().GetSelectedArray();
			window.__cur = () => api.WordControl.m_oDrawingDocument.SlideCurrent;
			// client coordinates of the centre (or a fraction across) of a slide's thumbnail
			window.__pt = (i, fx) => {
				const r = api.WordControl.m_oThumbnails.HtmlElement.getBoundingClientRect(), p = __th().m_arrPages[i], k = AscCommon.AscBrowser.retinaPixelRatio;
				const fr = window.frameElement.getBoundingClientRect();
				return { x: fr.left + r.left + (p.left + (p.right - p.left) * (fx === undefined ? 0.5 : fx)) / k, y: fr.top + r.top + (p.top + p.bottom) / 2 / k };
			};
			Common.UI.Menu.Manager.hideAll();
			$('.synch-tip-root').remove();
		});
		// four slides, the 4th hidden; slide 1 current
		await ev(() => { api.AddSlide(); api.AddSlide(); api.AddSlide(); api.WordControl.GoToPage(3); api.asc_HideSlides(true); api.WordControl.GoToPage(0); });
		await sleep(800);
		const ids = await ev(() => __ids());
		check('setup: 4 slides, the 4th hidden', ids.length === 4 && await ev(() => !api.WordControl.m_oLogicDocument.Slides[3].isVisible()), ids);

		const isMac = await ev(() => Common.Utils.isMac);
		const mod = isMac ? 'Meta' : 'Control';
		// a real click on a thumbnail (held modifier keys as the user would); waits past the double-click time
		const click = async (i, mods) => {
			const p = await ev((i) => __pt(i), i);
			for (const m of mods || []) await page.keyboard.down(m);
			await page.mouse.click(p.x, p.y);
			for (const m of mods || []) await page.keyboard.up(m);
			await sleep(600);
		};

		// 1. the View tab button
		await ev(() => tb.setTab('view'));
		await sleep(400);
		const btn = await ev(() => {
			const b = $('#slot-btn-slide-sorter button');
			if (!b.length || !b.is(':visible')) return null;
			const r = b[0].getBoundingClientRect(), fr = window.frameElement.getBoundingClientRect();
			return { x: fr.left + r.left + r.width / 2, y: fr.top + r.top + r.height / 2, caption: vt.btnSlideSorter.caption,
				text: b.text().replace(/\s+/g, ' ').trim(), prev: $('#slot-btn-slide-sorter').prev().attr('id') };
		});
		const icons = ['1x', '1.25x', '1.5x', '1.75x', '2x'].map(d => d + '/big/btn-slide-sorter.png').concat(['2.5x/big/btn-slide-sorter.svg']);
		const iconsMissing = icons.concat(icons.map(i => 'v2/' + i)).filter(i => !fs.existsSync(path.join(webapps, 'apps/presentationeditor/main/resources/img/toolbar', i)));
		check('its icon exists for every scale (classic and v2 sets)', iconsMissing.length === 0, iconsMissing);
		check('View tab has a "Slide Sorter" button next to Normal', btn && btn.caption.replace(/<br>/g, ' ') === 'Slide Sorter' && btn.text.replace(/ /g, '') === 'SlideSorter' &&
			btn.prev === 'slot-btn-normal', btn);
		if (!btn) throw new Error('no Slide Sorter button');
		await page.mouse.click(btn.x, btn.y);
		await sleep(1500);
		const s1 = await ev(() => {
			const body = api.WordControl.m_oBody.AbsolutePosition, th = api.WordControl.m_oThumbnailsContainer.AbsolutePosition;
			return { sorter: api.asc_IsSorterMode && api.asc_IsSorterMode(), mode: api.presentationViewMode,
				pressed: [vt.btnNormal.pressed, vt.btnSlideSorter && vt.btnSlideSorter.pressed, vt.btnSlideMaster.pressed],
				slider: vt.sldrSorterZoom && !vt.sldrSorterZoom.disabled,
				mainHidden: !$('#id_main_parent').is(':visible'),
				full: Math.abs((th.R - th.L) - (body.R - body.L)) < 1 && Math.abs((th.B - th.T) - (body.B - body.T)) < 1,
				canvasW: api.WordControl.m_oThumbnails.HtmlElement.width };
		});
		check('clicking it: sdk in sorter mode, only Slide Sorter pressed, zoom slider enabled', s1.sorter === true && s1.mode === 2 &&
			JSON.stringify(s1.pressed) === '[false,true,false]' && s1.slider, s1);
		check('the slide view is hidden and the thumbnails take the whole editor area', s1.mainHidden && s1.full && s1.canvasW > 800, s1);

		// 2. zoom slider -> 2 per row: a 2 x 2 grid
		const grid = await ev(() => {
			vt.sldrSorterZoom.setValue(9); vt.sldrSorterZoom.trigger('change', vt.sldrSorterZoom, 9);
			const p = __th().m_arrPages.map(p => [p.left, p.top, p.right - p.left]);
			return { cols: api.asc_GetSorterColumns(), p };
		});
		await sleep(800);
		const g = grid.p;
		check('zoom slider sets 2 thumbnails per row: slides laid out as a 2 x 2 grid', grid.cols === 2 && g[0][1] === g[1][1] && g[1][0] > g[0][0] &&
			g[2][0] === g[0][0] && g[2][1] > g[0][1] && g[3][1] === g[2][1] && g[0][2] > 300, grid);

		// 3. selection
		await click(2);
		const sel1 = await ev(() => ({ sel: __sel(), cur: __cur() }));
		await click(0, [mod]);
		const sel2 = await ev(() => __sel());
		await click(1);
		await click(3, ['Shift']);
		const sel3 = await ev(() => __sel());
		check('click selects slide 3; Ctrl+click adds slide 1; Shift+click selects a range (2-4)',
			JSON.stringify(sel1) === '{"sel":[2],"cur":2}' && JSON.stringify(sel2) === '[0,2]' && JSON.stringify(sel3) === '[1,2,3]', { sel1, sel2, sel3 });

		// 4. drag slide 3 before slide 1, undo
		await click(2);
		const from = await ev(() => __pt(2)), to = await ev(() => __pt(0, 0.2));
		await page.mouse.move(from.x, from.y);
		await page.mouse.down();
		for (let k = 1; k <= 10; k++) { await page.mouse.move(from.x + (to.x - from.x) * k / 10, from.y + (to.y - from.y) * k / 10); await sleep(30); }
		const dropPos = await ev(() => __th().MouseDownTrack.GetPosition());
		await page.mouse.up();
		await sleep(600);
		const afterDrag = await ev(() => __ids());
		check('dragging slide 3 onto the left half of slide 1 moves it first', dropPos === 0 &&
			JSON.stringify(afterDrag) === JSON.stringify([ids[2], ids[0], ids[1], ids[3]]), { dropPos, afterDrag, ids });
		await page.keyboard.press(mod + '+z');
		await sleep(600);
		const afterUndo = await ev(() => ({ ids: __ids(), sorter: api.asc_IsSorterMode(), btn: vt.btnSlideSorter.pressed }));
		check('Undo restores the order and the view stays the slide sorter', JSON.stringify(afterUndo.ids) === JSON.stringify(ids) && afterUndo.sorter && afterUndo.btn, afterUndo);

		// 5. Ctrl+Down moves the selection; arrows move through the grid
		await click(0);
		await page.keyboard.press('Control+ArrowDown');
		await sleep(400);
		const afterMove = await ev(() => __ids());
		await page.keyboard.press(mod + '+z');
		await sleep(400);
		const afterMoveUndo = await ev(() => __ids());
		check('Ctrl+Down moves the selected slide one place (and undoes)', JSON.stringify(afterMove) === JSON.stringify([ids[1], ids[0], ids[2], ids[3]]) &&
			JSON.stringify(afterMoveUndo) === JSON.stringify(ids), { afterMove, afterMoveUndo });
		await click(0);
		await page.keyboard.press('ArrowDown');
		await sleep(200);
		const curDown = await ev(() => __cur());
		await page.keyboard.press('ArrowRight');
		await sleep(200);
		const curRight = await ev(() => ({ cur: __cur(), sel: __sel() }));
		check('arrow keys move through the grid: Down = next row (slide 3), Right = next slide (slide 4)', curDown === 2 && curRight.cur === 3 &&
			JSON.stringify(curRight.sel) === '[3]', { curDown, curRight });

		// 6. Delete, Duplicate, copy/paste
		await click(1);
		await page.keyboard.press('Delete');
		await sleep(400);
		const afterDel = await ev(() => __ids());
		await page.keyboard.press(mod + '+z');
		await sleep(400);
		check('Delete removes the selected slide (and undoes)', JSON.stringify(afterDel) === JSON.stringify([ids[0], ids[2], ids[3]]) &&
			JSON.stringify(await ev(() => __ids())) === JSON.stringify(ids), afterDel);
		await click(1);
		await page.keyboard.press(mod + '+d');
		await sleep(500);
		const afterDup = await ev(() => ({ n: __ids().length, sorter: api.asc_IsSorterMode() }));
		await page.keyboard.press(mod + '+z');
		await sleep(400);
		check('Duplicate (Ctrl+D) duplicates the selected slide in the sorter (and undoes)', afterDup.n === 5 && afterDup.sorter &&
			(await ev(() => __ids().length)) === 4, afterDup);
		await click(0);
		await page.keyboard.press(mod + '+c');
		await sleep(300);
		await click(3);
		await page.keyboard.press(mod + '+v');
		await sleep(1200);
		const afterPaste = await ev(() => ({ n: __ids().length, sorter: api.asc_IsSorterMode() }));
		if (afterPaste.n === 5) { await page.keyboard.press(mod + '+z'); await sleep(400); }
		check('Ctrl+C / Ctrl+V copy the selected slide after the selection (and undo)', afterPaste.n === 5 && afterPaste.sorter &&
			(await ev(() => __ids().length)) === 4, afterPaste);

		// 7. hidden slide is dimmed (blank slides: visible thumbnail centre is white, hidden one is not)
		await sleep(1500);
		const px = await ev(() => {
			const c = api.WordControl.m_oThumbnails.HtmlElement, ctx = c.getContext('2d'), P = __th().m_arrPages;
			const at = (i) => { const p = P[i]; return Array.from(ctx.getImageData(((p.left + p.right) / 2) | 0, ((p.top + p.bottom) / 2) | 0, 1, 1).data); };
			return { visible: at(2), hidden: at(3) };
		});
		check('the hidden slide (4) is drawn dimmed', px.visible[0] > 245 && px.visible[1] > 245 && px.hidden[0] < 230 && px.hidden[0] > 100, px);

		// 8. double click opens the slide in Normal view; Enter too
		const p2 = await ev(() => __pt(2));
		await page.mouse.dblclick(p2.x, p2.y);
		await sleep(1500);
		const n1 = await ev(() => ({ sorter: api.asc_IsSorterMode(), mode: api.presentationViewMode, cur: __cur(),
			pressed: [vt.btnNormal.pressed, vt.btnSlideSorter.pressed], main: $('#id_main_parent').is(':visible') }));
		check('double click opens slide 3 in Normal view (Normal pressed, slide view shown)', !n1.sorter && n1.mode === 0 && n1.cur === 2 &&
			JSON.stringify(n1.pressed) === '[true,false]' && n1.main, n1);
		await ev(() => tb.setTab('view'));
		await page.mouse.click(btn.x, btn.y);
		await sleep(1200);
		const back = await ev(() => ({ sorter: api.asc_IsSorterMode(), cur: __cur() }));
		await click(1);
		await page.keyboard.press('Enter');
		await sleep(1200);
		const n2 = await ev(() => ({ sorter: api.asc_IsSorterMode(), cur: __cur(), n: __ids().length, main: $('#id_main_parent').is(':visible') }));
		check('back in the sorter the current slide is kept; Enter opens the selected slide (2) in Normal view', back.sorter && back.cur === 2 &&
			!n2.sorter && n2.cur === 1 && n2.n === 4 && n2.main, { back, n2 });

		const errs = o.errors.filter(e => !/widgetType/.test(e));
		check('no uncaught page errors', errs.length === 0, errs.map(e => e.split('\n')[0]));
	} catch (e) {
		check('run', false, String(e && e.message || e).split('\n')[0]);
	} finally {
		await o.browser.close();
		o.srv.close();
	}
}

(async () => {
	for (const [p, what] of [[SDKJS, 'sdkjs deploy (RD_SDKJS)'], [path.join(DEPLOY, 'apps'), 'web-apps deploy (RD_WEBAPPS_DEPLOY)'],
		[path.join(CORE, 'Common', 'empty'), 'core (RD_CORE)'], [path.join(FONTS, 'AllFonts.js'), 'fonts cache (RD_FONTS)']]) {
		if (!fs.existsSync(p)) { console.log(`SKIP #289: ${what} not found: ${p}`); process.exit(0); }
	}
	const tmp = fs.mkdtempSync(path.join(process.env.RD_TMP || os.tmpdir(), 'rd289-'));
	try {
		const { webapps, sdkjs } = prepare(tmp);
		await run(webapps, sdkjs, tmp);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
	if (failed) {
		console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
		process.exit(1);
	}
	console.log('all checks passed');
})();
