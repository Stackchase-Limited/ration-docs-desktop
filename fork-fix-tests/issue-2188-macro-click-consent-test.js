/*
 * #2188 "Executing a macro via link" (upstream: a feature request for links that
 * run macros). Checked here as a security question: can document content run
 * the document's own code without the macros warning? It could, two ways, under
 * every macros setting including "Disable all":
 *
 * 1. Click. A shape or form-control button with an assigned macro runs it on one
 *    left click (cell WorkbookView._onChangeSelectionDone, Controls.js
 *    CButtonController.runMacros -> baseEditorsApi.asc_runMacros). asc_runMacros
 *    checked only the admin "macros" switch and AscDesktopEditor.isSupportMacroses.
 *    The warning (web-apps onRunAutostartMacroses) is only raised for autostart
 *    macros, so a file without one never asks. The shape gets the pointer cursor
 *    and can be drawn as a blue underlined "https://..." - it reads as a link.
 * 2. Open. Custom functions saved in an .xlsx (jsaProject.bin "customFunctions",
 *    wb.fileCustomFunctions) were merged into the library and eval'd by
 *    registerCustomFunctionsLibrary when the WorkbookView was built - at open.
 *
 * Both were shown in a headless cell editor (Chromium, the built sdkjs, a stubbed
 * desktop host; .rd-work/wt/dg-tmp/h/probe.js with fixtures from dg-tmp/mkfix.py):
 * before the fix one click set B2 = "MACRO RAN" and RDPROBE was registered at open
 * with no event; after it the click raised asc_onMacrosRunRequest and ran only on
 * "yes", and the custom functions raised asc_onRunAutostartMacroses and were
 * registered only after asc_runAutostartMacroses.
 *
 * This test extracts by brace matching the REAL baseEditorsApi.asc_runMacros,
 * asc_runAutostartMacroses, hasDocumentAutorunCode / onDocumentMacrosAllowed (base
 * and cell), the content-ready statement that raises the warning, cell
 * registerCustomFunctionsLibrary and pluginMethod_GetCustomFunctions, Workbook.js
 * mergeCustomFunctions, and the spreadsheet editor's onMacrosRunRequest, and runs
 * them against stubs.
 *
 * Claimed: a document macro does not run on a click until the user allowed macros
 * for the document (no handler = no run; "No" is kept for the session; "Yes" or a
 * prior Yes/"Enable all" to the autostart warning runs it); file custom functions
 * are not eval'd at open, raise the warning, are registered after consent, and are
 * still written back on save; the user's own (localStorage) custom functions still
 * load at once; the editor's answer follows the macros setting (disable all, enable
 * all except Downloads/mail/temp, warn with No as default, admin switch off).
 * NOT claimed: the real Common.UI.warning rendering, the desktop GUI, or that the
 * macro "sandbox" contains a macro the user allowed (it does not - see #1664).
 *
 * RD_REPO=<sdkjs> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps).
 * BASELINE=1 reads both with git show at BASE_REF / WEBAPPS_BASE_REF; it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
const BASE_REF = process.env.BASE_REF || 'b6a9dee535^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || 'f8b289bf97^';

function read(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
/* `function (...) {...}` following marker, or null when the marker is absent (baseline). */
function fnAfter(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return null;
		throw new Error(marker + ' not found');
	}
	return matched(text, text.indexOf('function', at));
}
const compile = (src, ...names) => new Function(...names, '"use strict"; return (' + src + ');');

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}

/* ------------------------------ sdkjs ------------------------------ */
const apiBase = read(SDKJS, BASE_REF, 'common/apiBase.js');
const cellApi = read(SDKJS, BASE_REF, 'cell/api.js');
const cellPlugins = read(SDKJS, BASE_REF, 'cell/api_plugins.js');
const workbook = read(SDKJS, BASE_REF, 'cell/model/Workbook.js');

const readyAt = apiBase.indexOf('if (this.macros && !this.disableAutostartMacros');
assert.notStrictEqual(readyAt, -1, 'content-ready macros statement not found');
const readyStmt = apiBase.slice(readyAt, apiBase.indexOf(';', apiBase.indexOf('sendEvent', readyAt)) + 1);

const evals = [];
const AscCommon = {
	c_oEditorId: { Word: 0, Spreadsheet: 1, Presentation: 2 },
	safePluginEval: code => evals.push(code),
	getLocalStorageItem: k => (k in lsStore ? JSON.parse(lsStore[k]) : null),
	setLocalStorageItem: (k, v) => { lsStore[k] = JSON.stringify(v); },
};
const lsStore = {};
const safeJsonParse = s => { try { return typeof s === 'string' ? JSON.parse(s) : null; } catch (e) { return null; } };
const fakeWindow = { Asc: {}, localStorage: { getItem: k => (k in lsStore ? lsStore[k] : null) } };
const AscCommonExcel = { safeJsonParse };
AscCommonExcel.mergeCustomFunctions = compile(fnAfter(workbook, 'function mergeCustomFunctions('), 'window', 'safeJsonParse')(fakeWindow, safeJsonParse);
const names = ['window', 'AscCommon', 'AscCommonExcel'];
const args = [fakeWindow, AscCommon, AscCommonExcel];

