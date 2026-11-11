/*
 * #547 - saving a new spreadsheet as PDF put each sheet on ONE page, text shrunk
 * to fit ("PDF export tries to fit everything on one page"). Also the "file was
 * just created, never saved" half of #531. Save As > PDF of the same sheet was
 * fine, and so was the PDF after saving and reopening.
 *
 * The first Save of a new workbook shows the save dialog and PDF is offered
 * there, so that PDF comes from a plain Save. DesktopOfflineAppDocumentStartSave
 * (sdkjs/cell/Local/api.js) sent the Save As parameters only for Save As; for a
 * plain Save it sent "" (later, since #902, the same thing explicitly): the host's
 * default {"spreadsheetLayout":{"fitToWidth":1,"fitToHeight":1}}
 * (desktop-sdk fileconverter.h). asc_nativePrint (cell/api.js) applies a numeric
 * fitToWidth/fitToHeight to every sheet, so the PDF was fit-to-one-page.
 *
 * This extracts by brace matching the REAL DesktopOfflineAppDocumentStartSave and
 * getAdditionalSaveParams from cell/Local/api.js and the REAL getPrintOptionsJson
 * from cell/api.js, runs a plain Save against a recording host, and reads the
 * parameters the way asc_nativePrint does (AscCommon.isNumber on fitToWidth /
 * fitToHeight; sheetsProps for the per-sheet page setup).
 *
 * Claimed: a plain Save no longer forces fit-to-page, carries the sheets' own
 * page setup and the regional setting (locale, so dates follow it - #233), and
 * still carries #902's activeSheet; Save As is unchanged.
 * NOT claimed: the native save dialog. The rendering was checked end to end for
 * the commit (headless cell editor, plain save, our x2t replaying to PDF): a new
 * 170-row sheet gave 1 page before, 4 pages at full size after.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the sources at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'ba80ae077e^';

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
	return block(text, text.indexOf('function', at));
}

const local = src('cell/Local/api.js');
const api = src('cell/api.js');
const startSaveSrc = extract(local, 'window["DesktopOfflineAppDocumentStartSave"] = function');
const saveParamsSrc = extract(local, 'spreadsheet_api.prototype["getAdditionalSaveParams"] = function');
const printJsonSrc = extract(api, 'spreadsheet_api.prototype.getPrintOptionsJson = function');

/* Two sheets with their own page setup, French regional setting. */
const SHEETS = [{ pageSetup: { fitToWidth: 0, fitToHeight: 0, scale: 100 } }, { pageSetup: { scale: 70 } }];

function run(isSaveAs, options) {
	const calls = [];
	const editor = {
		sync_StartAction() {},
		asc_getLocale: () => 1036,
		DocInfo: { Title: 'Book1.xlsx' },
		wbModel: { getActive: () => 1, getPrintOptionsJson: () => SHEETS },
		wb: { wsViews: [] },
	};
	const AscCommon = {
		EncryptionWorker: { isNeedCrypt: () => false },
		translateManager: { mapTranslate: {} },
		cCellFunctionLocal: {},
		g_oCellAddressUtils: { colnumToColstr: n => String.fromCharCode(64 + n) },
	};
	const AscCommonExcel = { cFormulaFunctionToLocale: null };
	editor.getPrintOptionsJson = new Function('AscCommonExcel', 'AscCommon', '"use strict"; return ' + printJsonSrc)(AscCommonExcel, AscCommon);
	const asc = { editor };
	editor.getAdditionalSaveParams = new Function('asc', 'AscCommon', '"use strict"; return ' + saveParamsSrc)(asc, AscCommon);
	const window = { AscDesktopEditor: { LocalFileSave: function () { calls.push(Array.from(arguments)); } } };
	const Asc = { c_oAscAsyncActionType: { BlockInteraction: 0 }, c_oAscAsyncAction: { Save: 0 } };
	new Function('window', 'asc', 'Asc', 'AscCommon', '"use strict"; return ' + startSaveSrc)(window, asc, Asc, AscCommon)
		(isSaveAs, undefined, undefined, undefined, options);
	assert.strictEqual(calls.length, 1, 'LocalFileSave must be called once');
	return calls[0];
}

/* What asc_nativePrint (cell/api.js) takes from spreadsheetLayout. */
const isNumber = (v) => typeof v === 'number' && !isNaN(v);
function forcedFit(layout) {
	return !!layout && (isNumber(layout.fitToWidth) || isNumber(layout.fitToHeight)) &&
		!!(layout.fitToWidth || layout.fitToHeight);
}

/* --- the defect: plain Save of a new workbook, PDF picked in the dialog --- */
{
	const args = run(undefined, undefined);
	assert.strictEqual(args[0], '', 'a plain Save is not a Save As');
	const obj = JSON.parse(args[4] || '{}');
	assert.ok(!forcedFit(obj.spreadsheetLayout),
		'a plain Save forces fitToWidth/fitToHeight ' + JSON.stringify(obj.spreadsheetLayout) +
		': asc_nativePrint fits every sheet on one page, so a PDF chosen in the save dialog is shrunk');
	assert.deepStrictEqual(obj.spreadsheetLayout && obj.spreadsheetLayout.sheetsProps, SHEETS,
		'a plain Save must carry the sheets\' own page setup, as Save As does');
	assert.strictEqual(obj.locale, 1036, 'the regional setting must reach x2t (dates in the PDF, #233)');
	assert.strictEqual(obj.activeSheet, 1, '#902: the sheet on screen must still be sent');
	assert.strictEqual(obj.translate, undefined, 'the rest of the Save As parameters stay out');
}

/* --- Save As PDF: unchanged --- */
{
	const args = run(true, { fileType: 513 });
	const obj = JSON.parse(args[4]);
	assert.strictEqual(args[0], 'saveas=true;');
	assert.ok(!forcedFit(obj.spreadsheetLayout));
	assert.deepStrictEqual(obj.spreadsheetLayout.sheetsProps, SHEETS);
	assert.strictEqual(obj.locale, 1036);
}

console.log('ok - a plain Save sends the sheets\' page setup and locale, not fit-to-one-page (#547)');
