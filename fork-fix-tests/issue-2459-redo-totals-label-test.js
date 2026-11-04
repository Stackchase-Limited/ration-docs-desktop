/*
 * #2459 (follow-up) - paste a formatted table whose totals row has a label
 * ("Total" in the first column) and a SUBTOTAL total, then Undo and Redo: the
 * column's TotalsRowLabel came back empty. The cell still showed "Total", but
 * turning the totals row off and on again left it blank, and the saved xlsx
 * had totalsRowLabel="" and an empty cell. Co-editors got the empty label too.
 *
 * Cause: the paste records historyitem_AutoFilter_Add holding the clipboard's
 * TablePart as a snapshot; redo (and x2t's replay of the desktop save) rebuild
 * the table from it. Serializing that record, UndoRedoData_AutoFilter
 * .getProperty (cell/model/UndoRedo.js) passed the destination sheet to
 * BinaryTableWriter.WriteTable (cell/model/Serialize.js), which calls
 * TablePart.syncTotalLabels(ws) (cell/model/WorkbookElems.js). That reads the
 * totals-row cell at the snapshot's own Ref - the SOURCE position - in the
 * destination sheet, finds it empty and overwrites the snapshot's label with "".
 *
 * This extracts by brace matching the real getProperty, the real WriteTable /
 * WriteTableColumns / WriteTableColumn and the real syncTotalLabels /
 * isTotalsRow, runs them against minimal stubs (a destination sheet whose cell
 * at the source position is empty), and checks that
 *   1. serializing the record leaves the snapshot's label alone and writes it,
 *   2. a table that IS on the sheet is still synced from its cells (the
 *      behaviour upstream added the ws argument for, bug 45731).
 * NOT claimed here: the full paste/undo/redo/x2t flow. That was checked
 * separately in a headless editor + real x2t replay (see the commit message).
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
const BASE_REF = process.env.BASE_REF || '67c0b70be1^';

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

const undoRedo = read('cell/model/UndoRedo.js');
const serialize = read('cell/model/Serialize.js');
const elems = read('cell/model/WorkbookElems.js');

const getPropertySrc = fn(undoRedo, 'UndoRedoData_AutoFilter.prototype.getProperty = function');
assert.ok(getPropertySrc.includes('case this.Properties.tablePart'), 'extracted the wrong getProperty');
const writeTableSrc = fn(serialize, 'this.WriteTable = function');
assert.ok(writeTableSrc.includes('syncTotalLabels'), 'extracted the wrong WriteTable');
const writeColumnsSrc = fn(serialize, 'this.WriteTableColumns = function');
const writeColumnSrc = fn(serialize, 'this.WriteTableColumn = function');
const syncSrc = fn(elems, 'TablePart.prototype.syncTotalLabels = function');
const isTotalsSrc = fn(elems, 'TablePart.prototype.isTotalsRow = function');

const make = (params, src, scope) => {
	const names = Object.keys(scope || {});
	return new Function(...names, '"use strict"; return function' + src)(...names.map(n => scope[n]));
};
const consts = new Proxy({}, { get: (t, k) => typeof k === 'string' ? k : undefined });

/* --- the real TablePart pieces --- */
function TablePart(ref, labels) {
	this.Ref = ref;
	this.DisplayName = 'Table1';
	this.TotalsRowCount = 1;
	this.TableColumns = labels.map(l => ({ TotalsRowLabel: l, TotalsRowFunction: null, TotalsRowFormula: null, Name: 'c' }));
}
TablePart.prototype.syncTotalLabels = make(null, syncSrc, { Asc: { ETotalsRowFunction: { totalrowfunctionCustom: 7 } } });
TablePart.prototype.isTotalsRow = make(null, isTotalsSrc);

const range = (c1, r1, c2, r2) => ({ c1, r1, c2, r2, getName: () => `R${r1}C${c1}:R${r2}C${c2}` });

/* --- the real BinaryTableWriter.WriteTable chain, recording what it writes --- */
function BinaryTableWriter(memory) {
	this.memory = memory;
	this.tableIds = {};
	this.bs = { WriteItem(type, f) { f(); } };
	this.WriteTable = make(null, writeTableSrc, { c_oSer_TablePart: consts });
	this.WriteTableColumns = make(null, writeColumnsSrc, { c_oSer_TableColumns: consts });
	this.WriteTableColumn = make(null, writeColumnSrc, { c_oSer_TableColumns: consts, c_oSerPropLenType: consts });
	this.WriteAutoFilter = this.WriteSortState = this.WriteTableStyleInfo = this.WriteAltTextTable = this.WriteQueryTable = function () {};
}
function CMemory() {
	this.strings = [];
	this.WriteByte = this.WriteLong = this.WriteULong = this.WriteBool = function () {};
	this.WriteString2 = s => this.strings.push(s);
	this.GetBase64Memory = () => this.strings;
}

/* destination sheet: totals-row cells hold `cells[row][col]` */
function makeSheet(cells, tableParts) {
	return {
		TableParts: tableParts,
		getCell3(r, c) {
			const v = (cells[r] && cells[r][c]) || '';
			return { isFormula: () => false, getValue: () => v };
		},
	};
}
function serializeRecord(tablePart, sheetModel) {
	const window = { Asc: { editor: { wb: { model: {}, getWorksheetById: id => (id === 'sheet1' ? { model: sheetModel } : null) } } } };
	const AscCommonExcel = { InitSaveManager: function () {}, BinaryTableWriter };
	const getProperty = make(null, getPropertySrc, { window, AscCommon: { CMemory }, AscCommonExcel, UndoRedoData_BBox: function () {} });
	const data = { Properties: { tablePart: 18 }, tablePart };
	return getProperty.call(data, 18, 'sheet1');
}

/* 1. the paste snapshot: source table A1:E5 ("Total" at A5), pasted to B3:F7 */
{
	const snapshot = new TablePart(range(0, 0, 4, 4), ['Total', null, null, null, null]);
	const pasted = new TablePart(range(1, 2, 5, 6), ['Total', null, null, null, null]);
	const dest = makeSheet({ 6: { 1: 'Total' } }, [pasted]); // A5 (row 4, col 0) is empty here
	const written = serializeRecord(snapshot, dest);
	assert.strictEqual(snapshot.TableColumns[0].TotalsRowLabel, 'Total',
		`serializing the paste record changed the snapshot's label to ${JSON.stringify(snapshot.TableColumns[0].TotalsRowLabel)}; ` +
		'redo rebuilds the table from it and loses the totals-row label');
	assert.ok(written.includes('Total'), 'the record sent to x2t / co-editors must carry the label, got ' + JSON.stringify(written));
}

/* 2. a table that lives on the sheet is still synced from its cells (bug 45731) */
{
	const live = new TablePart(range(1, 2, 5, 6), ['Total', null, null, null, null]);
	const dest = makeSheet({ 6: { 1: 'Gesamt' } }, [live]);
	const written = serializeRecord(live, dest);
	assert.strictEqual(live.TableColumns[0].TotalsRowLabel, 'Gesamt', 'a table of this sheet must take its label from its cell');
	assert.ok(written.includes('Gesamt'), 'and write the synced label');
}

console.log('ok - serializing a table history record keeps the snapshot\'s totals-row label; live tables still sync');
