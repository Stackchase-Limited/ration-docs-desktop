/*
 * #1672 - saving a presentation as PDF (and printing it from the desktop app)
 * included the slides the author had hidden (<p:sld show="0">).
 *
 * Only the slideshow and the web download (DrawingDocument.ToRendererPart)
 * looked at Slide.isVisible(). asc_nativeGetPDF in slide/api.js - what
 * x2t/doctrenderer runs for pptx -> pdf, and so for the desktop's Save as /
 * Download as PDF - looped over every slide, and so did the desktop print
 * branch of asc_nativePrint. Our x2t turned a 10-slide deck with two hidden
 * slides into a 10-page PDF. PowerPoint leaves hidden slides out unless
 * "Print hidden slides" is ticked; we have no such option.
 *
 * This extracts by brace matching the REAL asc_nativeGetPDF, asc_nativePrint,
 * _printDesktop and (on the fixed tree) getSlidesToPrint from slide/api.js and
 * the real getNativePrintRanges from common/editorscommon.js, and drives them
 * with a stub presentation of 10 slides of which slides 2 and 5 are hidden.
 * The desktop print round trip is emulated as the desktop does it: the JSON
 * from AscDesktopEditor.Print comes back as asc_nativePrint's options, and
 * nativeOptions.pages is applied to the received pages BY POSITION
 * (desktop-apps win-linux/src/cprintdata.cpp).
 *
 * Claimed: PDF has no hidden slide (whole deck and ranges); a range made only of
 * hidden slides prints them (explicit choice); image export keeps every slide;
 * an all-hidden deck gives one blank page; desktop print skips hidden slides
 * and a page range / selection still lands on the right slides.
 * NOT claimed: real rendering, the desktop print dialog or the GUI's Save as
 * PDF (x2t was run on a real pptx for the commit; GUI print needs a manual
 * check).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the sources at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'c32ac680e4^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
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

const api = src('slide/api.js');
const common = src('common/editorscommon.js');

const code =
	extract(common, 'function getNativePrintRanges(') +
	'AscCommon.getNativePrintRanges = getNativePrintRanges;\n' +
	extract(api, 'asc_docs_api.prototype.getSlidesToPrint = function', true) +
	extract(api, 'asc_docs_api.prototype._printDesktop = function') +
	extract(api, 'window["asc_docs_api"].prototype["asc_nativePrint"] = function') +
	extract(api, 'window["asc_docs_api"].prototype["asc_nativePrintPagesCount"] = function') +
	extract(api, 'window["asc_docs_api"].prototype["asc_nativeGetPDF"] = function');

/* --- stubs --- */
const SLIDES = 10;
const W = 254, H = 142.875;

function makeApi(hidden, selected) {
	const window = {};
	const AscCommon = {};
	function asc_docs_api() {}
	window['asc_docs_api'] = asc_docs_api;

	const out = { pages: [], printStart: null, nativeJson: null };
	let current = null;
	function Renderer() {
		this.Memory = { Seek() {}, GetBase64Memory() { return ''; }, GetCurPosition() { return 0; }, data: null };
		this.VectorMemoryForPrint = { ClearNoAttack() {} };
	}
	Renderer.prototype.InitPicker = function () {};
	Renderer.prototype.DocInfo = function () {};
	Renderer.prototype.BeginPage = function () { current = { slide: null }; };
	Renderer.prototype.EndPage = function () { out.pages.push(current.slide); current = null; };
	AscCommon.CDocumentRenderer = Renderer;
	AscCommon.CMemory = function () { this.ClearNoAttack = function () {}; };
	AscCommon.g_oTextMeasurer = { m_oManager: null };
	AscCommon.CWatermarkOnDraw = function () {};

	const logic = {
		IsVisibleSlide: i => i >= 0 && i < SLIDES && !hidden.includes(i),
		GetWidthMM: () => W,
		GetHeightMM: () => H,
		DrawPage: (i, r) => { current.slide = i; },
	};
	const Asc = { c_oAscPrintType: { EntireDocument: 0, Selection: 1 } };
	window['native'] = { Save_End() {} };

	new Function('window', 'asc_docs_api', 'AscCommon', 'Asc', code)(window, asc_docs_api, AscCommon, Asc);

	const a = new asc_docs_api();
	a.WordControl = {
		GetSlidesCount: () => SLIDES,
		m_oLogicDocument: logic,
		m_oDrawingDocument: { GetSlidesCount: () => SLIDES, m_oLogicDocument: logic },
		Thumbnails: {
			isSelectedPage: i => (selected || []).includes(i),
			GetSelectedArray: () => selected || [],
		},
	};
	a.ShowParaMarks = false;
	a.DocumentUrl = '';
	a.ThemeLoader = { ThemesUrl: '' };
	a.getCurrentPage = () => 5;
	a.asc_getCoreProps = () => null;
	a.out = out;
	a.window = window;
	return a;
}

