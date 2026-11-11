/*
 * #531 - a PDF of a spreadsheet filtered in the current session, with "fit to
 * page" on, came out shrunk as if the filtered-out rows were still there. A
 * 170-row table filtered down to 38 rows printed at about 28% - the scale 170
 * rows would need. Saving, closing and reopening the file made it go away.
 *
 * The desktop's PDF is made by x2t replaying the session's changes onto the
 * Editor.bin written at open. Hiding rows goes through WorksheetView._updateRange
 * with a RangeMax range, which empties the row/column caches and leaves the
 * rebuild to the next draw; the converter never draws. _calcPagesPrint rebuilds
 * empty caches under NATIVE_EDITOR_ENJINE, but calcPrintScale runs before it, and
 * with an empty row cache _getHeightForPrint counts every row at the default
 * height - hidden or not.
 *
 * This extracts by brace matching the REAL calcPrintScale, _getHeightForPrint,
 * _getWidthForPrint, _calcHeightRows, _calcHeightRow and CacheRow from
 * cell/view/WorksheetView.js and runs calcPrintScale(1, 1) on a stub sheet of 170
 * rows, 132 of them hidden, with the row cache empty as x2t leaves it.
 *
 * Claimed: the fit-to-1x1 scale counts only visible rows (100% here, the 38 rows
 * fit), and a sheet with no hidden rows still scales down (control).
 * NOT claimed: real rendering or page layout. The whole chain (headless editor
 * builds and filters the table, plain save, x2t replays to PDF) was run for the
 * commit: last row at y=206pt before, y=598pt after.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the source at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'df3a283c13^';
const REL = 'cell/view/WorksheetView.js';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at) + ';\n';
}

const code =
	extract('function CacheRow() {') +
	extract('CacheRow.prototype.setHeight = function') +
	extract('WorksheetView.prototype._getWidthForPrint = function') +
	extract('WorksheetView.prototype._getHeightForPrint = function') +
	extract('WorksheetView.prototype._calcHeightRow = function') +
	extract('WorksheetView.prototype._calcHeightRows = function') +
	extract('WorksheetView.prototype.calcPrintScale = function');

/* --- stubs: only what those functions touch --- */
const ROWS = 170, COLS = 2, ROW_PT = 15;
function asc_CPageSetup() {}
const c_oAscPrintDefaultSettings = {
	PageWidth: 210, PageHeight: 297, PageOrientation: 0,
	PageLeftField: 17.8, PageRightField: 17.8, PageTopField: 19.1, PageBottomField: 19.1,
	MinPageLeftField: 0.17, MinPageRightField: 0.17, MinPageTopField: 0.17, MinPageBottomField: 0.17,
	PageGridLines: false, PageHeadings: false,
};
const AscBrowser = { retinaPixelRatio: 1 };
const AscCommon = { AscBrowser: { isCustomScaling: () => false } };
const AscCommonExcel = {
	vector_koef: 25.4 / 96,
	convertPtToPx: (pt) => pt * 96 / 72,
	recalcType: { recalc: 0, full: 1, newLines: 2 },
	oDefaultMetrics: { RowHeight: ROW_PT },
	executeInR1C1Mode: (b, f) => f(),
};
const Asc = { round: Math.round, c_oAscPageOrientation: { PageLandscape: 1 } };
const window = { NATIVE_EDITOR_ENJINE: true };
const gc_nMaxRow = 1048576;
function asc_Range(c1, r1, c2, r2) { Object.assign(this, { c1, r1, c2, r2 }); }
const asc_typeof = (o) => typeof o;

function WorksheetView() {}
new Function('WorksheetView', 'asc_CPageSetup', 'c_oAscPrintDefaultSettings', 'AscBrowser', 'AscCommon',
	'AscCommonExcel', 'Asc', 'window', 'gc_nMaxRow', 'asc_Range', 'asc_typeof',
	'"use strict";\n' + code)(WorksheetView, asc_CPageSetup, c_oAscPrintDefaultSettings, AscBrowser, AscCommon,
	AscCommonExcel, Asc, window, gc_nMaxRow, asc_Range, asc_typeof);

/* A sheet as x2t has it after replaying a filter: model rows hidden, view caches empty. */
function sheet(hidden) {
	const v = new WorksheetView();
	v.model = {
		PagePrintOptions: null,
		getId: () => 0,
		getRowsCount: () => ROWS,
		getColsCount: () => COLS,
		isDefaultHeightHidden: () => false,
		isDefaultWidthHidden: () => false,
		_getRowNoEmptyWithAll(i, f) { f({ getHidden: () => hidden(i), h: ROW_PT, getCustomHeight: () => false, getCalcHeight: () => false }); },
		workbook: { getDefinesNames: () => null },
		getSparkLinesMaxColRow: () => ({ col: -1, row: -1 }),
		autoFilters: { getMaxColRow: () => ({ col: -1, row: -1 }) },
	};
	v.rows = [];
	v.cols = [];
	v.cellsLeft = 0; v.cellsTop = 0;
	v.defaultRowHeightForPrintPt = ROW_PT;
	v.defaultColWidthPxForPrint = 64;
	v.defaultRowDescender = 3;
	v.workbook = { printPreviewState: { isStart: () => false } };
	v.getZoom = () => 1;
	v.getRetinaPixelRatio = () => 1;
	v._getRowTop = () => 0;
	v._getRowHeight = (i) => v.rows[i] ? v.rows[i].height : 20;
	// Columns are not what #531 is about; a stand-in that fills the cache like the real one.
	v._calcWidthColumns = () => { for (let i = v.cols.length; i < COLS; i++) v.cols[i] = { _widthForPrint: 64 }; };
	v._calculateMaxPrintRange = () => ({ col: COLS - 1, row: ROWS - 1 });
	return v;
}

/* Control: nothing hidden, 170 rows do not fit on one A4 page, so the scale drops. */
const all = sheet(() => false).calcPrintScale(1, 1);
assert.ok(all < 50, `control: 170 visible rows must scale well below 100%, got ${all}`);

/* The defect: header + 37 visible rows (as in the report), 132 hidden by the filter. */
const visible = (i) => i === 0 || (i >= 77 && i <= 113);
const v = sheet((i) => !visible(i));
const scale = v.calcPrintScale(1, 1);
assert.strictEqual(scale, 100,
	`fit-to-page scale ${scale}% for 38 visible rows: the rows hidden by the filter were counted ` +
	`(170 rows at ${all}% is what they would need)`);
assert.strictEqual(v.rows.length, ROWS, 'the row cache must be rebuilt from the model');
assert.strictEqual(v.rows[5]._heightForPrint, 0, 'a hidden row must contribute no height');

console.log(`ok - fit-to-page scale counts only visible rows (filtered: ${scale}%, unfiltered control: ${all}%)`);
