/*
 * #2459 (found while working on it) - a table sorted from its column filter
 * button saved a <sortState> / <sortCondition> that Excel does not write and
 * that drifted off the table's data rows:
 *   - first sort (table A1:C5 = header, data rows 2..4, totals row 5, sorted
 *     on B): <sortState ref="A2:C4"><sortCondition ref="B1:B5"> - the
 *     condition took in the header and totals row (Excel: B2:B4);
 *   - second sort on the same table (on C): <sortState ref="C1:C5">
 *     <sortCondition ref="C1:C5"> - the sort range shrank to one column and
 *     took in the header and totals row (Excel: A2:C4 / C2:C4);
 *   - inserting/deleting rows in the table moved the sortState but never its
 *     conditions (insert row 3: sortState A2:C5, sortCondition still B1:B5),
 *     and resizing the table moved neither (a resize that took out the sorted
 *     column left a condition outside the sortState, which Excel repairs);
 *   - turning the header row off moved the sortState's first row down
 *     (table A2:C6, data rows 3..5: sortState A4:C5 after header off).
 * The same happens to a sheet AutoFilter sorted from its button. Undo/redo and
 * x2t's replay of the desktop save run the same code.
 *
 * Cause: AutoFilters.sortColFilter (cell/model/autofilters.js) built the
 * condition from filterRef.r1..r2 (the whole table/autofilter Ref) and, when a
 * SortState existed, set SortState.Ref to the sorted column of that Ref.
 * SortState.changeRef (cell/model/WorkbookElems.js) changed only SortState.Ref,
 * and TablePart.changeRefOnRange (resize, auto-expansion) left the SortState
 * alone. The header toggle (changeFormatTableInfo, rowHeader) moved the table's
 * first row with TablePart.changeRef(.., bIsFirst) without the flag that keeps
 * the sort range (bIsNotChangeAutoFilter, used by the totals toggle).
 *
 * This extracts by brace matching the real sortColFilter, getPropForSort,
 * insertRows, changeTableRange, changeFormatTableInfo, TablePart changeRef / changeRefOnRange / getRangeWithoutHeaderFooter
 * / isTotalsRow / isHeaderRow / isAutoFilter, AutoFilter changeRef / changeRefOnRange /
 * getRangeWithoutHeaderFooter / isAutoFilter / isApplyAutoFilter, the SortState
 * and SortCondition constructors with SortState/SortCondition clone and SortState
 * changeRef / changeRefOnRange (the latter is new; absent at BASE_REF), the
 * UndoRedoData_SortState record with UndoRedoSortState.UndoRedo, and the real
 * Range constructor / clone / setOffsetFirst / setOffsetLast / getName /
 * _getName / getType / isAbsCol / isAbsRow / isOneCell / isEqual /
 * intersection / normalize, and checks the sortState and condition refs
 *   1. after sorting a table with a totals row on B, then on C,
 *   2. after inserting a row inside it, deleting a data row, and deleting its
 *      totals row ("totals row off"),
 *   3. after resizing it (TablePart.changeRefOnRange),
 *   4. for a sheet AutoFilter A1:C4 sorted on B, then C, then a row inserted,
 *   5. after resizing a table sorted on C to A1:B5 (SortState dropped and kept in
 *      a SortState history record), its undo (that record's real undo, then the
 *      resize back as the resize record's undo does) and redo,
 *   6. after turning a sorted table's header row off and on again.
 * Stubbed: History (Add records the items), table styles, the TablePart clone
 * (Ref + SortState clone, all changeTableRange reads), handlers, the worksheet
 * range/cell objects, the column-name helpers, cell clearing.
 * NOT claimed here: the editor's actual cell sort, undo/redo and the x2t save
 * (checked in a headless editor with the real desktop save, see the commit
 * message; that also showed the Sort dialog path, Workbook.js setCustomSort,
 * already writes data-row refs), the order in which History undoes a
 * transaction (assumed: last item first), and header on when the table must
 * move down a row (the _moveRange path; checked in the headless editor).
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
const BASE_REF = process.env.BASE_REF || '511ebed368^';

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
function fn(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return null;
	assert.notStrictEqual(at, -1, marker + ' not found');
	return matched(text, at + marker.length);
}

const utils = read('cell/utils/utils.js');
const elems = read('cell/model/WorkbookElems.js');
const autofilters = read('cell/model/autofilters.js');

/* --- the real Asc.Range --- */
const referenceTypeSrc = matched(utils, utils.indexOf('var referenceType = ') + 'var referenceType = '.length);
const ctorSrc = fn(utils, 'function Range');
const methods = ['clone', 'setOffsetFirst', 'setOffsetLast', 'getName', '_getName', 'getType', 'isAbsCol', 'isAbsRow', 'isOneCell', 'isEqual', 'intersection', 'normalize'];
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
const Asc = { Range, c_oAscSortOptions: { Ascending: 1, Descending: 2, ByColorFill: 3, ByColorFont: 4 } };

