/*
 * #902 - Saving a spreadsheet to CSV wrote the sheet that was active when the
 * document was opened, not the sheet the user was looking at.
 *
 * The CSV writer in x2t exports one sheet: the workbook's stored activeTab.
 * Which sheet is active is view state (Workbook.prototype.setActive adds no
 * History entry), and a desktop save ships *changes* that x2t replays onto the
 * Editor.bin written at open time, so the stored activeTab is the open-time
 * one. #1839 made the editor send the live sheet as "activeSheet" in the save
 * parameters, and x2t honours it - but DesktopOfflineAppDocumentStartSave in
 * sdkjs/cell/Local/api.js built those parameters only for Save As. A plain Save
 * (Ctrl+S on a .csv, or choosing CSV in the dialog of a new file) passed "" to
 * AscDesktopEditor.LocalFileSave; desktop-sdk's fileconverter.h then wrote its
 * default {"spreadsheetLayout":{"fitToWidth":1,"fitToHeight":1}} and x2t fell
 * back to the stale activeTab.
 *
 * This test extracts the REAL DesktopOfflineAppDocumentStartSave and the REAL
 * getAdditionalSaveParams from cell/Local/api.js by brace matching and runs
 * them against stubs: an editor whose active sheet is 1, a host that records
 * what LocalFileSave receives. It checks that a plain Save now hands the host
 * "activeSheet": 1 (plus, since #547, the sheets' page setup and locale and
 * nothing else of Save As), and that Save As still sends the full parameters.
 *
 * What is NOT claimed here: that x2t exports the sheet named by activeSheet
 * (that is #1839's core change; it was run end to end with the real cell editor
 * in headless Chromium and the payload x2t: Alpha rows before, Beta rows after),
 * nor anything about the native save dialog. Needs a GUI check in the app.
 *
 *   node issue-902-csv-plain-save-active-sheet-test.js            -> passes
 *   BASELINE=1 node issue-902-csv-plain-save-active-sheet-test.js -> fails
 *   RD_REPO=<sdkjs checkout> overrides ../sdkjs; BASE_REF overrides the baseline.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/Local/api.js';
const BASE_REF = process.env.BASE_REF || 'e2d1b5afd8^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found in ' + REL);
	return matched(source, source.indexOf('function', at));
}

const startSaveSrc = extract('window["DesktopOfflineAppDocumentStartSave"] = function');
const saveParamsSrc = extract('spreadsheet_api.prototype["getAdditionalSaveParams"] = function');
assert.ok(startSaveSrc.includes('LocalFileSave'), 'extracted the wrong function');

/* --- stubs --- */
function run(isSaveAs, options) {
	const calls = [];
	const editor = {
		currentPassword: undefined,
		openedAt: undefined,
		sync_StartAction() {},
		getPrintOptionsJson: () => ({ spreadsheetLayout: { ignorePrintArea: false, sheetsProps: {} } }),
		asc_getLocale: () => 1033,
		/* two sheets; the user switched to the second one without editing,
		 * which is what setActive records and nothing else does */
		wbModel: { getActive: () => 1 },
		wb: { wsViews: [
			{ getCurrentTopLeftCell: () => null },
			{ getCurrentTopLeftCell: () => ({ c1: 2, r1: 40 }) },
		] },
	};
	const window = {
		AscDesktopEditor: { LocalFileSave: function () { calls.push(Array.from(arguments)); } },
		g_asc_plugins: undefined,
	};
	const asc = { editor };
	const Asc = { c_oAscAsyncActionType: { BlockInteraction: 0 }, c_oAscAsyncAction: { Save: 0 } };
	const AscCommon = {
		EncryptionWorker: { isNeedCrypt: () => false },
		translateManager: { mapTranslate: {} },
		g_oCellAddressUtils: { colnumToColstr: n => String.fromCharCode(64 + n) },
	};
	const getAdditionalSaveParams = new Function('asc', 'AscCommon', '"use strict"; return ' + saveParamsSrc)(asc, AscCommon);
	editor.getAdditionalSaveParams = getAdditionalSaveParams;
	const startSave = new Function('window', 'asc', 'Asc', 'AscCommon', '"use strict"; return ' + startSaveSrc)(window, asc, Asc, AscCommon);
	startSave(isSaveAs, undefined, undefined, undefined, options);
	assert.strictEqual(calls.length, 1, 'LocalFileSave must be called once');
	return calls[0];
}

/* --- the defect: plain Save (Ctrl+S on a .csv) --- */
{
	const args = run(undefined, undefined);
	const json = args[4];
	assert.ok(json, 'a plain Save must send save parameters: with "" the host falls back to ' +
		'its default and x2t exports the sheet active at open time, not the one on screen (#902)');
	const obj = JSON.parse(json);
	assert.strictEqual(obj.activeSheet, 1, 'the sheet on screen must reach x2t on a plain Save (#902)');
	assert.strictEqual(obj.topLeftCells, '0:A1;1:C41', 'the scroll position rides the same channel (#1868)');
	// #547 replaced the host's fit-to-one-page default with the sheets' own page
	// setup and added the regional setting (a plain Save can end in a PDF);
	// issue-0547-plain-save-pdf-layout-test.js covers that.
	assert.deepStrictEqual(Object.keys(obj).sort(), ['activeSheet', 'locale', 'spreadsheetLayout', 'topLeftCells'],
		'a plain Save must not pick up the rest of the Save As parameters');
	assert.strictEqual(args[0], '', 'a plain Save is not a Save As');
}

/* --- Save As CSV: unchanged, full parameters with the active sheet --- */
{
	const args = run(true, { fileType: 260 });
	const obj = JSON.parse(args[4]);
	assert.strictEqual(args[0], 'saveas=true;');
	assert.strictEqual(args[3], 260);
	assert.strictEqual(obj.activeSheet, 1, 'Save As must keep sending the active sheet (#1839)');
	assert.strictEqual(obj.locale, 1033, 'Save As must keep its full parameters');
	assert.ok(obj.spreadsheetLayout.sheetsProps, 'Save As must keep the print layout');
}

console.log('ok - a plain Save hands x2t the sheet on screen (#902); Save As unchanged');
