/*
 * #1490 - "Add a (more comprehensible) dialog when saving multi-sheet as CSV". The
 * reporter lost two hours of work: Save As CSV warns that only the active sheet is
 * kept, but a plain Save of a file opened from .csv (Ctrl+S, the Save button, File >
 * Save, "Save" before closing) wrote CSV again without a word, and every other sheet
 * was gone. That is data loss, not a wording problem.
 *
 * In the desktop, every plain Save of a spreadsheet goes through asc_Save in
 * sdkjs/cell/Local/api.js, which called DesktopOfflineAppDocumentStartSave at once;
 * desktop-sdk saves in place when the format can be written (csv/tsv can), and x2t
 * exports only the active sheet. The fix: asc_Save asks via asc_onConfirmAction
 * (Asc.c_oAscConfirm.ConfirmSaveCsvSheets) when the file it writes back to ends in
 * .csv/.tsv (AscDesktopEditor.LocalFileGetSourcePath, which follows Save As) and the
 * workbook has more than one sheet. "Save" keeps the format; anything else opens Save
 * As. web-apps Main.onConfirmAction shows the existing, translated
 * SSE.Controllers.LeftMenu.warnDownloadCsvSheets with its Save button (never used before).
 *
 * This extracts the REAL asc_Save and _isSaveDroppingSheets from cell/Local/api.js and the
 * REAL c_oAscConfirm table from common/commonDefines.js (sdkjs), and the REAL
 * ConfirmSaveCsvSheets case of web-apps Main.js onConfirmAction, and drives them with
 * stubs: a host that records DesktopOfflineAppDocumentStartSave calls and a
 * Common.UI.warning that records the dialog and answers it.
 *
 * Claimed: csv/tsv + 2 sheets: no save until answered; Save -> plain save; Cancel ->
 * Save As; 1 sheet, an xlsx, Save As, autosave: saved at once as before. NOT claimed:
 * the native save itself (unchanged); the dialog's look (GUI check in the app).
 *
 *   RD_REPO=<sdkjs>  RD_WEBAPPS=<web-apps>  (defaults ../sdkjs, ../web-apps)
 *   BASELINE=1 reads sdkjs from BASE_REF -> must FAIL (it saves at once, no question).
 *   The web-apps half is read from RD_WEBAPPS as is (not part of the baseline).
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '80e0954ad1^';

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

const local = src('cell/Local/api.js');
const defines = src('common/commonDefines.js');
const c_oAscConfirm = new Function('return ' + matched(defines, defines.indexOf('var c_oAscConfirm ='), '{'))();

/* --- the editor, with the real methods --- */
const host = { path: '', starts: [] };
const window = {
	AscDesktopEditor: { LocalFileGetSourcePath: () => host.path },
	DesktopOfflineAppDocumentStartSave: (isSaveAs) => host.starts.push(isSaveAs === true ? 'save as' : 'save'),
};
const Asc = { c_oAscConfirm };
const AscCommon = { c_oAscAdvancedOptionsAction: { None: 0 }, History: { UserSavedIndex: 0 } };

function Api(sheets) {
	this.canSave = true;
	this.advancedOptionsAction = 0;
	this.wbModel = { getWorksheetCount: () => sheets };
	this.confirm = null;
	const self = this;
	this.handlers = {
		handlers: { asc_onConfirmAction: true },
		trigger(name, id, cb) { self.confirm = { name, id, cb }; },
	};
	this.CoAuthoringApi = { askSaveChanges() {} };
}
Api.prototype.isFrameEditor = () => false;
Api.prototype.asc_closeCellEditor = () => {};
Api.prototype._saveLocalCheck = () => true;
Api.prototype._onSaveCallback = () => {};
const make = (marker) => new Function('window', 'Asc', 'AscCommon', 'return ' + fnAt(local, marker) + ';')(window, Asc, AscCommon);
Api.prototype.asc_Save = make('spreadsheet_api.prototype.asc_Save = function');
if (local.includes('spreadsheet_api.prototype._isSaveDroppingSheets = function'))
	Api.prototype._isSaveDroppingSheets = make('spreadsheet_api.prototype._isSaveDroppingSheets = function');

/* --- the dialog: the real web-apps case, with a recording Common.UI.warning --- */
const mainJs = fs.readFileSync(path.join(WEBAPPS, 'apps/spreadsheeteditor/main/app/controller/Main.js'), 'utf8');
const caseAt = mainJs.indexOf('case Asc.c_oAscConfirm.ConfirmSaveCsvSheets:');
assert.notStrictEqual(caseAt, -1, 'web-apps Main.onConfirmAction has no ConfirmSaveCsvSheets case');
const caseBody = mainJs.slice(mainJs.indexOf(':', caseAt) + 1, mainJs.indexOf('break;', caseAt));
const leftMenuStrings = { warnDownloadCsvSheets: 'The CSV format does not support saving a multi-sheet file. ...', textSave: 'Save' };
function showDialog(apiCallback, answer) {
	let shown = null;
	const Common = { UI: { warning(opts) { shown = opts; } } };
	const _ = { bind: (f, ctx) => f.bind(ctx) };
	const ctrl = { notcriticalErrorTitle: 'Warning', getApplication: () => ({ getController: (n) => n === 'LeftMenu' ? leftMenuStrings : null }) };
	new Function('Common', '_', 'apiCallback', caseBody).call(ctrl, Common, _, apiCallback);
	assert.ok(shown, 'no dialog shown');
	shown.callback(answer);
	return shown;
}

let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(58)} ${JSON.stringify(got).padEnd(22)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}

function run(what, file, sheets, args, answer) {
	host.path = file; host.starts = [];
	const api = new Api(sheets);
	api.asc_Save.apply(api, args);
	const asked = !!api.confirm;
	if (asked) {
		assert.strictEqual(api.confirm.id, c_oAscConfirm.ConfirmSaveCsvSheets);
		const dlg = showDialog(api.confirm.cb, answer);
		assert.ok(/multi-sheet/.test(dlg.msg) && dlg.buttons[0].caption === 'Save', 'the dialog must show the CSV sheets warning with a Save button');
	}
	check(what, { asked, saves: host.starts }, arguments[5]);
}

console.log('sdkjs ' + (process.env.BASELINE ? '@ ' + BASE_REF : SDKJS));
run('book.csv, 2 sheets, Ctrl+S, answer Save', '/h/u/book.csv', 2, [], 'ok', { asked: true, saves: ['save'] });
run('book.csv, 2 sheets, Ctrl+S, answer Cancel -> Save As', '/h/u/book.csv', 2, [], 'cancel', { asked: true, saves: ['save as'] });
run('book.TSV, 3 sheets, Save before closing (asc_Save(false))', '/h/u/book.TSV', 3, [false], 'ok', { asked: true, saves: ['save'] });
run('book.csv, 1 sheet, Ctrl+S', '/h/u/book.csv', 1, [], null, { asked: false, saves: ['save'] });
run('book.xlsx, 2 sheets, Ctrl+S', '/h/u/book.xlsx', 2, [], null, { asked: false, saves: ['save'] });
run('book.csv, 2 sheets, Save As (has its own warning)', '/h/u/book.csv', 2, [false, true], null, { asked: false, saves: ['save as'] });
run('book.csv, 2 sheets, autosave (isNoUserSave)', '/h/u/book.csv', 2, [true], null, { asked: false, saves: [] });

console.log(failures ? '\nFAILED' : '\nok - a plain Save that would drop sheets asks first');
process.exit(failures ? 1 : 0);
