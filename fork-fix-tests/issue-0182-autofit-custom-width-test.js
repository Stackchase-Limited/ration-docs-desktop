/*
 * DesktopEditors #182 - "Need to apply auto column resize two times".
 *
 * Reproduction as filed (the reporter's issue_auto_resize.xlsx): double-click the
 * divider after column A. The first autofit makes the column NARROWER than the
 * numbers in it; a second autofit gives the right width. The file's columns carry
 * customWidth="1", as any width set by hand or written by Excel/LibreOffice does.
 * In the real editor (9.4 sdkjs, headless) that file gave, for column A:
 * open 96px -> autofit 95px -> autofit 99px; after the fix 96 -> 99 -> 99.
 *
 * Cause (cell/view/WorksheetView.js, _addCellTextToCache): a number is formatted
 * to fit the width it is drawn in - when the full text does not fit, the number
 * formatter falls back to fewer decimals (or ###) through the
 * makeFnIsGoodNumFormat check. Only when the column width is NOT custom does the
 * function first widen the column to the full text. _autoFitColumnWidth uses the
 * same function to measure, so on a custom-width column it measured the text as
 * shortened for the current width and set the column to that. setColBestFit
 * clears customWidth, so the second autofit took the widening branch and measured
 * the full number.
 *
 * Fix: while autofit runs (canChangeColWidth === all, set only by
 * _autoFitColumnWidth) the custom width does not block that branch.
 *
 * This extracts the REAL _autoFitColumnWidth, _addCellTextToCache and
 * _changeColWidth and runs them against a stub view/model/cell. The stub number
 * formatter behaves like the real one in the one way that matters: it returns the
 * longest candidate text that passes the width check it is given. Glyphs are
 * 7px wide.
 *
 * Claimed: one autofit on a custom-width column gives the width of the full
 *   number, and a second autofit does not change it; a custom-width column that
 *   is too WIDE still shrinks in one go; drawing a custom-width column outside
 *   autofit still shortens the number to fit and does not touch the width.
 * NOT claimed: pixel-exact widths of real fonts (verified separately in the
 *   headless editor, numbers above), rotated or merged cells.
 *
 *   node fork-fix-tests/issue-0182-autofit-custom-width-test.js
 *   BASELINE=1 node fork-fix-tests/issue-0182-autofit-custom-width-test.js   # must fail
 *   RD_REPO=<sdkjs checkout> overrides ../sdkjs; BASE_REF overrides the baseline.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/view/WorksheetView.js';
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '2c08a678ee^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function grab(assign) {
	const at = source.indexOf(assign);
	assert.notStrictEqual(at, -1, 'not found in ' + REL + ': ' + assign);
	return matched(source, at + assign.length);
}
const srcAutoFit = grab('WorksheetView.prototype._autoFitColumnWidth = function');
const srcAddText = grab('WorksheetView.prototype._addCellTextToCache = function');
const srcChangeW = grab('WorksheetView.prototype._changeColWidth = function');
assert.ok(srcAutoFit.indexOf('this._addCellTextToCache(col, row)') !== -1, 'wrong _autoFitColumnWidth');
assert.ok(srcAddText.indexOf('makeFnIsGoodNumFormat') !== -1, 'wrong _addCellTextToCache');
assert.ok(srcChangeW.indexOf('setColBestFit') !== -1, 'wrong _changeColWidth');

/* --- constants, as the product defines them --- */
const c_oAscCanChangeColWidth = { none: 0, numbers: 1, all: 2 };  // cell/apiDefines.js
const c_oAscMergeType = { none: 0, cols: 1, rows: 2 };            // cell/apiDefines.js
const CellValueType = { Number: 0, String: 1, Bool: 2, Error: 3 }; // common/commonDefines.js
const gc_nMaxDigCountView = 15;                                    // common/commonDefines.js
const gridlineSize = 1;                                            // WorksheetView.js
const GLYPH_PX = 7;
const PADDING = 2;                     // settings.cells.padding
const PAD = PADDING * 2 + 1;

const Asc = { c_oAscMaxColumnWidth: 255, c_oAscVAlign: { Bottom: 0, Center: 1, Top: 4 },
	isFixedWidthCell: function () { return false; } };
