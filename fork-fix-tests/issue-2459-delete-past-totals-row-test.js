/*
 * #2459 (found while working on it) - delete whole rows from a table's last
 * data rows through its totals row and past the table end (rows 5:7 of a table
 * H2:J6 = header, 3 data rows, totals row): the table kept totalsRowCount="1",
 * so its last remaining data row became the totals row - the redraw wrote the
 * totals label and SUBTOTAL formulas over that row's values (H4 "y" ->
 * "Summary", J4 4 -> =SUBTOTAL(109,Table1[B])) - and the autofilter and sort
 * range ended a row above it. Redo and x2t's replay of the desktop save re-run
 * the same code, so the saved file had <table ref="H2:J4" totalsRowCount="1">
 * <autoFilter ref="H2:J3"> and the row's values were gone. Excel removes the
 * totals row in this case and keeps the data rows.
 *
 * Cause: AutoFilters.insertRows (cell/model/autofilters.js), branch for a range
 * that starts inside the table and ends below it, shrank the table, its
 * autofilter and sort range by the same row count and never cleared
 * TotalsRowCount, unlike the "inside" branch when the deletion reaches the end.
 *
 * This extracts by brace matching the real insertRows, TablePart changeRef /
 * isTotalsRow, AutoFilter changeRef, SortState changeRef and the real Range
 * constructor / clone / setOffsetFirst / setOffsetLast / getName / _getName /
 * getType / isAbsCol / isAbsRow / isOneCell, and checks after deleting
 *   1. rows 5..7 (last data row, totals row, a row below): table H2:J4 without
 *      totals row, autofilter H2:J4, sort ranges H3:J4,
 *   2. rows 6..7 (totals row and a row below): H2:J5, H2:J5, H3:J5,
 *   3. rows 5..7 of a table without totals row (unchanged): H2:J4, H2:J4, H3:J4,
 *   4. rows 5..7 through a sheet autofilter H2:J5 (unchanged): H2:J4.
 * Stubbed: history, slicers, the table clone (only used for history), handlers.
 * NOT claimed here: the redraw that overwrote the row and the x2t save
 * (verified separately in a headless editor with the real desktop save, see
 * the commit message).
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
const BASE_REF = process.env.BASE_REF || '65f035c329^';

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
const sortChangeRef = make(fn(elems, 'SortState.prototype.changeRef = function'), { AscCommon });

const insertRowsSrc = fn(autofilters, 'insertRows: function ');
assert.ok(insertRowsSrc.includes('TotalsRowCount = null'), 'extracted the wrong insertRows');
const c_oAscInsertOptions = { InsertCellsAndShiftRight: 1, InsertCellsAndShiftDown: 2, InsertColumns: 3, InsertRows: 4, InsertTableRowAbove: 5 };
const c_oAscDeleteOptions = { DeleteCellsAndShiftLeft: 1, DeleteCellsAndShiftTop: 2, DeleteColumns: 3, DeleteRows: 4, DeleteTable: 5 };
const AscCH = { historyitem_AutoFilter_Change: 'change' };
const insertRows = make(insertRowsSrc, { AscCommon, AscCH, c_oAscInsertOptions, c_oAscDeleteOptions });

/* table H2:J6 = header row 2, data rows 3..5, totals row 6; autofilter H2:J5; sort ranges H3:J5 */
const r = (c1, r1, c2, r2) => new Range(c1, r1, c2, r2);
const sortState = () => ({ Ref: r(7, 2, 9, 4), changeRef: sortChangeRef });
function makeTable() {
	const af = { Ref: r(7, 1, 9, 4), SortState: sortState(), changeRef: afChangeRef };
	const tp = {
		Ref: r(7, 1, 9, 5), TotalsRowCount: 1, AutoFilter: af, SortState: sortState(), DisplayName: 'Table1',
		handlers: { trigger() {} }, changeRef: tableChangeRef, isTotalsRow,
		clone() { return { Ref: this.Ref.clone(), DisplayName: this.DisplayName }; },
	};
	const autoFilters = {
		worksheet: { AutoFilter: null, TableParts: [tp], workbook: { bUndoChanges: false, bRedoChanges: false, bCollaborativeChanges: false } },
		_addHistoryObj() {}, updateSlicer() {},
	};
	return { tp, autoFilters };
}
const refs = tp => ({ table: tp.Ref.getName(), af: tp.AutoFilter.Ref.getName(), totals: tp.TotalsRowCount,
	sort: tp.SortState.Ref.getName(), afSort: tp.AutoFilter.SortState.Ref.getName() });
const del = (rows, noTotals) => {
	const { tp, autoFilters } = makeTable();
	if (noTotals) {
		tp.Ref = r(7, 1, 9, 4); tp.TotalsRowCount = null;
	}
	insertRows.call(autoFilters, 'delCell', r(7, rows[0], 9, rows[1]), c_oAscDeleteOptions.DeleteRows);
	return refs(tp);
};

/* 1. rows 5..7: last data row, totals row and the row below the table */
{
	const got = del([4, 6]);
	assert.strictEqual(got.table, 'H2:J4');
	assert.strictEqual(got.totals, null,
		'the totals row was deleted; keeping totalsRowCount turns the last data row (row 4) into the totals row');
	assert.strictEqual(got.af, 'H2:J4', `the autofilter must end at the last data row (got ${got.af})`);
	assert.deepStrictEqual([got.sort, got.afSort], ['H3:J4', 'H3:J4']);
}

/* 2. rows 6..7: the totals row and the row below */
{
	const got = del([5, 6]);
	assert.deepStrictEqual([got.table, got.totals, got.af, got.sort, got.afSort], ['H2:J5', null, 'H2:J5', 'H3:J5', 'H3:J5']);
}

/* 3. unchanged: table H2:J5 without a totals row */
{
	const got = del([4, 6], true);
	assert.deepStrictEqual([got.table, got.totals, got.af, got.sort, got.afSort], ['H2:J4', null, 'H2:J4', 'H3:J4', 'H3:J4']);
}

/* 4. unchanged: a sheet autofilter H2:J5 */
{
	const af = { Ref: r(7, 1, 9, 4), SortState: sortState(), changeRef: afChangeRef, clone() { return { Ref: this.Ref.clone() }; } };
	const autoFilters = {
		worksheet: { AutoFilter: af, TableParts: [], workbook: { bUndoChanges: false, bRedoChanges: false, bCollaborativeChanges: false } },
		_addHistoryObj() {}, updateSlicer() {},
	};
	insertRows.call(autoFilters, 'delCell', r(7, 4, 9, 6), c_oAscDeleteOptions.DeleteRows);
	assert.deepStrictEqual([af.Ref.getName(), af.SortState.Ref.getName()], ['H2:J4', 'H3:J4']);
}

console.log('ok - deleting rows past a table end that take its totals row removes the totals row');
