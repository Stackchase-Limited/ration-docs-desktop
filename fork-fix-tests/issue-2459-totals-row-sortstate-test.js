/*
 * #2459 (found while working on it) - a table sorted from its column filter
 * button saved a <sortState> that no longer covered its data rows after the
 * totals row was turned off/on or deleted:
 *   - totals row off (or deleting rows that end with the totals row):
 *     <table ref="H2:J5"><autoFilter ref="H2:J5"><sortState ref="H3:J4"> -
 *     the sort range lost the last data row (H3:J3 after deleting rows 5:6);
 *   - totals row on after sorting: <sortState ref="H3:J6"> on a table H2:J6
 *     with totalsRowCount="1" - the sort range ran onto the totals row.
 * Undo/redo and x2t's replay of the desktop save re-run the same code.
 *
 * Cause: TablePart.changeRef(col, row, bIsFirst, bIsNotChangeAutoFilter)
 * (cell/model/WorkbookElems.js), whose flag is used only to add/remove the
 * totals row, left the AutoFilter alone but still shifted the SortState. And
 * AutoFilters.insertRows (cell/model/autofilters.js, "inside" branch), when the
 * deleted rows take the totals row, shifts the table without its autofilter
 * and the autofilter by diff + 1 - the SortState went with the table by diff.
 *
 * This extracts by brace matching the real insertRows, TablePart changeRef /
 * isTotalsRow, AutoFilter changeRef, SortState changeRef and the real Range
 * constructor / clone / setOffsetFirst / setOffsetLast / getName / _getName /
 * getType / isAbsCol / isAbsRow / isOneCell, runs them on a table H2:J6 with a
 * totals row, autofilter H2:J5 and a table SortState H3:J5 (as the sort button
 * makes it; the autofilter also gets a SortState H3:J5 to cover that path), and
 * checks both sort refs after
 *   1. deleting the totals row alone (what "totals row off" does): H3:J5,
 *   2. deleting the last data row and the totals row: H3:J4,
 *   3. deleting a data row in the middle (unchanged behaviour): H3:J4,
 *   4. adding / removing the totals row through changeRef(.., true) (what
 *      "totals row on", and "off" with a table right below, do): H3:J5.
 * Stubbed: history, slicers, the table clone (only used for history), handlers.
 * NOT claimed here: the full editor + x2t save flow (verified separately in a
 * headless editor with the real desktop save, see the commit message), nor the
 * sortCondition refs (sdkjs writes them over the whole table column at sort
 * time and no Ref change moves them; untouched by this fix).
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
const BASE_REF = process.env.BASE_REF || '3412e6b3bd^';

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
const del = (rows, type) => {
	const { tp, autoFilters } = makeTable();
	insertRows.call(autoFilters, 'delCell', r(7, rows[0], 9, rows[1]), type);
	return refs(tp);
};

/* 1. "totals row off": the totals row H6:J6 is deleted with cells shifting up */
{
	const got = del([5, 5], c_oAscDeleteOptions.DeleteCellsAndShiftTop);
	assert.deepStrictEqual([got.table, got.af, got.totals], ['H2:J5', 'H2:J5', null]);
	assert.strictEqual(got.sort, 'H3:J5',
		`after turning totals off the table sortState must still cover all data rows (got ${got.sort}; saved as ` +
		`<autoFilter ref="H2:J5"><sortState ref="${got.sort}">)`);
	assert.strictEqual(got.afSort, 'H3:J5');
}

/* 2. delete rows 5..6 (last data row + totals row) */
{
	const got = del([4, 5], c_oAscDeleteOptions.DeleteRows);
	assert.deepStrictEqual([got.table, got.af, got.totals], ['H2:J4', 'H2:J4', null]);
	assert.strictEqual(got.sort, 'H3:J4', `deleting the last data row and the totals row must cost the sort range one row (got ${got.sort})`);
	assert.strictEqual(got.afSort, 'H3:J4');
}

/* 3. unchanged: deleting a data row above the totals row shrinks everything by one */
{
	const got = del([3, 3], c_oAscDeleteOptions.DeleteRows);
	assert.deepStrictEqual([got.table, got.af, got.totals], ['H2:J5', 'H2:J4', 1]);
	assert.deepStrictEqual([got.sort, got.afSort], ['H3:J4', 'H3:J4']);
}

/* 4. totals row on / off via changeRef(.., bIsNotChangeAutoFilter): only the table Ref moves */
{
	const { tp } = makeTable();
	tp.Ref = r(7, 1, 9, 4); tp.TotalsRowCount = null;
	tp.changeRef(null, 1, null, true);
	let got = refs(tp);
	assert.deepStrictEqual([got.table, got.af], ['H2:J6', 'H2:J5']);
	assert.strictEqual(got.sort, 'H3:J5', `turning totals on must not put the sort range on the totals row (got ${got.sort})`);
	tp.changeRef(null, -1, null, true);
	got = refs(tp);
	assert.deepStrictEqual([got.table, got.af, got.sort], ['H2:J5', 'H2:J5', 'H3:J5']);
}

console.log('ok - a table sortState stays on the data rows when the totals row is added, removed or deleted');
