/*
 * #1868 (caret half) - a spreadsheet saved from the desktop reopened with the
 * cursor where it was when the file was OPENED, not where the user left it.
 *
 * Moving the caret is view state: it changes Worksheet.selectionRange and
 * records no History entry, and a desktop save ships *changes* that x2t
 * replays onto the Editor.bin written at open time - so the <selection> in the
 * saved sheetView was the open-time one. The scroll half was fixed by sending
 * "topLeftCells" in the save parameters (sdkjs getAdditionalSaveParams + core
 * fileOptions/@topLeftCells). Fix: the same channel carries "activeCells",
 * "<sheet index>:<active cell>:<range holding it>" per viewed sheet, on Save
 * As and on a plain Save; core applies it to the sheetView's selection
 * (fork-fix-tests/issue-1868-active-cell-x2t covers that side).
 *
 * This extracts the REAL getAdditionalSaveParams and
 * DesktopOfflineAppDocumentStartSave from sdkjs cell/Local/api.js and runs
 * them against stubs: three sheets, two with views (caret on C5, and on B2
 * inside the range B2:D7), one never opened.
 * Claimed: both a plain Save and Save As hand the host
 * activeCells "0:C5:C5;1:B2:B2:D7"; a sheet without a view is not listed.
 * NOT claimed: the x2t side here; the GUI; multi-range selections (only the
 * range holding the caret is sent).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the source at
 * BASE_REF with git; it must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/Local/api.js';
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '68457630dd^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function extract(marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found in ' + REL);
	const from = source.indexOf('function', at);
	const open = source.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < source.length; i++) {
		if (source[i] === '{') depth++;
		else if (source[i] === '}' && --depth === 0) return source.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
const startSaveSrc = extract('window["DesktopOfflineAppDocumentStartSave"] = function');
const saveParamsSrc = extract('spreadsheet_api.prototype["getAdditionalSaveParams"] = function');

function selection(activeRow, activeCol, r1, c1, r2, c2) {
	return { activeCell: { row: activeRow, col: activeCol }, getLast: () => ({ r1, c1, r2, c2 }) };
}

function run(isSaveAs, options) {
	const calls = [];
	const editor = {
		currentPassword: undefined,
		sync_StartAction() {},
		getPrintOptionsJson: () => ({ spreadsheetLayout: { ignorePrintArea: false, sheetsProps: {} } }),
		asc_getLocale: () => 1033,
		wbModel: { getActive: () => 0 },
		wb: { wsViews: [
			{ getCurrentTopLeftCell: () => null, model: { selectionRange: selection(4, 2, 4, 2, 4, 2) } },
			{ getCurrentTopLeftCell: () => null, model: { selectionRange: selection(1, 1, 1, 1, 6, 3) } },
			undefined,
		] },
	};
	const window = { AscDesktopEditor: { LocalFileSave: function () { calls.push(Array.from(arguments)); } } };
	const asc = { editor };
	const Asc = { c_oAscAsyncActionType: { BlockInteraction: 0 }, c_oAscAsyncAction: { Save: 0 } };
	const AscCommon = {
		EncryptionWorker: { isNeedCrypt: () => false },
		translateManager: { mapTranslate: {} },
		g_oCellAddressUtils: { colnumToColstr: n => String.fromCharCode(64 + n) },
	};
	editor.getAdditionalSaveParams = new Function('asc', 'AscCommon', '"use strict"; return ' + saveParamsSrc)(asc, AscCommon);
	const startSave = new Function('window', 'asc', 'Asc', 'AscCommon', '"use strict"; return ' + startSaveSrc)(window, asc, Asc, AscCommon);
	startSave(isSaveAs, undefined, undefined, undefined, options);
	assert.strictEqual(calls.length, 1, 'LocalFileSave must be called once');
	return JSON.parse(calls[0][4]);
}

let failed = 0;
for (const [name, isSaveAs, options] of [['plain Save', undefined, undefined], ['Save As xlsx', true, { fileType: 257 }]]) {
	const got = run(isSaveAs, options).activeCells;
	const ok = got === '0:C5:C5;1:B2:B2:D7';
	if (!ok) failed++;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: activeCells = ${JSON.stringify(got)}`);
}
if (failed) {
	console.log('FAIL #1868: the caret does not reach the save parameters' + (process.env.BASELINE ? ' (baseline, as expected)' : ''));
	process.exit(1);
}
console.log('PASS #1868: each viewed sheet\'s caret is sent with the save' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
