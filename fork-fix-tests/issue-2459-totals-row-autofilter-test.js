/*
 * #2459 (found while working on it) - turn a table's totals row off and on
 * again: the saved table had ref="B3:F7" totalsRowCount="1" but
 * <autoFilter ref="B3:F5">, i.e. the filter ended two rows above the table end
 * instead of one (the last data row was outside the filter). Each further
 * toggle, undo or redo shrank it by another row; x2t's replay of the desktop
 * save re-runs the same code, so the file got it too.
 *
 * Cause: turning totals off deletes the totals row with deleteCellsShiftUp,
 * which shifts tables in AutoFilters.insertRows (cell/model/autofilters.js).
 * When the deleted rows reach the table end it nulls TotalsRowCount and calls
 * TablePart.changeRef(null, diff) (cell/model/WorkbookElems.js), which also
 * shifts the table AutoFilter by diff - but the totals row is not part of the
 * autofilter, so the filter lost one row too many. Turning totals on again
 * only grows the table (changeRef(..., bIsNotChangeAutoFilter)), so the gap
 * stays. Deleting rows that end with the totals row goes through the same
 * branch.
 *
 * This extracts by brace matching the real insertRows, TablePart changeRef /
 * isTotalsRow, AutoFilter changeRef and the real Range constructor / clone /
 * setOffsetFirst / setOffsetLast / getName / _getName / getType / isAbsCol /
 * isAbsRow / isOneCell, runs them on a table H2:J6 with a totals row and an
 * autofilter H2:J5, and checks the autofilter after
 *   1. deleting the totals row alone (what "totals row off" does): H2:J5,
 *   2. deleting the last data row and the totals row: H2:J4,
 *   3. deleting a data row in the middle (unchanged behaviour): H2:J4, totals kept.
 * Stubbed: history, slicers, the table clone (only used for history), handlers.
 * NOT claimed here: the full editor + x2t save flow (verified separately in a
 * headless editor with the real desktop save, see the commit message), and the
 * table SortState, which still shifts with the table.
 *
 * RD_REPO overrides the sdkjs checkout; BASELINE=1 reads the sources from
 * BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit (re-pinned by the integrator after
// cherry-picking). Never HEAD: once the fix lands HEAD carries it.
const BASE_REF = process.env.BASE_REF || 'b29329506b^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match forward from the first '{' at or after `from`. */
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
/* `marker` ends with "function"; returns "(args) { body }" */
function fn(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return matched(text, at + marker.length);
}

const utils = read('cell/utils/utils.js');
const elems = read('cell/model/WorkbookElems.js');
const autofilters = read('cell/model/autofilters.js');

/* --- the real Asc.Range --- */
const referenceTypeSrc = matched(utils, utils.indexOf('var referenceType = ') + 'var referenceType = '.length);
const ctorSrc = fn(utils, 'function Range');
const methods = ['clone', 'setOffsetFirst', 'setOffsetLast', 'getName', '_getName', 'getType', 'isAbsCol', 'isAbsRow', 'isOneCell'];
const AscCommonExcel = { g_R1C1Mode: false, g_ActiveCell: { c1: 0, r1: 0 } };
const c_oAscSelectionType = { RangeCells: 1, RangeCol: 2, RangeRow: 3, RangeMax: 4 };
const g_oCellAddressUtils = {
	colnumToColstr(n) { let s = ''; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; },
};
const Range = new Function('AscCommonExcel', 'c_oAscSelectionType', 'g_oCellAddressUtils', 'gc_nMaxCol0', 'gc_nMaxRow0',
	'"use strict"; var referenceType = ' + referenceTypeSrc + '; function Range' + ctorSrc + '\n' +
	methods.map(m => 'Range.prototype.' + m + ' = function' + fn(utils, 'Range.prototype.' + m + ' = function') + ';').join('\n') +
	'\nreturn Range;')(AscCommonExcel, c_oAscSelectionType, g_oCellAddressUtils, 16383, 1048575);
const AscCommon = { CellBase: function (row, col) { this.row = row; this.col = col; }, gc_nMaxCol: 16384 };
const Asc = { Range };