const make = (src, scope) => {
	const names = Object.keys(scope || {});
	return new Function(...names, '"use strict"; return function' + src)(...names.map(n => scope[n]));
};

/* --- the real SortState / SortCondition --- */
const SortState = make(fn(elems, '\tfunction SortState'));
const SortCondition = make(fn(elems, '\tfunction SortCondition'));
SortState.prototype.changeRef = make(fn(elems, 'SortState.prototype.changeRef = function'), { AscCommon });
SortState.prototype.clone = make(fn(elems, 'SortState.prototype.clone = function'), { SortState });
SortCondition.prototype.clone = make(fn(elems, 'SortCondition.prototype.clone = function'), { SortCondition });
const sortChangeRefOnRange = fn(elems, 'SortState.prototype.changeRefOnRange = function', true);
if (sortChangeRefOnRange) SortState.prototype.changeRefOnRange = make(sortChangeRefOnRange, { Asc });
AscCommonExcel.SortState = SortState;
AscCommonExcel.SortCondition = SortCondition;

/* --- the real table / autofilter methods --- */
const TP = {
	changeRef: make(fn(elems, 'TablePart.prototype.changeRef = function'), { AscCommon }),
	changeRefOnRange: make(fn(elems, 'TablePart.prototype.changeRefOnRange = function'), { Asc,
		/* a column added by a resize: only its name is touched */
		TableColumn: function () { this.name = null; this.getTableColumnName = () => this.name; this.setTableColumnName = n => { this.name = n; }; } }),
	getRangeWithoutHeaderFooter: make(fn(elems, 'TablePart.prototype.getRangeWithoutHeaderFooter = function'), { Asc }),
	isTotalsRow: make(fn(elems, 'TablePart.prototype.isTotalsRow = function')),
	isAutoFilter: make(fn(elems, 'TablePart.prototype.isAutoFilter = function')),
	isHeaderRow: make(fn(elems, 'TablePart.prototype.isHeaderRow = function')),
};
const AF = {
	changeRef: make(fn(elems, 'AutoFilter.prototype.changeRef = function'), { AscCommon }),
	changeRefOnRange: make(fn(elems, 'AutoFilter.prototype.changeRefOnRange = function'), { Asc }),
	getRangeWithoutHeaderFooter: make(fn(elems, 'AutoFilter.prototype.getRangeWithoutHeaderFooter = function'), { Asc }),
	isAutoFilter: make(fn(elems, 'AutoFilter.prototype.isAutoFilter = function')),
	isApplyAutoFilter() { return false; },
};

const historyItems = [];
const History = { Create_NewPoint() {}, StartTransaction() {}, EndTransaction() {}, Add(...a) { historyItems.push(a); } };
/* the real table SortState undo record and its undo/redo */
const undoRedo = read('cell/model/UndoRedo.js');
const UndoRedoData_SortState = make(fn(undoRedo, '\tfunction UndoRedoData_SortState'));
AscCommonExcel.UndoRedoData_SortState = UndoRedoData_SortState;
AscCommonExcel.g_oUndoRedoSortState = 'g_oUndoRedoSortState';
const editorWindow = { Asc: { editor: null } };
const sortStateUndoRedo = make(fn(undoRedo, 'UndoRedoSortState.prototype.UndoRedo = function'), { window: editorWindow });
const AscCH = { historyitem_AutoFilter_Change: 'change', historyitem_AutoFilter_Sort: 'sort', historyitem_AutoFilter_ChangeTableRef: 'tableRef',
	historyitem_AutoFilter_ChangeTableInfo: 'tableInfo', historyitem_SortState_Add: 'sortStateAdd' };
