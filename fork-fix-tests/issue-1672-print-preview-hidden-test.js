/*
 * #1672 (follow-up) - the presentation editor's print preview showed hidden
 * slides and numbered its pages by slide, so it disagreed with what was printed.
 *
 * c32ac680e4 made the desktop print and PDF leave hidden slides
 * (<p:sld show="0">) out through asc_docs_api.getSlidesToPrint. The print
 * screen's preview (web-apps apps/presentationeditor/main/app/controller/Print.js)
 * only knew the slide count from asc_onCountPages: "slide X of Y" was the slide
 * number over the slide count and paging went through every slide, hidden ones
 * included, whatever the range. A 10-slide deck with slides 2 and 5 hidden
 * previewed as 10 pages and printed 8. Separately, the web/cloud PDF
 * (DrawingDocument.ToRendererPart) filtered hidden slides on its own: a deck
 * whose slides are all hidden gave a PDF with no pages, and a selection of only
 * hidden slides gave nothing, unlike getSlidesToPrint's explicit-choice rule.
 *
 * This extracts by brace matching the REAL sources and runs them on stubs:
 * from web-apps the whole PE print controller; from sdkjs getSlidesToPrint,
 * getSlidesToPrintInRange (fixed tree), _printDesktop, asc_nativePrint,
 * the asc_getSlidesToPrint export line, getNativePrintRanges and
 * ToRendererPart. The stub presentation has 10 slides, 2 and 5 hidden. The
 * preview is paged through as the print screen does (goToPage -> asc_onCurrentPage)
 * and compared with what the desktop print round trip
 * (asc_Print -> _printDesktop -> AscDesktopEditor.Print -> asc_nativePrint) draws.
 *
 * Claimed: preview pages == printed slides, in order, "page X of Y" counted
 * over them, for all slides, a custom range, a range of one hidden slide, and
 * the current slide; all hidden -> preview empty with its own message and
 * nothing printed from the print screen; ToRendererPart writes one blank page
 * for an all-hidden deck and prints an explicitly selected hidden slide.
 * NOT claimed: rendering, the real Backbone view, the canvas (headless Chromium
 * with the real slide sdk was run for the commits); the GUI print screen still
 * needs a manual look.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs), RD_WEBAPPS=<web-apps checkout>
 * (default ../web-apps). BASELINE=1 reads the sources with git show at
 * BASE_REF (sdkjs) and WEBAPPS_BASE_REF (web-apps), where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parents of the commits that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'e88d90ee71^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '73d504525b^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
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

function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return '';
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at) + ';\n';
}

function line(text, marker) {
	const at = text.indexOf(marker);
	return at === -1 ? '' : text.slice(at, text.indexOf('\n', at)) + '\n';
}

const api = src(SDKJS, BASE_REF, 'slide/api.js');
const common = src(SDKJS, BASE_REF, 'common/editorscommon.js');
const dd = src(SDKJS, BASE_REF, 'slide/Drawing/DrawingDocument.js');
const ctrl = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/presentationeditor/main/app/controller/Print.js');

const sdkCode =
	extract(common, 'function getNativePrintRanges(') +
	'AscCommon.getNativePrintRanges = getNativePrintRanges;\n' +
	extract(api, 'asc_docs_api.prototype.getSlidesToPrint = function', true) +
	extract(api, 'asc_docs_api.prototype.getSlidesToPrintInRange = function', true) +
	extract(api, 'asc_docs_api.prototype._printDesktop = function') +
	extract(api, 'window["asc_docs_api"].prototype["asc_nativePrint"] = function') +
	line(api, 'asc_docs_api.prototype["asc_getSlidesToPrint"]');
const toRendererPart = extract(dd, 'this.ToRendererPart = function');

/* --- stubs --- */
const SLIDES = 10;
const HIDDEN = [1, 4]; // slides 2 and 5

