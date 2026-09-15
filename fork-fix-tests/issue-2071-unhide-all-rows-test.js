/*
 * #2071 - "Unhide not working in spreadsheet".
 *
 * The filed report is about columns, and columns do work: setColHidden has a
 * whole-sheet branch (cell/model/Workbook.js, "if(0 === start && gc_nMaxCol0 === stop)")
 * that clears the flag on oAllCol and on every Col record, so Ctrl+A -> Show
 * brings hidden columns back.
 *
 * Rows had no such branch. Worksheet.prototype.setRowHidden -> doHide read:
 *
 *     if(0 == _start && gc_nMaxRow0 == _stop)
 *     {
 *         // ToDo implement hiding all rows!
 *     }
 *     else
 *     { ...the loop that actually does the work... }
 *
 * and "Select All -> Show" is exactly that call: WorksheetView.changeWorksheet
 * ("showRows", cell/view/WorksheetView.js:17778) hands doMultiRanges the selection,
 * MultiplyRange.unionByRowCol returns the single full-sheet range unchanged
 * (cell/utils/utils.js:1828), so the model gets setRowHidden(false, 0, gc_nMaxRow0)
 * and silently does nothing.
 *
 * That matters twice over:
 *   - once the FIRST row is hidden there is no row above it to select, so select-all
 *     is the only route back, and it is the one route that is a no-op;
 *   - a workbook saved with zeroHeight="1" (oAllRow hidden, round-tripped by
 *     cell/model/Serialize.js:6064 / :12087) loads with every row hidden and no way
 *     at all to get them back.
 *
 * This extracts the real Worksheet.prototype.setRowHidden and the real
 * Row.prototype.setHidden / getHidden / _getUpdateRange by brace matching and drives
 * them against a stub worksheet whose row store mirrors _foreachRowNoEmpty
 * (existing records only, ascending).
 *
 * BASELINE=1 re-reads cell/model/Workbook.js from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL_WB = 'cell/model/Workbook.js';
const REL_EL = 'cell/model/WorkbookElems.js';
const BASE_REF = process.env.BASE_REF || 'HEAD';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
const srcWb = read(REL_WB);
const srcEl = read(REL_EL);

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
function grabConst(source, rel, re) {
	const m = source.match(re);
	assert.ok(m, 'not found in ' + rel + ': ' + re);
	return m[0];
}

/* --- the real code under test --- */
const srcSetRowHidden = grabFn(srcWb, REL_WB, 'Worksheet.prototype.setRowHidden=function');
assert.ok(srcSetRowHidden.indexOf('var doHide = function') !== -1, 'extracted the wrong setRowHidden');
assert.ok(srcSetRowHidden.indexOf('gc_nMaxRow0 == _stop') !== -1, 'extracted the wrong setRowHidden');

/* the real row flag handling, so "hidden" means what it means in the product */
const srcRowSetHidden = grabFn(srcEl, REL_EL, 'Row.prototype.setHidden = function');
const srcRowGetHidden = grabFn(srcEl, REL_EL, 'Row.prototype.getHidden = function');
const srcRowUpdRange  = grabFn(srcEl, REL_EL, 'Row.prototype._getUpdateRange = function');
const srcFlagHd     = grabConst(srcEl, REL_EL, /var g_nRowFlag_hd = \d+;/);
const srcFlagHdView = grabConst(srcEl, REL_EL, /var g_nRowFlag_hdView = \d+;/);

const MAXROW0 = 1048576 - 1;
const MAXCOL0 = 16384 - 1;
const ALLROW = -1;