const c_oAscChangeTableStyleInfo = { columnFirst: 1, columnLast: 2, columnBanded: 3, rowHeader: 4, rowTotal: 5, rowBanded: 6, filterButton: 7, advancedSettings: 8 };
AscCommonExcel.Range = function () {};
const c_oAscInsertOptions = { InsertCellsAndShiftRight: 1, InsertCellsAndShiftDown: 2, InsertColumns: 3, InsertRows: 4, InsertTableRowAbove: 5 };
const c_oAscDeleteOptions = { DeleteCellsAndShiftLeft: 1, DeleteCellsAndShiftTop: 2, DeleteColumns: 3, DeleteRows: 4, DeleteTable: 5 };
const scope = { Asc, AscCommon, AscCommonExcel, AscCH, History, c_oAscInsertOptions, c_oAscDeleteOptions, c_oAscChangeTableStyleInfo };
const sortColFilterSrc = fn(autofilters, 'sortColFilter: function ');
assert.ok(sortColFilterSrc.includes('onSortAutoFilterCallback'), 'extracted the wrong sortColFilter');
const sortColFilter = make(sortColFilterSrc, scope);
const getPropForSort = make(fn(autofilters, 'getPropForSort: function '), scope);
const insertRows = make(fn(autofilters, 'insertRows: function '), scope);
const changeTableRange = make(fn(autofilters, 'changeTableRange: function '), scope);
const changeFormatTableInfo = make(fn(autofilters, 'changeFormatTableInfo: function '), scope);

const r = (c1, r1, c2, r2) => new Range(c1, r1, c2, r2);
function makeSheet(table) {
	const ws = { AutoFilter: null, TableParts: [], workbook: { bUndoChanges: false, bRedoChanges: false, bCollaborativeChanges: false },
		getRange3() { return {}; }, getId() { return 'sheet1'; }, getCell3() { return { isNullText() { return true; } }; } };
	let filter;
	if (table) {
		/* table A1:C5: header row 1, data rows 2..4, totals row 5; its autofilter A1:C4 */
		filter = Object.assign({
			Ref: r(0, 0, 2, 4), HeaderRowCount: null, TotalsRowCount: 1, DisplayName: 'Table1', SortState: null, QueryTable: null,
			TableStyleInfo: null, handlers: { trigger() {} },
			TableColumns: [0, 1, 2].map(i => ({ getTableColumnName() { return 'C' + i; } })), removeDependencies() {}, buildDependencies() {},
			addAutoFilter() { this.AutoFilter = Object.assign({ Ref: r(this.Ref.c1, this.Ref.r1, this.Ref.c2, this.Ref.r2 - (this.TotalsRowCount ? 1 : 0)), SortState: null }, AF); },
			/* TablePart.clone copies Ref and a SortState clone (only these are read by changeTableRange) */
			clone() { return { Ref: this.Ref.clone(), DisplayName: this.DisplayName, SortState: this.SortState && this.SortState.clone() }; },
		}, TP);
		filter.AutoFilter = Object.assign({ Ref: r(0, 0, 2, 3), SortState: null }, AF);
		ws.TableParts.push(filter);
	} else {
		/* sheet autofilter A1:C4 */
		filter = Object.assign({ Ref: r(0, 0, 2, 3), SortState: null, clone() { return { Ref: this.Ref.clone() }; } }, AF);
		ws.AutoFilter = filter;
	}
	const autoFilters = {
		worksheet: ws, getPropForSort, sortColFilter, insertRows,
		_getFilterByDisplayName(name) { return name ? ws.TableParts.find(t => t.DisplayName === name) || null : null; },
		searchRangeInTableParts() { return -1; },
		expandRange(ref) { return ref; },
		_addHistoryObj(obj, type, redo) { if (type === AscCH.historyitem_AutoFilter_ChangeTableRef) this.lastResize = obj; },
		_setColorStyleTable() {}, _cleanStyleTable() {}, updateSlicer() {}, changeTableRange, changeFormatTableInfo,
		_clearRange() {}, _generateColumnName2() { return 'Column'; }, _openHiddenRows() {}, _isEmptyRange() { return true; },
	};
	return { filter, autoFilters };
}
/* "sortB" = asc_sortColFilter from the filter button of column B (cellId is the column index in the filter) */
const sort = (sh, colIndex, type) => sh.autoFilters.sortColFilter(type || Asc.c_oAscSortOptions.Ascending, colIndex,
	r(colIndex, 0, colIndex, 0), null, sh.filter.DisplayName);
