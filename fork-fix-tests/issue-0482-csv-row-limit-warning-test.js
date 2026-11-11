/*
 * DesktopEditors #482 - "Unable to Open a large CSV file".
 *
 * What still goes wrong in 9.4: a csv with more rows than a sheet holds
 * (1048576) opened cut short, with no message. x2t's CSVReader stops at the
 * limit and returns AVS_FILEUTILS_ERROR_CONVERT_ROWLIMITS (94), which x2t counts
 * as success (SUCCEEDED_X2T); the desktop open path (desktop-sdk cefview.cpp,
 * OnFileConvertToEditor -> LocalFile_End) loads Editor.bin and never passes the
 * code on. With a 1100001-row csv: x2t rc=94, the editor opened 1048577 rows and
 * reported nothing; 51424 rows were gone, and saving over the csv loses them.
 * (Big files inside the limit open: a 273 MB, 568455-row csv like the report's
 * opened in the 9.4 editor.)
 *
 * Fix (web-apps, spreadsheeteditor controller/Main.js, onAdvancedOptions): the
 * CSV options dialog already parses the whole file with the chosen options for
 * its preview and hands those records to the handler as settings.data. When
 * there are more of them than a sheet holds, the handler shows a warning with
 * both numbers before passing the options on; the open itself is unchanged.
 *
 * This extracts the REAL onAdvancedOptions (and the controller's maxSheetRows /
 * warnCsvRowLimit) and drives the CSV dialog's handler with stubs.
 *
 * Claimed: over the limit the user gets a warning naming the row count and the
 *   limit, and the open still proceeds with the chosen options; at or under the
 *   limit, and for "save as csv" (mode 2), there is no warning.
 * NOT claimed: the dialog's own row count (settings.data comes from
 *   asc_parseText; counting quirks there are not tested here); how the warning
 *   looks over the load mask (needs a GUI check); files too big for the
 *   renderer's JS heap (they still end on the crash page, not a message).
 *
 *   node fork-fix-tests/issue-0482-csv-row-limit-warning-test.js
 *   BASELINE=1 node fork-fix-tests/issue-0482-csv-row-limit-warning-test.js   # must fail
 *   RD_REPO=<web-apps checkout> overrides ../web-apps; BASE_REF overrides the baseline.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEBAPPS = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
const REL = 'apps/spreadsheeteditor/main/app/controller/Main.js';
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '7ddbfa80c2^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', WEBAPPS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(WEBAPPS, REL), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
const HEAD = 'onAdvancedOptions: function';
const at = source.indexOf(HEAD);
assert.notStrictEqual(at, -1, 'onAdvancedOptions not found in ' + REL);
const srcOnAdvancedOptions = matched(source, at + HEAD.length);
assert.ok(srcOnAdvancedOptions.indexOf('Common.Utils.importTextType.CSV') !== -1, 'wrong onAdvancedOptions');

/* controller members the handler reads; undefined on a tree that has none */
function member(name) {
	const m = source.match(new RegExp('\\n\\s*' + name + ':\\s*(\'(?:[^\'\\\\]|\\\\.)*\'|\\d+)'));
	return m ? eval(m[1]) : undefined;
}

/* --- stubs --- */
const Asc = { c_oAscAdvancedOptionsID: { CSV: 0, DRM: 1 }, c_oAscAsyncActionType: { BlockInteraction: 1 } };
let dialogOptions = null;
const warnings = [];
const Common = {
	Views: { OpenDialog: function (opts) { dialogOptions = opts; this.show = function () {}; } },
	Utils: { importTextType: { CSV: 1, TXT: 2, Paste: 3, Columns: 4, Data: 5, DRM: 0 } },
	UI: { warning: function (cfg) { warnings.push(cfg); } },
	Gateway: { userActionRequired() {}, requestClose() {} },
	Controllers: { Desktop: { requestClose() {} } },
};
Common.Views.OpenDialog.prototype.txtTitle = 'Choose %1 options';
const LoadingDocument = -256;

const onAdvancedOptions = new Function('Asc', 'Common', 'LoadingDocument',
	'"use strict"; return function' + srcOnAdvancedOptions + ';')(Asc, Common, LoadingDocument);

function controller() {
	const calls = [];
	return {
		calls: calls,
		_state: {},
		appOptions: {},
		maxSheetRows: member('maxSheetRows'),
		warnCsvRowLimit: member('warnCsvRowLimit'),
		notcriticalErrorTitle: 'Warning',
		loadMask: { show() {}, hide() {} },
		onLongActionEnd() {},
		api: {
			asc_getDocumentName: () => 'big.csv',
			asc_setAdvancedOptions: (type, opts) => calls.push(['open', type, opts]),
			asc_DownloadAs: (opts) => calls.push(['save', opts]),
		},
	};
}
const advOptions = { asc_getData: () => new Uint8Array(1), asc_getCodePages: () => [], asc_getRecommendedSettings: () => ({}) };
const textOptions = { chosen: true };

/* what the dialog hands its handler: one entry per parsed record */
function records(n) { return { length: n }; }

let failures = 0;
function check(name, fn) {
	warnings.length = 0; dialogOptions = null;
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
function openWith(n, mode) {
	const c = controller();
	onAdvancedOptions.call(c, Asc.c_oAscAdvancedOptionsID.CSV, advOptions, mode, { asc_setAdvancedOptions() {} });
	assert.ok(dialogOptions && typeof dialogOptions.handler === 'function', 'CSV dialog not created');
	dialogOptions.handler.call({}, 'ok', { textOptions: textOptions, data: n === null ? undefined : records(n) });
	return c;
}

check('1100001 records: warning names the row count and the limit, and the file still opens', () => {
	const c = openWith(1100001);
	assert.strictEqual(warnings.length, 1, 'no warning: the rows after 1048576 are dropped silently');
	const msg = String(warnings[0].msg);
	assert.ok(msg.indexOf('1100001') !== -1, 'warning does not give the row count: ' + msg);
	assert.ok(msg.indexOf('1048576') !== -1, 'warning does not give the limit: ' + msg);
	assert.ok(msg.indexOf('%') === -1, 'unfilled placeholder in: ' + msg);
	assert.deepStrictEqual(c.calls, [['open', Asc.c_oAscAdvancedOptionsID.CSV, textOptions]], 'open did not proceed');
});

check('1048577 records (one over): warning', () => {
	openWith(1048577);
	assert.strictEqual(warnings.length, 1, 'no warning one row over the limit');
});

check('exactly 1048576 records, 568455 records, no preview: no warning, file opens', () => {
	for (const n of [1048576, 568455, null]) {
		warnings.length = 0;
		const c = openWith(n);
		assert.strictEqual(warnings.length, 0, 'warning for ' + n + ' records');
		assert.deepStrictEqual(c.calls, [['open', Asc.c_oAscAdvancedOptionsID.CSV, textOptions]], 'open did not proceed for ' + n);
	}
});

check('save as csv (mode 2): no warning, download proceeds', () => {
	const c = openWith(1100001, 2);
	assert.strictEqual(warnings.length, 0, 'warning on save');
	assert.strictEqual(c.calls.length, 1);
	assert.strictEqual(c.calls[0][0], 'save');
});

if (failures) {
	console.log(failures + ' check(s) failed' + (process.env.BASELINE ? ' (BASELINE=1: expected)' : ''));
	process.exit(1);
}
console.log('all checks passed');