/* --- stubs --- */
const history = [];
const AscCH = { historyitem_Worksheet_RowHide: 'RowHide', historyitem_Worksheet_RowProp: 'RowProp' };
const AscCommon = {
	History: {
		LocalChange: false,
		Create_NewPoint: function () {},
		Is_On: function () { return true; },
		Add: function (cls, type, sheetId, range, data) { history.push({ type: type, range: range, data: data }); }
	}
};
function Range(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
const Asc = { Range: function (c1, r1, c2, r2) { return new Range(c1, r1, c2, r2); } };
Asc.Range.prototype = Range.prototype;

function UndoRedoData_FromToRowCol(bRow, from, to) { this.bRow = bRow; this.from = from; this.to = to; }
function UndoRedoData_IndexSimpleProp(index, bRow, oOldVal, oNewVal) {
	this.index = index; this.bRow = bRow; this.oOldVal = oOldVal; this.oNewVal = oNewVal;
}
/* the only bit of UndoRedoData_RowProp setRowHidden leans on is hd + isEqual */
function RowProp(row) {
	this.h = row.getHeight(); this.hd = row.getHidden();
	this.CustomHeight = row.getCustomHeight(); this.OutlineLevel = row.getOutlineLevel();
	this.Collapsed = row.getCollapsed();
}
RowProp.prototype.isEqual = function (v) {
	return this.hd == v.hd && this.h == v.h && this.CustomHeight == v.CustomHeight &&
		this.OutlineLevel == v.OutlineLevel && this.Collapsed == v.Collapsed;
};

const AscCommonExcel = { g_oUndoRedoWorksheet: {}, g_nAllRowIndex: ALLROW, g_nAllColIndex: -1 };

/* build the real Row methods over a plain record */
const rowBuild = new Function('AscCommon', 'AscCommonExcel', 'AscCH', 'Asc', 'gc_nMaxCol0', 'gc_nMaxRow0',
	'UndoRedoData_IndexSimpleProp', '"use strict";\n' +
	srcFlagHd + '\n' + srcFlagHdView + '\n' +
	'function Row(ws, index) { this.ws = ws; this.index = index; this.flags = 0; this.h = null;\n' +
	'  this.outlineLevel = 0; this.collapsed = false; this._hasChanged = false; }\n' +
	'Row.prototype.setHidden = function' + srcRowSetHidden + ';\n' +
	'Row.prototype.getHidden = function' + srcRowGetHidden + ';\n' +
	'Row.prototype._getUpdateRange = function' + srcRowUpdRange + ';\n' +
	'Row.prototype.getHeight = function () { return this.h; };\n' +
	'Row.prototype.getCustomHeight = function () { return false; };\n' +
	'Row.prototype.getOutlineLevel = function () { return this.outlineLevel; };\n' +
	'Row.prototype.getCollapsed = function () { return this.collapsed; };\n' +
	'return Row;');
const Row = rowBuild(AscCommon, AscCommonExcel, AscCH, Asc, MAXCOL0, MAXROW0, UndoRedoData_IndexSimpleProp);
Row.prototype.getHeightProp = function () { return new RowProp(this); };

/* a worksheet whose row store behaves like Range._foreachRowNoEmpty:
 * only rows that actually have a record, walked in ascending index order. */
function Sheet() {
	this.rows = {};            // index -> Row, "has a record"
	this.oAllRow = null;       // the sheetFormatPr default row
	this.sheetPr = null;
	this.hiddenManager = { addHidden: function () {} };
	this.autoFilters = {
		useViewLocalChange: false,
		containInFilter: function () { return false; },
		splitRangeByFilters: function () { return null; },
		reDrawFilter: function () {}
	};
	this.workbook = {
		bUndoChanges: false, bRedoChanges: false, bCollaborativeChanges: false,
		dependencyFormulas: { calcTree: function () {} }
	};
}
Sheet.prototype.getId = function () { return 'sheet1'; };
Sheet.prototype.getActiveNamedSheetViewId = function () { return null; };
Sheet.prototype.needRecalFormulas = function () { return false; };
Sheet.prototype.setCollapsedRow = function () {};
Sheet.prototype.getAllRow = function () {
	if (null == this.oAllRow) { this.oAllRow = new Row(this, ALLROW); }
	return this.oAllRow;
};
Sheet.prototype.getAllRowNoEmpty = function () { return this.oAllRow; };
Sheet.prototype._getRowNoEmpty = function (i, fAction) { fAction(this.rows[i] || null); };
Sheet.prototype._getRow = function (i, fAction) {
	if (ALLROW == i) { fAction(this.getAllRow()); return; }
	if (!this.rows[i]) { this.rows[i] = new Row(this, i); }
	fAction(this.rows[i]);
};
Sheet.prototype._forEachRow = function (fAction) {
	const idx = Object.keys(this.rows).map(Number).sort(function (a, b) { return a - b; });
	for (const i of idx) { fAction(this.rows[i]); }
};
/* mirrors _getRowNoEmptyWithAll: a row with no record inherits the default row */
Sheet.prototype.getRowHidden = function (i) {
	const row = this.rows[i];
	if (row) { return row.getHidden(); }
	return this.oAllRow ? this.oAllRow.getHidden() : false;
};
Sheet.prototype.recordCount = function () { return Object.keys(this.rows).length; };

const wbBuild = new Function('AscCommon', 'AscCommonExcel', 'AscCH', 'Asc', 'gc_nMaxCol0', 'gc_nMaxRow0',
	'UndoRedoData_FromToRowCol', 'UndoRedoData_IndexSimpleProp', 'Sheet', '"use strict";\n' +
	'Sheet.prototype.setRowHidden = function' + srcSetRowHidden + ';\n' +
	'return Sheet;');
wbBuild(AscCommon, AscCommonExcel, AscCH, Asc, MAXCOL0, MAXROW0,
	UndoRedoData_FromToRowCol, UndoRedoData_IndexSimpleProp, Sheet);

function sheetWithHiddenRows(indices) {
	const ws = new Sheet();
	for (const i of indices) {
		ws.rows[i] = new Row(ws, i);
		ws.rows[i].setHidden(true);
	}
	return ws;
}

/* --- 0. the harness itself: a partial range works, in both trees --- */
{
	const ws = sheetWithHiddenRows([2, 3]);
	assert.strictEqual(ws.getRowHidden(2), true);
	ws.setRowHidden(false, 2, 3);
	assert.strictEqual(ws.getRowHidden(2), false, 'showing rows 3:4 must work');
	assert.strictEqual(ws.getRowHidden(3), false);

	ws.setRowHidden(true, 5, 5);
	assert.strictEqual(ws.getRowHidden(5), true, 'hiding row 6 must work');
}

/* --- 1. the defect: hide the first row, then Select All -> Show --- */
{
	const ws = sheetWithHiddenRows([0]);
	history.length = 0;
	ws.setRowHidden(false, 0, MAXROW0);

	assert.strictEqual(ws.getRowHidden(0), false,
		'Select All then Show must unhide row 1 - it is the only way to reach the ' +
		'first row, and setRowHidden(false, 0, gc_nMaxRow0) used to fall into the ' +
		'empty "ToDo implement hiding all rows!" branch and do nothing (#2071)');
	assert.ok(history.length > 0, 'the change must be undoable');
}

/* --- 2. several hidden rows at once, including one that is not first --- */
{
	const ws = sheetWithHiddenRows([0, 4, 5, 9]);
	ws.setRowHidden(false, 0, MAXROW0);
	for (const i of [0, 4, 5, 9]) {
		assert.strictEqual(ws.getRowHidden(i), false, 'row ' + (i + 1) + ' must be shown');
	}
}

/* --- 3. a workbook loaded with zeroHeight="1" (oAllRow hidden) --- */
{
	const ws = new Sheet();
	ws.getAllRow().setHidden(true);          // what Serialize.js:12087 does on open
	assert.strictEqual(ws.getRowHidden(7), true, 'every row starts hidden');

	ws.setRowHidden(false, 0, MAXROW0);
	assert.strictEqual(ws.oAllRow.getHidden(), false,
		'Show over the whole sheet must clear the default-row hidden flag, otherwise ' +
		'a zeroHeight="1" workbook can never be read');
	assert.strictEqual(ws.getRowHidden(7), false);
}

/* --- 4. hiding the whole sheet uses the default row, not a million records --- */
{
	const ws = sheetWithHiddenRows([]);
	ws.rows[3] = new Row(ws, 3);             // one ordinary row with a record
	const before = ws.recordCount();

	ws.setRowHidden(true, 0, MAXROW0);
	assert.strictEqual(ws.getRowHidden(500000), true,
		'Select All then Hide must hide rows that have no record of their own');
	assert.strictEqual(ws.rows[3].getHidden(), true,
		'and rows that do have one');
	assert.strictEqual(ws.recordCount(), before,
		'without materialising a Row record per row (got ' + ws.recordCount() + ')');

	ws.setRowHidden(false, 0, MAXROW0);
	assert.strictEqual(ws.getRowHidden(500000), false, 'and it must be reversible');
	assert.strictEqual(ws.rows[3].getHidden(), false);
}

/* --- 5. nothing outside the selection moves --- */
{
	const ws = sheetWithHiddenRows([2, 3, 8]);
	ws.setRowHidden(false, 2, 3);
	assert.strictEqual(ws.getRowHidden(8), true,
		'showing rows 3:4 must leave row 9 hidden');
}

console.log('ok - Select All then Show/Hide now reaches every row, the first one included');