/* --- the real table / autofilter Ref changes --- */
const make = (src, scope) => {
	const names = Object.keys(scope || {});
	return new Function(...names, '"use strict"; return function' + src)(...names.map(n => scope[n]));
};
const tableChangeRef = make(fn(elems, 'TablePart.prototype.changeRef = function'), { AscCommon });
const isTotalsRow = make(fn(elems, 'TablePart.prototype.isTotalsRow = function'));
const afChangeRef = make(fn(elems, 'AutoFilter.prototype.changeRef = function'), { AscCommon });

const insertRowsSrc = fn(autofilters, 'insertRows: function ');
assert.ok(insertRowsSrc.includes('TotalsRowCount = null'), 'extracted the wrong insertRows');
const c_oAscInsertOptions = { InsertCellsAndShiftRight: 1, InsertCellsAndShiftDown: 2, InsertColumns: 3, InsertRows: 4, InsertTableRowAbove: 5 };
const c_oAscDeleteOptions = { DeleteCellsAndShiftLeft: 1, DeleteCellsAndShiftTop: 2, DeleteColumns: 3, DeleteRows: 4, DeleteTable: 5 };
const AscCH = { historyitem_AutoFilter_Change: 'change' };
const insertRows = make(insertRowsSrc, { AscCommon, AscCH, c_oAscInsertOptions, c_oAscDeleteOptions });

/* table H2:J6 = header row 2, data rows 3..5, totals row 6; autofilter H2:J5 */
const r = (c1, r1, c2, r2) => new Range(c1, r1, c2, r2);
function makeTable() {
	const af = { Ref: r(7, 1, 9, 4), SortState: null, changeRef: afChangeRef };
	const tp = {
		Ref: r(7, 1, 9, 5), TotalsRowCount: 1, AutoFilter: af, SortState: null, DisplayName: 'Table1',
		handlers: { trigger() {} }, changeRef: tableChangeRef, isTotalsRow,
		clone() { return { Ref: this.Ref.clone(), DisplayName: this.DisplayName }; },
	};
	const autoFilters = {
		worksheet: { AutoFilter: null, TableParts: [tp], workbook: { bUndoChanges: false, bRedoChanges: false, bCollaborativeChanges: false } },
		_addHistoryObj() {}, updateSlicer() {},
	};
	return { tp, autoFilters };
}
const del = (rows, type) => {
	const { tp, autoFilters } = makeTable();
	insertRows.call(autoFilters, 'delCell', r(7, rows[0], 9, rows[1]), type);
	return { table: tp.Ref.getName(), af: tp.AutoFilter.Ref.getName(), totals: tp.TotalsRowCount };
};

/* 1. "totals row off": the totals row H6:J6 is deleted with cells shifting up */
{
	const got = del([5, 5], c_oAscDeleteOptions.DeleteCellsAndShiftTop);
	assert.strictEqual(got.table, 'H2:J5');
	assert.strictEqual(got.totals, null, 'the table has no totals row any more');
	assert.strictEqual(got.af, 'H2:J5',
		`after turning totals off the autofilter must cover all data rows (got ${got.af}; turning totals on again ` +
		`saves <table ref="H2:J6"> with <autoFilter ref="${got.af}">)`);
}

/* 2. delete rows 5..6 (last data row + totals row) */
{
	const got = del([4, 5], c_oAscDeleteOptions.DeleteRows);
	assert.strictEqual(got.table, 'H2:J4');
	assert.strictEqual(got.totals, null);
	assert.strictEqual(got.af, 'H2:J4', `deleting the last data row and the totals row must cost the filter one row (got ${got.af})`);
}

/* 3. unchanged: deleting a data row above the totals row shrinks both by one */
{
	const got = del([3, 3], c_oAscDeleteOptions.DeleteRows);
	assert.strictEqual(got.table, 'H2:J5');
	assert.strictEqual(got.totals, 1, 'the totals row is still there');
	assert.strictEqual(got.af, 'H2:J4');
}

console.log('ok - deleting a table\'s totals row leaves its autofilter ending at the last data row');