const rows = (sh, type, r1, r2, opt) => sh.autoFilters.insertRows(type, r(0, r1, 2, r2), opt);
const state = f => f.SortState.Ref.getName() + ' [' + f.SortState.SortConditions.map(c => c.Ref.getName()).join(',') + ']';

/* 1. first and second sort on a table with a totals row */
const t = makeSheet(true);
sort(t, 1);
assert.strictEqual(state(t.filter), 'A2:C4 [B2:B4]',
	'sorting table A1:C5 (totals row 5) on B must give <sortState ref="A2:C4"><sortCondition ref="B2:B4"> as Excel does (got ' + state(t.filter) + ')');
sort(t, 2, Asc.c_oAscSortOptions.Descending);
assert.strictEqual(state(t.filter), 'A2:C4 [C2:C4]',
	'a second sort (on C) must keep the sort range on all data rows and columns (got ' + state(t.filter) + ')');
assert.strictEqual(t.filter.SortState.SortConditions[0].ConditionDescending, true);

/* 2. rows inserted / deleted inside the table, then the totals row deleted ("totals row off") */
rows(t, 'insCell', 2, 2, c_oAscInsertOptions.InsertRows);
assert.strictEqual(t.filter.Ref.getName(), 'A1:C6');
assert.strictEqual(state(t.filter), 'A2:C5 [C2:C5]', 'inserting row 3 must grow the sort condition with the sort range (got ' + state(t.filter) + ')');
rows(t, 'delCell', 1, 1, c_oAscDeleteOptions.DeleteRows);
assert.strictEqual(state(t.filter), 'A2:C4 [C2:C4]', 'deleting row 2 must shrink the sort condition with the sort range (got ' + state(t.filter) + ')');
rows(t, 'delCell', 4, 4, c_oAscDeleteOptions.DeleteCellsAndShiftTop);
assert.deepStrictEqual([t.filter.Ref.getName(), t.filter.TotalsRowCount], ['A1:C4', null]);
assert.strictEqual(state(t.filter), 'A2:C4 [C2:C4]', 'removing the totals row leaves the data rows and their sort condition (got ' + state(t.filter) + ')');

/* 3. resizing the table (no totals row now) to A1:C7, then back to A1:C3 */
t.filter.changeRefOnRange(r(0, 0, 2, 6), t.autoFilters);
assert.strictEqual(state(t.filter), 'A2:C7 [C2:C7]', 'resizing the table to A1:C7 must fit the sort range and condition to its data rows (got ' + state(t.filter) + ')');
t.filter.changeRefOnRange(r(0, 0, 2, 2), t.autoFilters);
assert.strictEqual(state(t.filter), 'A2:C3 [C2:C3]');

/* 4. a sheet AutoFilter A1:C4 (not a table) */
const a = makeSheet(false);
sort(a, 1);
assert.strictEqual(state(a.filter), 'A2:C4 [B2:B4]', 'sorting autofilter A1:C4 on B (got ' + state(a.filter) + ')');
sort(a, 2);
assert.strictEqual(state(a.filter), 'A2:C4 [C2:C4]', 'second sort of autofilter A1:C4 on C (got ' + state(a.filter) + ')');
rows(a, 'insCell', 2, 2, c_oAscInsertOptions.InsertRows);
assert.deepStrictEqual([a.filter.Ref.getName(), state(a.filter)], ['A1:C5', 'A2:C5 [C2:C5]']);

