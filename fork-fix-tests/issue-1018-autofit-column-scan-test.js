/*
 * DesktopEditors #1018 - "DesktopEditors hangup when applying autofit in big xlsx file".
 *
 * Reproduction as filed: open a big xlsx, select the first 4 columns, apply
 * "AutoFit column width". The editor stops responding.
 *
 * asc_autoFitColumnWidth -> WorksheetView.autoFitColumnsWidth builds, for every
 * selected range, a range whose rows are 0 .. model.getRowsCount()-1, and
 * _autoFitColumnsWidth hands each column to _autoFitColumnWidth, whose body is a
 * DENSE index loop (cell/view/WorksheetView.js):
 *
 *     if (null == r2) { r2 = this.model.getRowsCount() - 1; }
 *     ...
 *     for (row = r1; row <= r2; ++row) {
 *         this._addCellTextToCache(col, row);
 *         ct = this._getCellTextCache(col, row);
 *         if (ct === undefined) { continue; }
 *         ...
 *     }
 *
 * Worksheet.getRowsCount() is the sheet's ROW EXTENT, not a cell count: it is
 * raised by every Row record (Worksheet._initRow, cell/model/Workbook.js) and by
 * rowsData.getMaxIndex(), so a workbook whose rows carry whole-sheet formatting
 * reports 1048576 even when the columns hold a hundred values. Autofitting four
 * columns then runs _addCellTextToCache 4 * 1048576 times - and every one of those
 * calls builds a Range, builds a CellFlags, and asks the merge manager - to read
 * four hundred cells.
 *
 * The rows with no cell cannot contribute anything: _addCellTextToCache returns at
 * "if (c.isEmptyTextString())" before it reaches any measuring or any
 * _changeColWidth, it leaves nothing in the text cache, so _getCellTextCache
 * returns undefined and the loop body does "continue". The scan is pure waste.
 *
 * The fix clamps the loop to the column's own cell extent - the same bound
 * Range._foreachNoEmptyByCol uses (colData.getMinIndex()/getMaxIndex(),
 * cell/model/SheetMemory.js).
 *
 * This test extracts the real _autoFitColumnWidth, _autoFitColumnsWidth,
 * _getCellTextCache and _getCellCache from cell/view/WorksheetView.js by brace
 * matching and drives them against a stub worksheet whose column store mirrors
 * SheetMemory (indexA/indexB) and whose _addCellTextToCache reproduces the real
 * one's observable contract: a cell with text lands in the cache, an empty one
 * does not.
 *
 * Section 1 and section 2 are harness/behaviour checks and pass in both trees.
 * Section 3 is the complexity claim and FAILS with BASELINE=1.
 *
 *   node fork-fix-tests/issue-1018-autofit-column-scan-test.js
 *   BASELINE=1 node fork-fix-tests/issue-1018-autofit-column-scan-test.js   # must fail
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL_WSV = 'cell/view/WorksheetView.js';
// Pinned to the commit this fix landed on top of. It must NOT default to HEAD:
// once the fix is committed, HEAD carries it, the baseline stops differing and
// the test quietly becomes toothless while still reporting success.
const BASE_REF = process.env.BASE_REF || 'b98bcb7c0106504261863c483e7f1fd8172af82b';

function readGit(rel) {
	return execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 });
}
function read(rel) {
	return process.env.BASELINE ? readGit(rel) : fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
const srcWsv = read(REL_WSV);
/* section 3 runs the working tree and BASE_REF against each other in one process */
const srcWsvBase = readGit(REL_WSV);

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function grabFn(source, rel, assign) {
	const at = source.indexOf(assign);
	assert.notStrictEqual(at, -1, 'not found in ' + rel + ': ' + assign);
	return matched(source, at + assign.length);
}