function pdf(hidden, options) {
	const a = makeApi(hidden);
	a['asc_nativeGetPDF'](options);
	return a.out.pages;
}

/* The desktop round trip: Print(json) -> asc_nativePrint(undefined, undefined, json)
   -> pages -> the desktop applies nativeOptions.pages to them by position. */
function desktopPrint(hidden, nativeOptions, selected) {
	const a = makeApi(hidden, selected);
	a.window['AscDesktopEditor'] = {
		Print(json) { a.out.nativeJson = json; a['asc_nativePrint'](undefined, undefined, JSON.parse(json)); },
		Print_Start(url, count, themes, cur) { a.out.printStart = { count, cur }; },
		Print_Page() {},
		Print_End() {},
	};
	const advancedOptions = {
		asc_getPrintType: () => (selected ? 1 : 0),
		asc_getNativeOptions: () => nativeOptions,
	};
	a._printDesktop({ advancedOptions });
	const sent = a.out.pages;
	const range = (JSON.parse(a.out.nativeJson).nativeOptions || {}).pages;
	if (!range || range === 'all')
		return { sent, printed: sent, start: a.out.printStart };
	const pos = new Set();
	for (const r of range.split(',')) {
		const [s, e] = r.split('-').map(Number);
		for (let p = s; p <= (e || s); p++) pos.add(p);
	}
	return { sent, printed: sent.filter((_, k) => pos.has(k + 1)), start: a.out.printStart };
}

const HIDDEN = [1, 4]; // slides 2 and 5
const ALL = [...Array(SLIDES).keys()];
const VISIBLE = ALL.filter(i => !HIDDEN.includes(i));

/* 1. x2t / desktop Save as PDF of the whole deck */
assert.deepStrictEqual(pdf(HIDDEN, null), VISIBLE, 'PDF must leave the hidden slides 2 and 5 out');

/* 2. a range: slides 1-3 -> 1 and 3 */
assert.deepStrictEqual(pdf(HIDDEN, { nativeOptions: { pages: '1-3' } }), [0, 2]);

/* 3. a range made only of a hidden slide is an explicit choice */
assert.deepStrictEqual(pdf(HIDDEN, { nativeOptions: { pages: '2' } }), [1]);

/* 4. export to images and the first-page thumbnail keep every slide */
assert.deepStrictEqual(pdf(HIDDEN, { saveFormat: 'image' }), ALL);
assert.deepStrictEqual(pdf([0], { printOptions: { onlyFirstPage: true } }), [0]);

/* 5. every slide hidden: one blank page, nothing drawn */
assert.deepStrictEqual(pdf(ALL, null), [null]);

/* 6. desktop print of the whole deck */
let r = desktopPrint(HIDDEN, { pages: 'all' });
assert.deepStrictEqual(r.printed, VISIBLE, 'desktop print must leave hidden slides out');
assert.strictEqual(r.start.count, VISIBLE.length);
assert.strictEqual(r.start.cur, VISIBLE.indexOf(5), 'current slide is passed as its position among the printed pages');

/* 7. desktop print of slides 3-6: the hidden 5 is skipped, the range still means slide numbers */
r = desktopPrint(HIDDEN, { pages: '3-6' });
assert.deepStrictEqual(r.printed, [2, 3, 5], 'range must land on slides 3, 4 and 6');

/* 8. desktop print of the thumbnail selection {2, 3}: slide 2 is hidden */
r = desktopPrint(HIDDEN, { pages: 'all' }, [1, 2]);
assert.deepStrictEqual(r.printed, [2]);

console.log('PASS #1672: hidden slides stay out of PDF export and desktop print' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