/* 5. resizing a table so that its sorted column leaves it drops the condition (here the whole SortState); undo
 * (SortState record first, then the resize's own undo = resize back) restores it, redo drops it again */
{
	const sh = makeSheet(true), ws = sh.autoFilters.worksheet;
	editorWindow.Asc.editor = { wb: { getWorksheetById() { return { model: { autoFilters: sh.autoFilters } }; } } };
	const undoRedoThis = { wb: { getWorksheetById() { return {}; } } };
	sort(sh, 2);
	assert.strictEqual(state(sh.filter), 'A2:C4 [C2:C4]');
	historyItems.length = 0;
	sh.autoFilters.changeTableRange('Table1', r(0, 0, 1, 4));
	const kept = sh.filter.SortState && state(sh.filter);
	assert.strictEqual(sh.filter.SortState, null,
		'resizing table A1:C5 sorted on C to A1:B5 must drop the sortState whose only condition is on C (got ' + kept + ')');
	const rec = historyItems.filter(h => h[1] === AscCH.historyitem_SortState_Add);
	assert.strictEqual(rec.length, 1, 'the dropped SortState must be kept in the history');
	const data = rec[0][4];
	assert.deepStrictEqual([state({ SortState: data.from }), data.to, data.bFilter, data.tableName], ['A2:C4 [C2:C4]', null, true, 'Table1']);
	/* undo: the transaction is undone last item first */
	ws.workbook.bUndoChanges = true;
	sortStateUndoRedo.call(undoRedoThis, AscCH.historyitem_SortState_Add, data, 'sheet1', true);
	sh.autoFilters.changeTableRange('Table1', sh.autoFilters.lastResize.moveFrom);
	ws.workbook.bUndoChanges = false;
	assert.strictEqual(sh.filter.Ref.getName(), 'A1:C5');
	assert.strictEqual(state(sh.filter), 'A2:C4 [C2:C4]', 'undo of the resize must bring the sort condition back');
	ws.workbook.bRedoChanges = true;
	sh.autoFilters.changeTableRange('Table1', r(0, 0, 1, 4));
	sortStateUndoRedo.call(undoRedoThis, AscCH.historyitem_SortState_Add, data, 'sheet1', false);
	ws.workbook.bRedoChanges = false;
	assert.strictEqual(sh.filter.SortState, null);
	assert.strictEqual(historyItems.filter(h => h[1] === AscCH.historyitem_SortState_Add).length, 1, 'undo/redo must not add history');
	/* the history copy was not changed by the redo */
	assert.strictEqual(state({ SortState: data.from }), 'A2:C4 [C2:C4]');
}

/* 6. a sorted table's header row turned off and on again (row above empty): the sort range stays on the data rows */
{
	const sh = makeSheet(true);
	sort(sh, 1);
	sh.filter.Ref = r(0, 1, 2, 5); sh.filter.AutoFilter.Ref = r(0, 1, 2, 4); /* table A2:C6: row 1 above it is free */
	sh.filter.SortState.Ref = r(0, 2, 2, 4); sh.filter.SortState.SortConditions[0].Ref = r(1, 2, 1, 4);
	sh.autoFilters.changeFormatTableInfo('Table1', c_oAscChangeTableStyleInfo.rowHeader, false);
	assert.deepStrictEqual([sh.filter.Ref.getName(), sh.filter.HeaderRowCount], ['A3:C6', 0]);
	assert.strictEqual(state(sh.filter), 'A3:C5 [B3:B5]',
		'turning the header row of table A2:C6 off must leave the sort range on data rows 3..5 (got ' + state(sh.filter) + ')');
	sh.autoFilters.changeFormatTableInfo('Table1', c_oAscChangeTableStyleInfo.rowHeader, true);
	assert.deepStrictEqual([sh.filter.Ref.getName(), sh.filter.HeaderRowCount], ['A2:C6', null]);
	assert.strictEqual(state(sh.filter), 'A3:C5 [B3:B5]', 'turning the header row back on (got ' + state(sh.filter) + ')');
}

console.log('ok - a sorted table/autofilter keeps its sortState and sortCondition on the data rows through sorts, row changes, resizes and header toggles');