function makeApi(hidden, selected) {
	const window = {};
	const AscCommon = {};
	function asc_docs_api() {}
	window['asc_docs_api'] = asc_docs_api;
	const out = { printed: null, pages: [], previews: [] };
	let current = null;
	function Renderer() {
		this.Memory = { Seek() {}, GetBase64Memory() { return ''; }, GetData() { return null; } };
		this.VectorMemoryForPrint = { ClearNoAttack() {} };
	}
	Renderer.prototype.InitPicker = function () {};
	Renderer.prototype.DocInfo = function () {};
	Renderer.prototype.BeginPage = function () { current = { slide: null }; };
	Renderer.prototype.EndPage = function () { out.pages.push(current.slide); current = null; };
	AscCommon.CDocumentRenderer = Renderer;
	AscCommon.CMemory = function () { this.ClearNoAttack = function () {}; };
	AscCommon.g_oTextMeasurer = { m_oManager: null };
	const Asc = { c_oAscPrintType: { EntireDocument: 0, Selection: 1 } };

	const slides = [...Array(SLIDES).keys()].map(i => ({
		isVisible: () => !hidden.includes(i),
		draw: () => { current.slide = i; },
	}));
	const logic = {
		Slides: slides,
		IsVisibleSlide: i => i >= 0 && i < SLIDES && !hidden.includes(i),
		IsVisioEditor: () => false,
		IsMasterMode: () => false,
		GetWidthMM: () => 254,
		GetHeightMM: () => 142.875,
		DrawPage: i => { current.slide = i; },
	};

	new Function('window', 'asc_docs_api', 'AscCommon', 'Asc', sdkCode)(window, asc_docs_api, AscCommon, Asc);

	const a = new asc_docs_api();
	const callbacks = {};
	let slide = 0;
	const thumbnails = { isSelectedPage: i => (selected || []).includes(i), GetSelectedArray: () => selected || [] };
	a.WordControl = {
		GetSlidesCount: () => SLIDES,
		m_oLogicDocument: logic,
		Thumbnails: thumbnails,
	};
	a.WordControl.m_oDrawingDocument = { GetSlidesCount: () => SLIDES, m_oLogicDocument: logic };
	a.ShowParaMarks = false;
	a.DocumentUrl = '';
	a.ThemeLoader = { ThemesUrl: '' };
	a.getCurrentPage = () => slide;
	a.getCountPages = () => SLIDES;
	a.asc_getCoreProps = () => null;
	a.asc_registerCallback = (name, f) => { callbacks[name] = f; };
	a.goToPage = i => { slide = i; callbacks['asc_onCurrentPage'] && callbacks['asc_onCurrentPage'](i); };
	a.asc_initPrintPreview = () => {};
	a.asc_closePrintPreview = () => {};
	a.asc_drawPrintPreview = i => { out.previews.push(i); };
	a.asc_Print = opts => a._printDesktop(opts);
	window['AscDesktopEditor'] = {
		Print(json) { out.printed = []; out.pages = []; a['asc_nativePrint'](undefined, undefined, JSON.parse(json)); out.printed = out.pages; },
		Print_Start() {}, Print_Page() {}, Print_End() {},
	};

	// ToRendererPart lives on the drawing document; run the real one against this api
	const ddObj = {
		m_oWordControl: a.WordControl,
		m_oLogicDocument: logic,
		m_lCurrentRendererPage: -1,
	};
	a.WordControl.m_oApi = a;
	new Function('_onbeforeunload', 'AscCommon', 'window', toRendererPart.replace(/^this\./, 'arguments[3].')).call(null, () => {}, AscCommon, { addEventListener() {} }, ddObj);
	a.webPdf = isSelection => { out.pages = []; ddObj.m_lCurrentRendererPage = -1; ddObj.ToRendererPart(true, isSelection); return out.pages; };
	a.out = out;
	return a;
}

/* The real controller with a stub view. */
function makeController(a) {
	const PE = { Controllers: {}, Views: {} };
	const _ = {
		extend: Object.assign, bind: (f, ctx, ...args) => f.bind(ctx, ...args),
		isEmpty: v => !v || !v.length, uniq: x => x, union: (x, y) => x.concat(y),
		range: n => [...Array(n).keys()],
		sortedIndex: (arr, v) => { let i = 0; while (i < arr.length && arr[i] < v) i++; return i; },
	};
	const Common = { NotificationCenter: { on() {}, trigger() {} }, UI: { Keys: { RETURN: 13, ESC: 27 } }, Utils: { isChrome: true } };
	const Asc = {
		asc_CAdjustPrint: function () { let n; this.asc_setNativeOptions = o => { n = o; }; this.asc_getNativeOptions = () => n; this.asc_getPrintType = () => 0; },
		asc_CDownloadOptions: function () { let ao; this.asc_setAdvancedOptions = o => { ao = o; }; Object.defineProperty(this, 'advancedOptions', { get: () => ao }); },
		c_oAscFileType: { PDF: 513 },
	};
	const Backbone = { Controller: { extend: o => o } };
	const define = (deps, f) => f();
	new Function('PE', '_', 'Common', 'Asc', 'Backbone', 'define', 'navigator', ctrl)(PE, _, Common, Asc, Backbone, define, { userAgent: '' });

	const c = Object.create(PE.Controllers.Print);
	c.addListeners = () => {};
	c.initialize();
	const ui = { range: 'all', input: '' };
	const btn = () => ({ setDisabled() {}, on() {} });
	const v = c.printSettings = {
		isVisible: () => true,
		$previewBox: { toggleClass(cls, on) { ui.boxHidden = on; }, removeClass() {}, on() {} },
		$previewEmpty: { toggleClass(cls, on) { ui.emptyHidden = on; }, find: () => ({ text(t) { ui.emptyText = t; } }) },
		updateCurrentPage(i) { ui.page = i + 1; },
		updateCountOfPages(n) { ui.count = n; },
		btnPrevPage: btn(), btnNextPage: btn(), btnPrintSystemDialog: btn(), btnPrint: btn(), btnPrintPdf: btn(),
		cmbRange: { on() {}, getValue: () => ui.range, setValue(x) { ui.range = x; } },
		inputPages: { on() {}, getValue: () => ui.input, setValue(x) { ui.input = x; }, showError() {}, focus() {}, checkValidate() { return this.validation(ui.input); } },
		txtNumberPage: { on() {}, cmpEl: { find: () => ({ on() {} }) }, setValue() {}, checkValidate() {} },
		cmbPaperSize: { on() {}, getSelectedRecord: () => ({ size: [210, 297], caption: 'A4' }) },
		cmbPrinter: { getSelectedRecord: () => null },
		cmbColorPrinting: { getValue: () => 'color' },
		spnCopies: { getNumberValue: () => 1 },
		cmbSides: { getValue: () => 'one' },
		menu: { hide() {}, on() {} },
		txtEmptyTable: 'presentation is empty',
		txtAllSlidesHidden: 'all slides are hidden',
	};
	c.onAfterRender(v);
	c.mode = { isEdit: true };
	c.setApi(a);
	c.onCountPages(SLIDES); // as at load
	c.ui = ui;
	return c;
}