const AscCommon = { align_Left: 0, align_Right: 1, align_Center: 2, align_Distributed: 4 };
const AscCommonExcel = { g_nVerticalTextAngle: 255, dropDecimalAutofit: function (s) { return s; },
	g_oCacheMeasureEmpty: { get: function () {}, add: function () {} } };
const History = { Create_NewPoint() {}, StartTransaction() {}, EndTransaction() {} };
function CacheElementText() {}

function text(frags) { return frags.map(function (f) { return f.text; }).join(''); }

/* A number cell. getValue2 with no check returns the full text; with a check it
 * returns the longest candidate that passes, which is what the real formatter
 * does when it drops decimals to make a number fit. */
function NumberCell(candidates) { this.candidates = candidates; }
NumberCell.prototype.getValue2 = function (dDigitsCount, fIsFitMeasurer) {
	const frag = (t) => [{ text: t, format: {} }];
	if (!fIsFitMeasurer) return frag(this.candidates[0]);
	for (const t of this.candidates) {
		if (fIsFitMeasurer(frag(t))) return frag(t);
	}
	return frag('#');
};
NumberCell.prototype.getType = function () { return CellValueType.Number; };
NumberCell.prototype.getNumFormatStr = function () { return '_-* #,##0.00\\ "€"_-'; };
NumberCell.prototype.isEmptyTextString = function () { return false; };
NumberCell.prototype.isFormula = function () { return false; };
NumberCell.prototype.getAlign = function () {
	return { hor: null, getAlignVertical() { return null; }, getAngle() { return 0; },
		getIndent() { return 0; }, getAlignHorizontal() { return null; } };
};
NumberCell.prototype.getAlignHorizontalByValue = function () { return AscCommon.align_Right; };

function Flags() { this.wrapText = false; this.shrinkToFit = false; this.merged = null; }
Flags.prototype.getMergeType = function () { return c_oAscMergeType.none; };
Flags.prototype.isMerged = function () { return false; };
Flags.prototype.clone = function () { const f = new Flags(); Object.assign(f, this); return f; };

/* one column (0) with one number cell in row 0 */
function makeView(widthChars, customWidth, candidates) {
	const col = { chars: widthChars, custom: customWidth, bestFitCalls: 0 };
	const cell = new NumberCell(candidates);
	const cache = {};
	const model = {
		getColCustomWidth: () => col.custom,
		getRowCustomHeight: () => false,
		getSheetView: () => null,
		isUserProtectedRangesCanView: () => true,
		getRowsCount: () => 1,
		getColDataNoEmpty: () => ({ getMinIndex: () => 0, getMaxIndex: () => 0 }),
		colWidthToCharCount: (px) => px / GLYPH_PX,
		charCountToModelColWidth: (cc) => cc,
		setColBestFit: (bBestFit, w) => { col.chars = w; col.custom = false; col.bestFitCalls++; }
	};
	const view = {
		model: model, col: col, cache: cache,
		canChangeColWidth: c_oAscCanChangeColWidth.none,
		maxRowHeightPx: 4096, maxDigitWidth: GLYPH_PX, defaultColWidthChars: 8.43,
		defaultSpaceWidth: 3, isZooming: false, nRowsCount: 1, cols: [{}], rows: [{}],
		settings: { cells: { padding: PADDING } },
		workbook: { printPreviewState: null },
		stringRender: {
			measureString: (str) => ({ width: GLYPH_PX * text(str).length, height: 15 }),
			getInternalState: () => ({}),
		},
		getZoom: () => 1, getRetinaPixelRatio: () => 1,
		getColumnWidthInSymbols: () => col.chars,
		_getColumnWidth: () => Math.round(col.chars * GLYPH_PX) + PAD,
		_getColumnWidthInner: () => Math.round(col.chars * GLYPH_PX),
		_getColumnWidthIgnoreHidden: () => Math.round(col.chars * GLYPH_PX) + PAD,
		_calcColWidth: () => {},
		_getCell: () => cell,
		_getCellFlags: () => new Flags(),
		_roundTextMetrics: (tm) => tm,
		_getRowHeight: () => 20,
		_calcMaxWidth: () => Math.round(col.chars * GLYPH_PX),
		_calcCellTextOffset: (c, r, ha, w) => ({ maxWidth: w, leftSide: 0, rightSide: 0 }),
		_fetchCellCache: (c, r) => (cache[c + ':' + r] = cache[c + ':' + r] || new CacheElementText()),
		_fetchCellCacheText: () => {},
		_getCellTextCache: (c, r) => cache[c + ':' + r],
		_addErasedBordersToCache: () => {},
		_updateRowHeight: () => {},
		_checkFilterButtonInRange: () => false,
	};
	new Function('view', 'asc', 'Asc', 'AscCommon', 'AscCommonExcel', 'CellValueType', 'c_oAscCanChangeColWidth',
		'c_oAscMergeType', 'gc_nMaxDigCountView', 'gridlineSize', 'History', 'CacheElementText',
		'"use strict";\n' +
		'view._autoFitColumnWidth = function' + srcAutoFit + ';\n' +
		'view._addCellTextToCache = function' + srcAddText + ';\n' +
		'view._changeColWidth = function' + srcChangeW + ';\n')(
		view, Asc, Asc, AscCommon, AscCommonExcel, CellValueType, c_oAscCanChangeColWidth,
		c_oAscMergeType, gc_nMaxDigCountView, gridlineSize, History, CacheElementText);
	return view;
}