/* --- the real code under test --- */
function extract(source) {
	const fns = {
		autoFitCol:  grabFn(source, REL_WSV, 'WorksheetView.prototype._autoFitColumnWidth = function'),
		autoFitCols: grabFn(source, REL_WSV, 'WorksheetView.prototype._autoFitColumnsWidth = function'),
		cellCache:   grabFn(source, REL_WSV, 'WorksheetView.prototype._getCellCache = function'),
		textCache:   grabFn(source, REL_WSV, 'WorksheetView.prototype._getCellTextCache = function')
	};
	/* guard against extracting the wrong thing */
	assert.ok(fns.autoFitCol.indexOf('this._addCellTextToCache(col, row)') !== -1,
		'extracted the wrong _autoFitColumnWidth');
	assert.ok(fns.autoFitCol.indexOf('this.model.getRowsCount() - 1') !== -1,
		'extracted the wrong _autoFitColumnWidth');
	assert.ok(fns.autoFitCols.indexOf('this._autoFitColumnWidth(') !== -1,
		'extracted the wrong _autoFitColumnsWidth');
	assert.ok(fns.textCache.indexOf('getMergedByCell') !== -1,
		'extracted the wrong _getCellTextCache');
	return fns;
}
const FNS = extract(srcWsv);
const FNS_BASE = extract(srcWsvBase);

/* --- constants, copied from where the product defines them --- */
/* cell/apiDefines.js:211 */
const c_oAscCanChangeColWidth = { none: 0, numbers: 1, all: 2 };
/* common/commonDefines.js:657 */
const CellValueType = { Number: 0, String: 1, Bool: 2, Error: 3 };
/* common/commonDefines.js:454 */
const c_oAscMaxColumnWidth = 255;
const gc_nMaxRow0 = 1048576 - 1;
const gc_nMaxCol0 = 16384 - 1;

