/*
 * #1905 - "Move sheet to new workbook". In the Move or Copy dialog (sheet tab context menu),
 * choosing "(new spreadsheet)" with "Create a copy" UNticked must MOVE the sheet: open it in
 * a new, unsaved workbook and take it out of this one. It copied instead - the sheet stayed.
 * (The reporter's other point, the new tab showing the whole workbook, was #2278 and is
 * already fixed in desktop-sdk 62d208bb.)
 *
 * Cause: sdkjs cell/api.js asc_moveWorksheet, for arrBooks = [] (the "new" entry), only
 * called copyToNewWorkbook; the sibling branch for another open workbook deletes the
 * sheets after sending them, this one never did. Fix: copyToNewWorkbook now returns
 * whether the host accepted the binary (AscDesktopEditor.OpenWorkbook returns true once
 * EditorForAsLocal.bin is written - see desktop-sdk client_renderer_wrapper.cpp), and
 * the move deletes the sheets only then, so a failed hand-over never loses them.
 * Checked in the real engine (docbuilder, .rd-work/wt/du-tmp/db/t4.js): copyToNewWorkbook([1]) on a
 * 3-sheet xlsx yields a binary that the real BinaryFileReader reads back as that one sheet.
 *
 * This extracts the REAL asc_moveWorksheet, asc_copyWorksheet and copyToNewWorkbook from
 * cell/api.js and drives them with stubs: a host that records OpenWorkbook, a writer that
 * "serialises" the tab-selected sheets, and an asc_deleteWorksheet that records what it is
 * asked to remove (and, like the real one, refuses to remove every sheet).
 *
 * Claimed: move to new -> new tab gets only the chosen sheet(s) AND they are deleted
 * here; copy to new -> not deleted; host failed to take the binary -> not deleted; not a
 * local file -> nothing happens (as before). NOT claimed: the GUI dialog itself and the
 * new tab's title (it still shows the source file name, unsaved - unchanged; GUI check).
 *
 *   RD_REPO=<sdkjs> (default ../sdkjs).  BASELINE=1 reads BASE_REF -> must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'd829164103^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function matched(text, from, open) {
	const close = open === '{' ? '}' : ']';
	const start = text.indexOf(open, from);
	let depth = 0;
	for (let i = start; i < text.length; i++) {
		if (text[i] === open) depth++;
		else if (text[i] === close && --depth === 0) return text.slice(start, i + 1);
	}
	throw new Error('unbalanced ' + open);
}
function fnAt(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	const p = text.indexOf('(', at + marker.length - 10);
	return 'function' + text.slice(p, text.indexOf(')', p) + 1) + matched(text, p, '{');
}

const api = src('cell/api.js');

const host = { local: true, accept: true, opened: [] };
const window = {
	AscDesktopEditor: {
		IsLocalFile: () => host.local,
		OpenWorkbook: (b64) => { host.opened.push(Buffer.from(b64, 'base64').toString()); return host.accept; },
	},
};
const AscCommon = { Base64: { encode: (s) => Buffer.from(s).toString('base64') } };
const AscCommonExcel = {
	// Stands in for the real writer, which walks the sheets the way BinaryWorksheetsTableWriter
	// does: wb.forEach(cb, isCopyPaste (undefined here), InitSaveManager.writeOnlySelectedTabs).
	BinaryFileWriter: function (wbModel) {
		this.InitSaveManager = {};
		this.Write = () => {
			const out = [];
			wbModel.forEach((ws) => out.push(ws.name), undefined, this.InitSaveManager.writeOnlySelectedTabs);
			return out.join(',');
		};
	},
};

/* REAL Workbook.prototype.forEach and Worksheet.prototype.isSelectedTab (cell/model/Workbook.js) */
const wbJs = src('cell/model/Workbook.js');
const wbForEach = new Function('return ' + fnAt(wbJs, 'Workbook.prototype.forEach = function'))();
const isSelectedTab = new Function('return ' + fnAt(wbJs, 'Worksheet.prototype.isSelectedTab = function'))();

// tabSelected is false after open: the binary reader skips c_oSer_SheetView.TabSelected.
function Api(names) {
	const sheets = names.map((name) => ({ name, sheetViews: [{ tabSelected: false }], isSelectedTab }));
	this.wbModel = { sheets, aWorksheets: sheets, forEach: wbForEach, getActiveWs: () => sheets[0], getActive: () => 0 };
	this.wb = { executeWithCurrentTopLeftCell: (f) => f() };
	this.deleted = [];
}
Api.prototype.asc_deleteWorksheet = function (arr) {
	if (arr.length === this.wbModel.sheets.length) return false;
	this.deleted.push(arr.slice());
	return true;
};
Api.prototype.sendSheetsToOtherBooks = () => {};
Api.prototype.removeDocumentInfoEvent = () => {};
const make = (marker) => new Function('window', 'AscCommon', 'AscCommonExcel', 'return ' + fnAt(api, marker) + ';')(window, AscCommon, AscCommonExcel);
Api.prototype.asc_moveWorksheet = make('spreadsheet_api.prototype.asc_moveWorksheet = function');
Api.prototype.asc_copyWorksheet = make('spreadsheet_api.prototype.asc_copyWorksheet = function');
Api.prototype.copyToNewWorkbook = make('spreadsheet_api.prototype.copyToNewWorkbook = function');

let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(52)} ${JSON.stringify(got).padEnd(40)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}
// The dialog's handler for workbook === 'new': arrBooks = [], arrNames = the sheets' names.
function run(what, op, sheets, opts, want) {
	host.local = opts.local !== false; host.accept = opts.accept !== false; host.opened = [];
	const a = new Api(['Sheet1', 'Sheet2', 'Sheet3']);
	const names = sheets.map((i) => a.wbModel.sheets[i].name);
	if (op === 'move') a.asc_moveWorksheet(0, sheets, names, []);
	else a.asc_copyWorksheet(0, names, sheets, []);
	check(what, { opened: host.opened, deleted: a.deleted, tabs: a.wbModel.sheets.map((s) => s.sheetViews[0].tabSelected) }, want);
}

console.log('sdkjs ' + (process.env.BASELINE ? '@ ' + BASE_REF : SDKJS));
const TABS = [false, false, false];
run('move Sheet2 to new workbook', 'move', [1], {}, { opened: ['Sheet2'], deleted: [[1]], tabs: TABS });
run('move Sheet2+Sheet3 to new workbook', 'move', [1, 2], {}, { opened: ['Sheet2,Sheet3'], deleted: [[1, 2]], tabs: TABS });
run('move Sheet1', 'move', [0], {}, { opened: ['Sheet1'], deleted: [[0]], tabs: TABS });
run('copy Sheet2 to new workbook (Create a copy)', 'copy', [1], {}, { opened: ['Sheet2'], deleted: [], tabs: TABS });
run('move, host could not take the binary', 'move', [1], { accept: false }, { opened: ['Sheet2'], deleted: [], tabs: TABS });
run('move, not a local file (no new tab)', 'move', [1], { local: false }, { opened: [], deleted: [], tabs: TABS });

console.log(failures ? '\nFAILED' : '\nok - Move to a new workbook removes the sheet here once the new tab has it');
process.exit(failures ? 1 : 0);
