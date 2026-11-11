/*
 * #2119 - Spreadsheets: holding Shift while dragging whole rows should insert
 * them between other rows (Excel), not overwrite the target rows.
 *
 * The insert-move existed (feature "drag and drop rows cols"), but Shift was
 * only read once, at mousedown on the row/column header:
 * EventsController.prototype._moveRangeHandle passed {ctrlKey, shiftKey} on
 * the first call, WorksheetView.changeSelectionMoveRangeHandle stored them in
 * startCellMoveRange.colRowMoveProps, and every later mousemove passed nothing.
 * Pressing Shift after the drag had started (the gesture in the report) was
 * ignored, and a drag from the selection border could never insert. The fix
 * passes the live event.shiftKey on every move, through
 * WorkbookView._onMoveRangeHandle, and changeSelectionMoveRangeHandle updates
 * (or, for a border drag, creates) colRowMoveProps for whole-row/column moves.
 *
 * This extracts the REAL EventsController._moveRangeHandle,
 * WorkbookView._onMoveRangeHandle, WorksheetView.changeSelectionMoveRangeHandle
 * and WorksheetView.applyMoveRangeHandle by brace matching, wires them with a
 * small handler bus and stubs (rows 20 px high, a minimal Range), drives a
 * drag of rows 3-4 down to row 8 with Shift pressed only after the drag began,
 * and checks that the drop goes through the insert path (changeWorksheet
 * "insCell" + shift down, then the move, then "delCell" of the source rows).
 *
 * Claimed: Shift pressed mid-drag (header or border drag of whole rows) makes
 * the drop insert; Shift released again makes it a plain move; a drag without
 * Shift is still a plain move. NOT claimed: painting of the insert line in a
 * real browser, the actual cell data after insCell/moveRange (stubbed here;
 * that path is the unchanged upstream one) - a GUI check is needed.
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
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'ff0514e5b7^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

/* --- minimal stand-ins --- */
const MAXC = 16383, MAXR = 1048575;
const c_oAscSelectionType = { RangeCells: 1, RangeCol: 2, RangeRow: 3, RangeMax: 4 };
class Range {
	constructor(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
	clone() { return new Range(this.c1, this.r1, this.c2, this.r2); }
	normalize() { return this; }
	assign(c1, r1, c2, r2) { this.c1 = c1; this.r1 = r1; this.c2 = c2; this.r2 = r2; }
	assign2(r) { this.assign(r.c1, r.r1, r.c2, r.r2); }
	isEqual(r) { return r && this.c1 === r.c1 && this.r1 === r.r1 && this.c2 === r.c2 && this.r2 === r.r2; }
	adjustRange() { return null; }
	getType() {
		const row = this.c1 === 0 && this.c2 === MAXC, col = this.r1 === 0 && this.r2 === MAXR;
		return row && col ? 4 : col ? 2 : row ? 3 : 1;
	}
}
const Asc = { c_oAscSelectionType, Range };
const AscCommon = { CellBase: function (r, c) { this.row = r; this.col = c; } };
const c_oAscError = { ID: { No: 0 }, Level: {} };
const c_oAscInsertOptions = { InsertCellsAndShiftRight: 'shiftRight', InsertCellsAndShiftDown: 'shiftDown' };
const c_oAscDeleteOptions = { DeleteCellsAndShiftLeft: 'shiftLeft', DeleteCellsAndShiftTop: 'shiftTop' };
const History = { Create_NewPoint() {}, StartTransaction() {}, EndTransaction() {} };

const ws = src('cell/view/WorksheetView.js');
const wb = src('cell/view/WorkbookView.js');
const ec = src('cell/view/EventsController.js');
const WorksheetView = function () {}, WorkbookView = function () {}, asc_CEventsController = function () {};
new Function('WorksheetView', 'WorkbookView', 'asc_CEventsController', 'asc_Range', 'c_oAscSelectionType', 'Asc',
	'AscCommon', 'c_oAscError', 'c_oAscInsertOptions', 'c_oAscDeleteOptions', 'History', 'asc_applyFunction',
	extract(ws, 'WorksheetView.prototype.changeSelectionMoveRangeHandle = function') + ';\n' +
	extract(ws, 'WorksheetView.prototype.applyMoveRangeHandle = function') + ';\n' +
	extract(wb, 'WorkbookView.prototype._onMoveRangeHandle = function') + ';\n' +
	extract(ec, 'asc_CEventsController.prototype._moveRangeHandle = function') + ';\n')(
	WorksheetView, WorkbookView, asc_CEventsController, Range, c_oAscSelectionType, Asc, AscCommon, c_oAscError,
	c_oAscInsertOptions, c_oAscDeleteOptions, History, (f, ...a) => f && f(...a));

/* --- one drag on a fresh sheet: rows 3-4 (0-based 2..3) selected --- */
function drag(steps, opts) {
	const calls = [];
	const sel = new Range(0, 2, MAXC, 3);
	const sheet = Object.assign(new WorksheetView(), {
		startCellMoveRange: null, activeMoveRange: null, dragAndDropRange: null,
		cellsTop: 20, cellsLeft: 40,
		drawingCtx: { getHeight: () => 1000, getWidth: () => 1000 },
		model: {
			selectionRange: { getLast: () => sel },
			workbook: { handlers: { trigger() {} } },
			isUserProtectedRangesIntersection: () => false, getSheetProtection: () => false,
			isLockedRange: () => false, checkMovePivotTable: () => 0, _prepareMoveRange: () => 0,
		},
		af_changeSelectionTablePart() {}, cleanSelection() {}, _drawSelection() {},
		_cleanSelectionMoveRange() { this.activeMoveRange = null; this.startCellMoveRange = null; calls.push('clean'); },
		_findColUnderCursor: () => ({ col: 0 }),
		_findRowUnderCursor: (y) => ({ row: Math.floor((y - 20) / 20) }),
		checkMoveFormulaArray: () => true,
		changeWorksheet(prop, val, cb) { calls.push(prop + ':' + val + '@' + sel.r1 + '-' + sel.r2); cb(true); },
		moveRangeHandle(from, to, ctrl, x, cb) { calls.push('move ' + from.r1 + '-' + from.r2 + '>' + to.r1 + '-' + to.r2); cb && cb(true); },
		setSelection() {},
	});
	const book = Object.assign(new WorkbookView(), { getWorksheet: () => sheet });
	const bus = { trigger(name, ...a) { assert.strictEqual(name, 'moveRangeHandle'); book._onMoveRangeHandle(...a); } };
	const ctl = Object.assign(new asc_CEventsController(), {
		handlers: bus, scroll() {},
		_getCoordinates: (e) => ({ x: 100, y: e.y }),
	});
	const rowY = (r) => 20 + r * 20 + 5;
	// mousedown: header drag passes props, border drag (MoveRange target) passes none
	ctl._moveRangeHandle({ y: rowY(2), shiftKey: false }, null, opts.header ? { ctrlKey: false, shiftKey: false } : undefined);
	for (const s of steps) ctl._moveRangeHandle({ y: rowY(s.row), shiftKey: s.shift });
	sheet.applyMoveRangeHandle(false);
	return calls;
}

let failed = 0;
function check(name, calls, expectInsert) {
	const inserted = calls.some((c) => c.startsWith('insCell:shiftDown'));
	const ok = inserted === expectInsert && calls.some((c) => c.startsWith('move '));
	console.log((ok ? 'ok   ' : 'FAIL ') + name + ' -> ' + calls.join(', '));
	if (!ok) failed++;
}

check('header drag, Shift pressed after the drag started, drop inserts',
	drag([{ row: 5, shift: false }, { row: 8, shift: true }, { row: 8, shift: true }], { header: true }), true);
check('border drag of whole rows, Shift pressed mid-drag, drop inserts',
	drag([{ row: 5, shift: false }, { row: 8, shift: true }], { header: false }), true);
check('Shift pressed then released again, drop is a plain move',
	drag([{ row: 6, shift: true }, { row: 8, shift: false }], { header: true }), false);
check('no Shift at all, drop is a plain move',
	drag([{ row: 5, shift: false }, { row: 8, shift: false }], { header: false }), false);

if (failed) { console.log(failed + ' check(s) failed'); process.exit(1); }
console.log('PASS #2119: Shift during a whole-row drag switches to insert-between-rows');