/* --- stubs --- */
function Range(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
const Asc = { Range: function (c1, r1, c2, r2) { return new Range(c1, r1, c2, r2); } };
Asc.Range.prototype = Range.prototype;
/* _autoFitColumnWidth reads the cap off Asc, not off the file-local alias */
Asc.c_oAscMaxColumnWidth = c_oAscMaxColumnWidth;

const History = {
	Create_NewPoint: function () {},
	StartTransaction: function () {},
	EndTransaction: function () {}
};

/* mirrors SheetMemory: indexA/indexB are -1 until a cell is written (cell/model/SheetMemory.js) */
function ColData() { this.indexA = -1; this.indexB = -1; }
ColData.prototype.checkIndex = function (i) {
	if (this.indexA === -1) { this.indexA = this.indexB = i; return; }
	if (i < this.indexA) this.indexA = i;
	if (i > this.indexB) this.indexB = i;
};
ColData.prototype.getMinIndex = function () { return this.indexA; };
ColData.prototype.getMaxIndex = function () { return this.indexB; };

/* one measurable "glyph" is 7px wide, so a string's width is 7 * length */
const GLYPH_PX = 7;

function Model() {
	this.cells = [];               // cells[col][row] = {text, type} for cells that exist
	this.cellsByCol = [];          // col -> ColData, the real name and shape
	this.cellsByColRowsCount = 0;
	this.nRowsCount = 0;           // the ROW EXTENT, what getRowsCount() returns
	this.nColsCount = 0;
	this.colWidthChars = [];       // col -> width in chars
	this.bestFit = {};             // col -> width last handed to setColBestFit
	this.merges = [];              // {c1, r1, c2, r2}
	this.selectionRange = { ranges: [] };
}
Model.prototype.setCell = function (col, row, text, type) {
	if (!this.cells[col]) this.cells[col] = [];
	this.cells[col][row] = { text: text, type: (type === undefined ? CellValueType.String : type) };
	this.getColData(col).checkIndex(row);
	this.cellsByColRowsCount = Math.max(this.cellsByColRowsCount, row + 1);
	this.nRowsCount = Math.max(this.nRowsCount, row + 1);
	this.nColsCount = Math.max(this.nColsCount, col + 1);
};
/* what a Row record does to the extent - Worksheet._initRow, cell/model/Workbook.js */
Model.prototype.addRowRecord = function (row) {
	this.nRowsCount = Math.max(this.nRowsCount, row + 1);
};
Model.prototype.getColData = function (i) {
	if (!this.cellsByCol[i]) this.cellsByCol[i] = new ColData();
	return this.cellsByCol[i];
};
Model.prototype.getColDataNoEmpty = function (i) { return this.cellsByCol[i]; };
Model.prototype.getColDataLength = function () { return this.cellsByCol.length; };
Model.prototype.getRowsCount = function () { return this.nRowsCount; };
Model.prototype.getColsCount = function () { return this.nColsCount; };
Model.prototype.getPivotTableButtons = function () { return []; };
/* the anchor (mc.c1, mc.r1) keeps its cell; the covered coordinates do not */
Model.prototype.addMerge = function (c1, r1, c2, r2, text) {
	this.merges.push({ c1: c1, r1: r1, c2: c2, r2: r2 });
	this.setCell(c1, r1, text);
	this.nRowsCount = Math.max(this.nRowsCount, r2 + 1);
	this.nColsCount = Math.max(this.nColsCount, c2 + 1);
};
Model.prototype.getMergedByCell = function (row, col) {
	for (const m of this.merges) {
		if (m.c1 <= col && col <= m.c2 && m.r1 <= row && row <= m.r2) { return m; }
	}
	return null;
};
Model.prototype.colWidthToCharCount = function (px) { return px / GLYPH_PX; };
Model.prototype.charCountToModelColWidth = function (cc) { return cc; };
Model.prototype.setColBestFit = function (bBestFit, width, start, stop) {
	for (let c = start; c <= stop; ++c) {
		this.bestFit[c] = width;
		this.colWidthChars[c] = width;
	}
};

function View(model) {
	this.model = model;
	this.cache = { rows: [] };
	this.cols = [];
	this.canChangeColWidth = c_oAscCanChangeColWidth.none;
	this.maxRowHeightPx = 409;
	this.maxDigitWidth = GLYPH_PX;
	this.defaultColWidthChars = 8.43;
	this.settings = { cells: { padding: 2 } };
	this.stringRender = { measureString: function () { throw new Error('unexpected re-measure'); } };
	/* instrumentation */
	this.visits = 0;        // _addCellTextToCache calls = rows the loop touched
	this.hits = 0;          // of those, rows that actually had a cell
	this.calcColWidth = 0;
}
View.prototype.getZoom = function () { return 1; };
View.prototype.getRetinaPixelRatio = function () { return 1; };
View.prototype.getColumnWidthInSymbols = function (col) {
	const w = this.model.colWidthChars[col];
	return w === undefined ? this.defaultColWidthChars : w;
};
View.prototype._calcColWidth = function () { this.calcColWidth++; };
View.prototype._checkFilterButtonInRange = function () { return false; };
View.prototype._getFilterButtonSize = function () { return 12; };
View.prototype._getCell = function (col, row) {
	const c = this.model.cells[col] && this.model.cells[col][row];
	return c || null;
};
View.prototype._roundTextMetrics = function (tm) { return tm; };
View.prototype._fetchCellCache = function (col, row) {
	let r = this.cache.rows[row];
	if (!r) { r = this.cache.rows[row] = { columns: [], columnsWithText: [] }; }
	let c = r.columns[col];
	if (!c) { c = r.columns[col] = {}; }
	return c;
};
/*
 * Stands in for WorksheetView._addCellTextToCache. It reproduces the part of the
 * real contract _autoFitColumnWidth depends on:
 *   - a cell whose text is empty returns early ("if (c.isEmptyTextString())") and
 *     leaves NOTHING that _getCellTextCache can find;
 *   - a cell with text ends with _fetchCellCache + _fetchCellCacheText, i.e. both
 *     columns[col] and columnsWithText[col] set, carrying flags/metrics/angle.
 */
View.prototype._addCellTextToCache = function (col, row, opt_GenerateCacheObj) {
	this.visits++;
	const mc = this.model.getMergedByCell(row, col);
	if (null !== mc) {
		/* the real one delegates a covered coordinate to the merge anchor */
		if (col !== mc.c1 || row !== mc.r1) {
			if (undefined === this._getCellTextCache(mc.c1, mc.r1, true)) {
				return this._addCellTextToCache(mc.c1, mc.r1);
			}
			return mc.c2;
		}
	}
	const c = this._getCell(col, row);
	if (null === c || !c.text) { return col; }
	this.hits++;
	const cache = this._fetchCellCache(col, row);
	cache.flags = {
		merged: mc,
		isMerged: function () { return null !== this.merged; },
		getMergeType: function () { return 0; },
		wrapText: false
	};
	cache.metrics = { width: c.text.length * GLYPH_PX, height: 14 };
	cache.angle = 0;
	cache.cellType = c.type;
	this.cache.rows[row].columnsWithText[col] = true;
	return mc ? mc.c2 : col;
};

/*
 * Builds a View subclass carrying the four real methods extracted from one
 * revision of WorksheetView.js, so two revisions can be run side by side.
 */
function viewClassFrom(fns) {
	function V(model) { View.call(this, model); }
	V.prototype = Object.create(View.prototype);
	V.prototype.constructor = V;
	const build = new Function(
		'V', 'Asc', 'History', 'c_oAscCanChangeColWidth', 'CellValueType', 'c_oAscMaxColumnWidth',
		'gc_nMaxRow0', 'gc_nMaxCol0',
		'"use strict";\n' +
		'V.prototype._getCellCache = function' + fns.cellCache + ';\n' +
		'V.prototype._getCellTextCache = function' + fns.textCache + ';\n' +
		'V.prototype._autoFitColumnWidth = function' + fns.autoFitCol + ';\n' +
		'V.prototype._autoFitColumnsWidth = function' + fns.autoFitCols + ';\n');
	build(V, Asc, History, c_oAscCanChangeColWidth, CellValueType, c_oAscMaxColumnWidth,
		gc_nMaxRow0, gc_nMaxCol0);
	return V;
}
const View_ = viewClassFrom(FNS);          // the tree as it stands
const View_base = viewClassFrom(FNS_BASE); // BASE_REF, for the side-by-side check

/*
 * The range autoFitColumnsWidth builds for a whole-column selection:
 * "var r1 = 0, r2 = this.model.getRowsCount() - 1" then
 * "ranges.push(new Asc.Range(sel.c1, r1, sel.c2, r2))".
 */
function selectionRangeForColumns(model, c1, c2) {
	return [new Range(c1, 0, c2, model.getRowsCount() - 1)];
}

function autofitFirstFourColumns(model, Klass) {
	const view = new (Klass || View_)(model);
	view._autoFitColumnsWidth(selectionRangeForColumns(model, 0, 3));
	return view;
}

/* a sheet with `dataRows` rows of text in columns A..D and a row extent of `extent` */
function sheet(dataRows, extent) {
	const m = new Model();
	for (let r = 0; r < dataRows; ++r) {
		for (let c = 0; c < 4; ++c) {
			m.setCell(c, r, 'r' + r + 'c' + c + 'x'.repeat((r + c) % 5));
		}
	}
	if (extent > m.nRowsCount) { m.addRowRecord(extent - 1); }
	return m;
}

let failures = 0;
function section(name, fn) {
	try { fn(); console.log('ok   - ' + name); }
	catch (e) { failures++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

/* ------------------------------------------------------------------ *
 * 0. harness check - the extracted code really runs and really fits   *
 * ------------------------------------------------------------------ */
section('0. harness: autofit of a dense sheet widens the columns it is given', function () {
	const m = sheet(50, 50);
	const view = autofitFirstFourColumns(m);
	assert.strictEqual(view.hits, 200, 'expected 4 columns x 50 cells with text, got ' + view.hits);
	for (let c = 0; c < 4; ++c) {
		assert.ok(m.bestFit[c] !== undefined, 'column ' + c + ' was never sized');
		assert.ok(m.bestFit[c] > 0, 'column ' + c + ' got a non-positive width');
	}
});

/* ------------------------------------------------------------------ *
 * 1. behaviour - the sizes autofit produces must not move             *
 * ------------------------------------------------------------------ *
 * The widest string in column c over rows 0..49 is the one with the most
 * trailing padding, so the expected width is computable independently of
 * the code under test. Both trees must produce exactly these numbers,
 * and they must not depend on how far the sheet's row extent runs.
 */
function expectedChars(model, col, dataRows) {
	let maxPx = 0;
	for (let r = 0; r < dataRows; ++r) {
		const c = model.cells[col] && model.cells[col][r];
		if (c && c.text) { maxPx = Math.max(maxPx, c.text.length * GLYPH_PX); }
	}
	if (maxPx <= 0) { return null; }
	const pad = 2 * 2 + 1;
	return Math.min((maxPx + pad) / GLYPH_PX, c_oAscMaxColumnWidth);
}

section('1. behaviour: autofit produces the arithmetically correct column width', function () {
	const m = sheet(50, 50);
	autofitFirstFourColumns(m);
	for (let c = 0; c < 4; ++c) {
		assert.strictEqual(m.bestFit[c], expectedChars(m, c, 50),
			'column ' + c + ' width changed: got ' + m.bestFit[c] + ', want ' + expectedChars(m, c, 50));
	}
});

section('1b. behaviour: a padded row extent does not change the sizes', function () {
	const tight = sheet(120, 120);
	const padded = sheet(120, gc_nMaxRow0 + 1);
	autofitFirstFourColumns(tight);
	autofitFirstFourColumns(padded);
	for (let c = 0; c < 4; ++c) {
		assert.strictEqual(padded.bestFit[c], tight.bestFit[c],
			'column ' + c + ': padded sheet sized to ' + padded.bestFit[c] +
			' but the same data in a tight sheet sized to ' + tight.bestFit[c]);
		assert.strictEqual(tight.bestFit[c], expectedChars(tight, c, 120), 'column ' + c + ' width is wrong');
	}
});

section('1c. behaviour: a column with a gap still measures the cells below the gap', function () {
	const m = new Model();
	m.setCell(0, 0, 'short');
	m.setCell(0, 900, 'a much much longer value');   // far below the gap
	m.addRowRecord(gc_nMaxRow0);
	const view = new View_(m);
	view._autoFitColumnsWidth([new Range(0, 0, 0, m.getRowsCount() - 1)]);
	assert.strictEqual(view.hits, 2, 'both cells must be measured, measured ' + view.hits);
	assert.strictEqual(m.bestFit[0], expectedChars(m, 0, 901), 'wrong width for a column with a gap');
});

/* ------------------------------------------------------------------ *
 * 2. the defect - how many rows the scan touches                      *
 * ------------------------------------------------------------------ */
section('2. scan is bounded by the cells, not by the sheet row extent', function () {
	const DATA_ROWS = 100;
	const m = sheet(DATA_ROWS, gc_nMaxRow0 + 1);   // rows formatted to the bottom of the sheet
	assert.strictEqual(m.getRowsCount(), 1048576, 'the stub sheet should report a full row extent');

	const view = autofitFirstFourColumns(m);
	const cells = 4 * DATA_ROWS;

	console.log('       row extent           : ' + m.getRowsCount());
	console.log('       cells with content   : ' + cells);
	console.log('       _addCellTextToCache  : ' + view.visits);
	console.log('       wasted visits        : ' + (view.visits - view.hits));

	assert.ok(view.visits <= cells,
		'autofit of 4 columns holding ' + cells + ' cells called _addCellTextToCache ' +
		view.visits + ' times (' + (view.visits / cells).toFixed(0) + 'x the work); ' +
		'the loop is walking the sheet row extent instead of the column cell extent');
});

section('2b. scan cost does not grow with the empty row extent', function () {
	const counts = [10000, 100000, gc_nMaxRow0 + 1].map(function (extent) {
		return { extent: extent, visits: autofitFirstFourColumns(sheet(100, extent)).visits };
	});
	counts.forEach(function (c) {
		console.log('       extent ' + String(c.extent).padStart(8) + ' -> visits ' + c.visits);
	});
	assert.strictEqual(counts[0].visits, counts[2].visits,
		'visits grew from ' + counts[0].visits + ' to ' + counts[2].visits +
		' when only the empty row extent grew (100x more empty rows, same 400 cells)');
});

/* ------------------------------------------------------------------ *
 * 3. no behaviour change - BASE_REF and the working tree side by side *
 * ------------------------------------------------------------------ *
 * Both revisions of the real _autoFitColumnWidth are extracted into this one
 * process and run over the same corpus of sheets. Every column must come out
 * the same width, and every cell that BASE_REF measured must still be measured.
 * With BASELINE=1 the two sides are the same revision, so this only says
 * something when the working tree differs - which is the point.
 */
const corpus = [
	['dense text, 200 rows', function () { return sheet(200, 200); }],
	['dense text, 200 rows, extent padded to the sheet maximum', function () { return sheet(200, gc_nMaxRow0 + 1); }],
	['numeric cells', function () {
		const m = new Model();
		for (let r = 0; r < 150; ++r) {
			for (let c = 0; c < 4; ++c) { m.setCell(c, r, String(r * 1000 + c) + '.' + r, CellValueType.Number); }
		}
		m.addRowRecord(gc_nMaxRow0);
		return m;
	}],
	['sparse cells with big gaps', function () {
		const m = new Model();
		[0, 5, 77, 199, 4000].forEach(function (r) {
			for (let c = 0; c < 4; ++c) { m.setCell(c, r, 'v'.repeat(3 + (r % 11) + c)); }
		});
		m.addRowRecord(gc_nMaxRow0);
		return m;
	}],
	['column data starting well below row 0', function () {
		const m = new Model();
		for (let r = 500; r < 560; ++r) {
			for (let c = 0; c < 4; ++c) { m.setCell(c, r, 'below-' + r + '-' + c); }
		}
		m.addRowRecord(gc_nMaxRow0);
		return m;
	}],
	['a merge spanning rows only, inside column A', function () {
		const m = sheet(40, 40);
		m.addMerge(0, 60, 0, 80, 'a tall merged label that is much wider than the rest');
		m.addRowRecord(gc_nMaxRow0);
		return m;
	}],
	['a merge spanning columns', function () {
		const m = sheet(40, 40);
		m.addMerge(0, 60, 2, 60, 'a wide merged banner nobody should autofit against');
		m.addRowRecord(gc_nMaxRow0);
		return m;
	}],
	['one of the four columns holds nothing', function () {
		const m = new Model();
		for (let r = 0; r < 120; ++r) {
			for (const c of [0, 1, 3]) { m.setCell(c, r, 'c' + c + '-' + 'y'.repeat(r % 9)); }
		}
		m.addRowRecord(gc_nMaxRow0);
		return m;
	}],
	['completely empty sheet with a full row extent', function () {
		const m = new Model();
		m.addRowRecord(gc_nMaxRow0);
		m.nColsCount = 4;
		return m;
	}]
];

section('3. no behaviour change: same widths as ' + BASE_REF + ' on every shape of sheet', function () {
	for (const [name, make] of corpus) {
		const mNew = make(), mOld = make();
		const vNew = autofitFirstFourColumns(mNew, View_);
		const vOld = autofitFirstFourColumns(mOld, View_base);

		assert.deepStrictEqual(mNew.bestFit, mOld.bestFit,
			name + ': setColBestFit widths differ\n       now  ' + JSON.stringify(mNew.bestFit) +
			'\n       ' + BASE_REF + ' ' + JSON.stringify(mOld.bestFit));
		assert.deepStrictEqual(Array.from(mNew.colWidthChars), Array.from(mOld.colWidthChars),
			name + ': resulting column widths differ');
		assert.strictEqual(vNew.hits, vOld.hits,
			name + ': measured ' + vNew.hits + ' cells but ' + BASE_REF + ' measured ' + vOld.hits);
		console.log('       ' + name.padEnd(48) + ' widths ' +
			JSON.stringify(mNew.bestFit) + '  cells measured ' + vNew.hits +
			'  rows touched ' + vNew.visits + ' (was ' + vOld.visits + ')');
	}
});

process.exitCode = failures ? 1 : 0;
console.log(failures ? '\n' + failures + ' section(s) failed' : '\nall sections passed');