const base = {};
for (const [k, m, opt] of [
	['asc_runMacros', 'baseEditorsApi.prototype.asc_runMacros = function'],
	['asc_runAutostartMacroses', 'baseEditorsApi.prototype.asc_runAutostartMacroses = function'],
	['hasDocumentAutorunCode', 'baseEditorsApi.prototype.hasDocumentAutorunCode = function', true],
	['onDocumentMacrosAllowed', 'baseEditorsApi.prototype.onDocumentMacrosAllowed = function', true],
]) {
	const src = fnAfter(apiBase, m, opt);
	if (src) base[k] = compile(src, ...names)(...args);
}
AscCommon.baseEditorsApi = { prototype: base };
const cell = Object.create(base);
for (const [k, m, opt] of [
	['hasFileCustomFunctions', 'spreadsheet_api.prototype.hasFileCustomFunctions = function', true],
	['hasDocumentAutorunCode', 'spreadsheet_api.prototype.hasDocumentAutorunCode = function', true],
	['onDocumentMacrosAllowed', 'spreadsheet_api.prototype.onDocumentMacrosAllowed = function', true],
]) {
	const src = fnAfter(cellApi, m, opt);
	if (src) cell[k] = compile(src, ...names)(...args);
}
cell.registerCustomFunctionsLibrary = compile(fnAfter(cellPlugins, 'Api.prototype.registerCustomFunctionsLibrary = function'),
	'window', 'AscCommon', 'AscCommonExcel', 'customFunctionsStorageId')(fakeWindow, AscCommon, AscCommonExcel, 'cell-custom-functions-library');
cell.getCustomFunctions = compile(fnAfter(cellPlugins, 'Api.prototype["pluginMethod_GetCustomFunctions"] = function'),
	'window', 'AscCommon', 'AscCommonExcel', 'customFunctionsStorageId')(fakeWindow, AscCommon, AscCommonExcel, 'cell-custom-functions-library');
const contentReady = new Function('"use strict";' + readyStmt);

const GUID = '{11111111-2222-3333-4444-555555555555}';
const FILE_CF = { macrosArray: [{ name: 'RDPROBE', value: 'FILE-CF-CODE' }] };
const USER_CF = { macrosArray: [{ name: 'MINE', value: 'USER-CF-CODE' }] };

function makeApi(opts = {}) {
	const api = Object.create(cell);
	const log = { runs: [], asks: 0, events: [], recalcs: 0 };
	let handler = opts.handler || null;
	Object.assign(api, {
		editorId: 1, DocInfo: null, disableAutostartMacros: false,
		macros: { run: g => log.runs.push(g), runAuto: () => log.runs.push('auto'), isExistAuto: () => !!opts.autostart },
		canRunBuilderScript: () => true, _beforeEvalCommand() {}, _afterEvalCommand() {}, onEndBuilderScript() {},
		handlers: { hasTrigger: n => n === 'asc_onMacrosRunRequest' && !!handler },
		asc_checkNeedCallback: n => n === 'asc_onMacrosRunRequest' && !!handler,
		sendEvent(n, cb) { log.events.push(n); if (n === 'asc_onMacrosRunRequest') { log.asks++; handler(cb); } },
		clearCustomFunctions() {}, recalculateCustomFunctions() { log.recalcs++; },
		wbModel: { fileCustomFunctions: opts.fileCF || null },
	});
	api.wb = { model: api.wbModel };
	fakeWindow.Asc.editor = api;
	fakeWindow.Asc['editor'] = api;
	for (const k in lsStore) delete lsStore[k];
	if (opts.userCF) lsStore['cell-custom-functions-library'] = JSON.stringify(opts.userCF);
	evals.length = 0;
	return { api, log };
}