/* Open the print screen with the editor on `start`, pick the range, page through
   the preview from the first page to the last and print. */
function run(hidden, start, range, input) {
	const a = makeApi(hidden);
	const c = makeController(a);
	a.goToPage(start);
	c.onShowMainSettingsPrint();
	if (range !== 'all') {
		c.ui.range = range;
		c.comboRangeChange(null, { value: range });
		if (range === -1) { c.ui.input = input; c.inputPagesChanging(null, input); c.ui.range = -1; }
	}
	const first = { page: c.ui.page, count: c.ui.count, empty: c.ui.boxHidden, emptyText: c.ui.emptyText };
	for (let k = 0; k < 20; k++) c.onChangePreviewPage(false);
	const seen = [];
	for (let k = 0; k < 20; k++) {
		const p = a.out.previews[a.out.previews.length - 1];
		if (seen.length && seen[seen.length - 1].slide === p) break;
		seen.push({ slide: p, page: c.ui.page, count: c.ui.count });
		c.onChangePreviewPage(true);
	}
	c.onBtnPrint(true, false);
	return { first, seen, printed: a.out.printed };
}

function check(name, r, expected) {
	const preview = r.seen.map(s => s.slide);
	assert.deepStrictEqual(r.printed, expected, name + ': printed');
	assert.deepStrictEqual(preview, expected, name + ': preview pages must be the printed slides (preview ' +
		JSON.stringify(preview.map(i => i + 1)) + ', printed ' + JSON.stringify(expected.map(i => i + 1)) + ')');
	r.seen.forEach((s, k) => {
		assert.strictEqual(s.page, k + 1, name + ': page number');
		assert.strictEqual(s.count, expected.length, name + ': "of Y" must count the printed pages');
	});
}

const VISIBLE = [...Array(SLIDES).keys()].filter(i => !HIDDEN.includes(i));

/* 1. all slides: 8 preview pages, 1 of 8 .. 8 of 8, no hidden slide shown */
check('all slides', run(HIDDEN, 0, 'all'), VISIBLE);

/* 2. opened on hidden slide 2: the preview starts at the next printed slide, page 2 */
let r = run(HIDDEN, 1, 'all');
assert.deepStrictEqual([r.first.page, r.first.count], [2, 8], 'opened on a hidden slide');
check('all slides from a hidden one', r, VISIBLE);

/* 3. custom range 1-5: slides 1, 3, 4 */
check('range 1-5', run(HIDDEN, 0, -1, '1-5'), [0, 2, 3]);

/* 4. a range of only the hidden slide 2: an explicit choice, printed and previewed */
check('range 2', run(HIDDEN, 0, -1, '2'), [1]);

/* 5. current slide (hidden slide 5) */
check('current slide', run(HIDDEN, 4, 'current'), [4]);

/* 6. every slide hidden: empty preview that says why, nothing printed */
const ALL = [...Array(SLIDES).keys()];
r = run(ALL, 0, 'all');
assert.strictEqual(r.first.empty, true, 'all hidden: preview box hidden');
assert.strictEqual(r.first.emptyText, 'all slides are hidden');
assert.strictEqual(r.printed, null, 'all hidden: print screen prints nothing');

/* 7. web/cloud PDF (ToRendererPart) */
assert.deepStrictEqual(makeApi(HIDDEN).webPdf(false), VISIBLE, 'web PDF leaves hidden slides out');
assert.deepStrictEqual(makeApi(ALL).webPdf(false), [null], 'web PDF of an all-hidden deck: one blank page');
assert.deepStrictEqual(makeApi(HIDDEN, [1]).webPdf(true), [1], 'web PDF of a selected hidden slide prints it');
assert.deepStrictEqual(makeApi(HIDDEN, [1, 2]).webPdf(true), [2]);

console.log('PASS #1672: print preview shows exactly the slides that are printed' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
