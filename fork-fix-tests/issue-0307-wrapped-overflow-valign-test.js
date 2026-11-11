/*
 * #307 - "Wrong vertical alignment in table cell". The reporter's test1.xlsx is a
 * Russian invoice header: row 2 is 11.1pt high (customHeight) and its cells hold
 * 3-4 line wrapped captions ("Но-\nмер\nпо по-\nрядку") with vertical="center".
 * Excel 2003 and 2016 draw the FIRST line of each caption ("Но-", "Масса",
 * "Количе-", "Сумма без"); we centred the whole block on the 11pt row, so the clip
 * kept the middle of it and cut letters through on both edges ("мер / по по-").
 *
 * Cause: WorksheetView.prototype._drawCellText passed ct.cellVA straight to
 * _calcTextVertPos, whose Center/Dist/Just branch returns
 * y1 + round(0.5 * (h - textHeight)) - a negative offset once the wrapped text is
 * taller than the cell. Fix: for wrapped, unrotated text taller than its cell,
 * Center/Dist/Just are drawn as Top. Top and Bottom are left as they were.
 *
 * Reproduced with x2t (xlsx -> pdf through the real cell sdkjs): before the fix
 * pdftotext -bbox puts "Но-" 4pt above row 2's top edge, clipped; after it "Но-"
 * is the first visible line, as in the reporter's Excel screenshots.
 *
 * This extracts the real _drawCellText, _calcTextVertPos, _calcTextHorizPos and
 * _calcTextWidth from cell/view/WorksheetView.js by brace matching, and the real
 * c_oAscVAlign table from common/commonDefines.js, and runs them against stubs that
 * record where _drawText is asked to draw. Nothing of the logic is copied here.
 *
 * Claimed: wrapped text taller than its cell starts at the cell top for Center (and
 * Dist/Just); text that fits is still centred; Bottom and Top are unchanged.
 * NOT claimed: what Excel does for bottom-aligned overflowing text (not in the
 * report, left as it was), rotated text (excluded), or centerContinuous across
 * B2:D2 / E2:F2 in the same file, which we still draw as left/right - a separate
 * horizontal-alignment gap that this does not touch.
 *
 * RD_REPO overrides the sdkjs checkout. BASELINE=1 reads the sources from git at
 * BASE_REF and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '67b7cbe97c^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function block(text, from, open = '{', close = '}') {
	const start = text.indexOf(open, from);
	let depth = 0;
	for (let i = start; i < text.length; i++) {
		if (text[i] === open) depth++;
		else if (text[i] === close && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced ' + open);
}
function extract(source, marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at) + ';\n';
}

function line(source, marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return source.slice(at, source.indexOf('\n', at) + 1);
}

const ws = src('cell/view/WorksheetView.js');
const defines = src('common/commonDefines.js');

const code =
	extract(defines, 'var c_oAscVAlign = {') +
	line(ws, 'var gridlineSize = ') +
	'function WorksheetView() {}\n' +
	extract(ws, 'WorksheetView.prototype._drawCellText = function') +
	extract(ws, 'WorksheetView.prototype._calcTextHorizPos = function') +
	extract(ws, 'WorksheetView.prototype._calcTextVertPos = function') +
	extract(ws, 'WorksheetView.prototype._calcTextWidth = function') +
	'return { WorksheetView, c_oAscVAlign };';

/* --- stubs: only what the non-rotated branch of _drawCellText touches --- */
const AscCommon = { align_Left: 0, align_Right: 1, align_Center: 2, align_Justify: 3, align_Distributed: 4 };
const Asc = { round: Math.round, Range: function () {}, ECfType: { iconSet: 6 } };
const { WorksheetView, c_oAscVAlign } = new Function('Asc', 'AscCommon', code)(Asc, AscCommon);
Asc.c_oAscVAlign = c_oAscVAlign;

const ROW_TOP = 100, COL_LEFT = 50, COL_W = 40;

// Draws one cell whose text block is textH px tall in a row rowH px high, and
// returns the y the text is drawn at, relative to the row top.
function drawY(va, wrap, textH, rowH) {
	const view = new WorksheetView();
	let drawnAt = null;
	const ct = {
		metrics: { width: 30, height: textH, baseline: textH - 2 },
		cellVA: va, cellHA: AscCommon.align_Center, angle: 0, indent: 0, sideL: 0, sideR: 0, state: {},
		flags: { wrapText: wrap, isMerged: () => false },
	};
	Object.assign(view, {
		nColsCount: 100, nRowsCount: 100, defaultSpaceWidth: 5,
		settings: { cells: { padding: 2 } },
		drawingCtx: {},
		stringRender: { restoreInternalState: () => ({}) },
		workbook: { printPreviewState: { isStart: () => false } },
		model: {
			getSheetView: () => ({ asc_getShowZeros: () => true }),
			getPivotTableButtons: () => null,
			getHyperlinkByCell: () => null,
		},
		_getCellTextCache: () => ct,
		_getVisibleCell: () => ({ getValue: () => 'x', getFont: () => ({ getColor: () => 0, getSize: () => 8 }) }),
		_eraseCellRightBorder() {},
		_getColLeft: (c) => COL_LEFT + (c - 1) * COL_W,
		_getColumnWidth: () => COL_W,
		_getRowTop: (r) => ROW_TOP + (r - 2) * rowH,
		_getRowDescender: () => 2,
		getZoom: () => 1,
		getPrintScale: () => 1,
		getRightToLeft: () => false,
		_getCellCF: () => null,
		_getFilterButtonSize: () => 0,
		_AddClipRect() {},
		_RemoveClipRect() {},
		_drawText(sr, ctx, x, y) { drawnAt = y; },
	});
	view._drawCellText(null, null, 1, 2, 0, 99, 0, 0);
	assert.notStrictEqual(drawnAt, null, '_drawText was not reached');
	return drawnAt - ROW_TOP;
}

const V = c_oAscVAlign;
const results = [];
function check(name, fn) {
	try { fn(); results.push(['PASS', name]); } catch (e) { results.push(['FAIL', name + ': ' + e.message]); }
}

// Row 2 of test1.xlsx at 100%: 11.1pt row ~ 15px, a 4-line 8pt caption ~ 44px.
check('wrapped centred text taller than its row starts at the row top (reporter\'s cells)', () => {
	assert.strictEqual(drawY(V.Center, true, 44, 15), 0);
});
check('distributed/justified overflow also starts at the top', () => {
	assert.strictEqual(drawY(V.Dist, true, 44, 15), 0);
	assert.strictEqual(drawY(V.Just, true, 44, 15), 0);
});
check('wrapped centred text that fits is still centred', () => {
	assert.strictEqual(drawY(V.Center, true, 30, 60), 15);
});
check('unwrapped centred text is not changed', () => {
	assert.strictEqual(drawY(V.Center, false, 44, 15), Math.round(0.5 * (15 - 44)));
});
check('bottom and top alignment are not changed by the fix', () => {
	assert.strictEqual(drawY(V.Top, true, 44, 15), 0);
	// bottom: baseline-based, as before - row bottom - descender - text baseline
	assert.strictEqual(drawY(V.Bottom, true, 44, 15), 15 - 2 - 42);
});

for (const [s, n] of results) console.log(`${s}  ${n}`);
const failed = results.filter(r => r[0] === 'FAIL').length;
console.log(failed ? `${failed} of ${results.length} FAILED` : `all ${results.length} passed`);
process.exit(failed ? 1 : 0);