check('click on a macro shape, no consent asked for: the macro does not run', () => {
	const { api, log } = makeApi();
	api.asc_runMacros(GUID);
	assert.deepStrictEqual(log.runs, [], 'macro ran without the user allowing macros');
});
check('click: the editor is asked; "no" does not run and is kept for the session', () => {
	const { api, log } = makeApi({ handler: cb => cb(false) });
	api.asc_runMacros(GUID);
	api.asc_runMacros(GUID);
	assert.deepStrictEqual(log.runs, []);
	assert.strictEqual(log.asks, 1, 'asked again after "no"');
});
check('click: "yes" runs it, and later clicks run without asking again', () => {
	const { api, log } = makeApi({ handler: cb => cb(true) });
	api.asc_runMacros(GUID);
	api.asc_runMacros(GUID);
	assert.deepStrictEqual(log.runs, [GUID, GUID]);
	assert.strictEqual(log.asks, 1);
});
check('click after "Yes" (or Enable all) to the autostart warning runs without asking', () => {
	const { api, log } = makeApi({ autostart: true, handler: () => { throw new Error('asked'); } });
	api.asc_runAutostartMacroses();
	api.asc_runMacros(GUID);
	assert.deepStrictEqual(log.runs, ['auto', GUID]);
});
check('open: custom functions saved in the file are not eval\'d before consent; the user\'s own still are', () => {
	const { api } = makeApi({ fileCF: FILE_CF, userCF: USER_CF });
	api.registerCustomFunctionsLibrary(undefined, true);
	assert.ok(!evals.includes('FILE-CF-CODE'), 'file custom function code ran at open');
	assert.ok(evals.includes('USER-CF-CODE'), 'the user\'s localStorage functions no longer load');
});
check('open: file custom functions alone raise the macros warning', () => {
	const { api, log } = makeApi({ fileCF: FILE_CF });
	contentReady.call(api);
	assert.deepStrictEqual(log.events, ['asc_onRunAutostartMacroses']);
	const plain = makeApi();
	contentReady.call(plain.api);
	assert.deepStrictEqual(plain.log.events, [], 'a file with no code must not warn');
});
check('consent: file custom functions are registered and recalculated', () => {
	const { api, log } = makeApi({ fileCF: FILE_CF });
	api.registerCustomFunctionsLibrary(undefined, true);
	api.asc_runAutostartMacroses();
	assert.ok(evals.includes('FILE-CF-CODE'), 'not registered after consent');
	assert.ok(log.recalcs >= 1);
	const viaClick = makeApi({ fileCF: FILE_CF, handler: cb => cb(true) });
	viaClick.api.asc_runMacros(GUID);
	assert.ok(evals.includes('FILE-CF-CODE'), '"yes" on a click does not register them');
});
check('save: file custom functions still go back into the file without consent', () => {
	const { api } = makeApi({ fileCF: FILE_CF });
	api.registerCustomFunctionsLibrary(undefined, true);
	assert.ok(/RDPROBE/.test(api.getCustomFunctions()), 'lost from what the writer saves');
});

/* ------------------------------ web-apps ------------------------------ */
const mainSrc = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/app/controller/Main.js');
const handlerSrc = fnAfter(mainSrc, 'onMacrosRunRequest: function', true);
function ask(mode, srcPath, opts = {}) {
	const settings = { 'sse-macros-mode': mode }, stored = {};
	const out = { answers: [], dialog: null, stored };
	const Common = {
		Utils: { InternalSettings: { get: k => settings[k], set: (k, v) => { settings[k] = v; } } },
		localStorage: { setItem: (k, v) => { stored[k] = v; } },
		UI: { warning: o => { out.dialog = o; } },
		Controllers: { Desktop: { isLocalFileFromUntrustedPlace: () => /Downloads|Mail Downloads|\/T\//.test(srcPath) } },
	};
	const ctx = { editorConfig: opts.editorConfig || {}, textMacroOnClick: 'CLICK', textMacrosTrust: 'TRUST', textRemember: 'R' };
	compile(handlerSrc, 'Common')(Common).call(ctx, a => out.answers.push(a));
	return out;
}
check('editor: asc_onMacrosRunRequest is handled', () => {
	assert.ok(handlerSrc, 'no onMacrosRunRequest in the spreadsheet editor');
	assert.ok(/asc_registerCallback\('asc_onMacrosRunRequest'/.test(mainSrc), 'not registered');
});
check('editor: answers follow the macros setting', () => {
	assert.ok(handlerSrc, 'no handler');
	assert.deepStrictEqual(ask(2, '/Users/u/Documents/a.xlsx').answers, [false], 'disable all');
	assert.deepStrictEqual(ask(1, '/Users/u/Documents/a.xlsx').answers, [true], 'enable all');
	assert.deepStrictEqual(ask(1, '/Users/u/Documents/a.xlsx', { editorConfig: { customization: { macros: false } } }).answers, [false], 'admin off');
	const dl = ask(1, '/Users/u/Downloads/a.xlsx');
	assert.ok(dl.dialog && dl.answers.length === 0, 'enable all must still ask for a downloaded file');
	const w = ask(0, '/Users/u/Documents/a.xlsx');
	assert.strictEqual(w.dialog.primary, 'no', 'default button');
	assert.deepStrictEqual(w.dialog.buttons, ['no', 'yes']);
	assert.ok(w.dialog.msg.includes('TRUST'));
	w.dialog.callback('no', false);
	assert.deepStrictEqual(w.answers, [false]);
	const y = ask(0, '/Users/u/Documents/a.xlsx');
	y.dialog.callback('yes', true);
	assert.deepStrictEqual(y.answers, [true]);
	assert.strictEqual(y.stored['sse-macros-mode'], 1, 'remember my choice');
	const en = JSON.parse(read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/locale/en.json'));
	assert.ok(en['SSE.Controllers.Main.textMacroOnClick'], 'textMacroOnClick missing in en.json');
});

console.log(failures ? `${failures} FAILED` : 'all passed');
process.exit(failures ? 1 : 0);