const FULL = '207,359.84 €';           // 12 glyphs = 84px
const CANDIDATES = [FULL, '207,360 €', '2E+05'];
const FULL_FIT = (GLYPH_PX * FULL.length + PAD) / GLYPH_PX;   // chars autofit should set
const near = (a, b) => Math.abs(a - b) < 1e-9;
let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

/* 0. harness: a column that is NOT custom gets the full width in one autofit (both trees). */
check('non-custom narrow column: one autofit fits the full number', () => {
	const v = makeView(11, false, CANDIDATES);
	v._autoFitColumnWidth(0, null, null, false, []);
	assert.ok(near(v.col.chars, FULL_FIT), 'width ' + v.col.chars + ', expected ' + FULL_FIT);
});

/* 1. the bug: custom width narrower than the full number. */
check('custom-width narrow column: first autofit fits the full number', () => {
	const v = makeView(11, true, CANDIDATES);
	v._autoFitColumnWidth(0, null, null, false, []);
	const first = v.col.chars;
	v._autoFitColumnWidth(0, null, null, false, []);
	const second = v.col.chars;
	assert.ok(near(first, FULL_FIT),
		'first autofit set ' + first.toFixed(3) + ' chars (measured a shortened number), the full number needs ' +
		FULL_FIT.toFixed(3) + '; second autofit gave ' + second.toFixed(3));
	assert.ok(near(second, first), 'second autofit changed the width again: ' + first + ' -> ' + second);
});

/* 2. custom width wider than needed still shrinks in one go. */
check('custom-width wide column: one autofit shrinks to the full number', () => {
	const v = makeView(20, true, CANDIDATES);
	v._autoFitColumnWidth(0, null, null, false, []);
	assert.ok(near(v.col.chars, FULL_FIT), 'width ' + v.col.chars + ', expected ' + FULL_FIT);
});

/* 3. outside autofit a custom-width column is drawn as before: number shortened to
      fit, column width untouched. */
check('custom-width column outside autofit: text shortened, width untouched', () => {
	for (const mode of [c_oAscCanChangeColWidth.none, c_oAscCanChangeColWidth.numbers]) {
		const v = makeView(11, true, CANDIDATES);
		v.canChangeColWidth = mode;
		v._addCellTextToCache(0, 0);
		assert.strictEqual(v.col.chars, 11, 'width changed in mode ' + mode);
		assert.strictEqual(v.col.custom, true, 'customWidth cleared in mode ' + mode);
		assert.strictEqual(v.col.bestFitCalls, 0, 'setColBestFit called in mode ' + mode);
		assert.strictEqual(v.cache['0:0'].metrics.width, GLYPH_PX * '207,360 €'.length,
			'cell text not shortened to the custom width in mode ' + mode);
	}
});

if (failures) {
	console.log(failures + ' check(s) failed' + (process.env.BASELINE ? ' (BASELINE=1: expected)' : ''));
	process.exit(1);
}
console.log('all checks passed');
