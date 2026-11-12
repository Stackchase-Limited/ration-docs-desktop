/*
 * #247 - "Missing keyboard key to edit a filled Cell in Spreadsheets": there was no way to
 * edit a filled cell in place from the keyboard.
 *
 * On Windows/Linux 9.4 already has it: F2 (EditOpenCellEditor, cell/model/Shortcuts.js)
 * opens the cell editor on the active cell with the caret after its text, as in Excel;
 * the upstream thread confirms that. On macOS F2 is the same key, but on Mac keyboards
 * the top row sends brightness/media keys unless fn is held (or the system option "Use F1,
 * F2, etc. keys as standard function keys" is on), so Mac users effectively had no key.
 * Excel for Mac binds "edit the active cell" to Control+U; in our Mac defaults Control+U
 * was only a duplicate of Underline next to Cmd+U. Now on macOS Control+U opens the cell
 * editor and Cmd+U underlines; F2 (fn+F2) still works; nothing changes off macOS.
 *
 * What runs: the real Shortcuts.js default table (evaluated with isMacOs true and false),
 * the real CAscShortcut (apiCommon.js), CShortcuts (editorscommon.js), c_oAscKeyCodes /
 * c_oAscKeyCodeAnalogues (commonDefines.js), c_oAscSpreadsheetShortcutType (apiDefines.js),
 * baseEditorsApi initDefaultShortcuts/getShortcut (apiBase.js), CKeyboardEvent and
 * check_KeyboardEvent (WorkEvents.js) turning a DOM-like keydown into the lookup, and the
 * EditOpenCellEditor case of asc_CEventsController._onWindowKeyDown (EventsController.js)
 * against a recording stub.
 *
 * NOT claimed: real key delivery in the CEF window (needs a GUI check on a Mac: select a
 * filled cell, press Control+U, the caret should sit after the text), the Keyboard
 * Shortcuts dialog listing (it reads the same table), users' customised shortcuts.
 *
 *   RD_REPO=<sdkjs tree> node issue-0247-mac-edit-cell-key-test.js   (default ../sdkjs)
 *   BASELINE=1 ...   reads the sources at BASE_REF (parent of the fix) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
// Pinned to the parent of the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '4acf06a079^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function blockFrom(text, open) {
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}
/* `marker` through the end of the first {...} after it */
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	assert.strictEqual(text.indexOf(marker, at + 1), -1, marker + ' is not unique');
	const open = text.indexOf('{', at);
	return text.slice(at, open) + blockFrom(text, open);
}
/* the statements from `from` up to (not including) `to` */
function between(text, from, to) {
	const a = text.indexOf(from), b = text.indexOf(to, a);
	assert(a !== -1 && b !== -1, from + ' .. ' + to + ' not found');
	return text.slice(a, b);
}

const common = src('common/commonDefines.js');
const apiCommon = src('common/apiCommon.js');
const editorsCommon = src('common/editorscommon.js');
const apiBase = src('common/apiBase.js');
const apiDefines = src('cell/apiDefines.js');
const shortcutsJs = src('cell/model/Shortcuts.js');
const workEvents = src('common/Drawings/WorkEvents.js');
const eventsCtl = src('cell/view/EventsController.js');

function buildAsc() {
	const Asc = {};
	Asc.c_oAscKeyCodes = new Function(extract(common, 'const c_oAscKeyCodes = ') + ';\nreturn c_oAscKeyCodes;')();
	Asc.c_oAscKeyCodeAnalogues = new Function('c_oAscKeyCodes',
		between(common, 'const c_oAscKeyCodeEquals = ', 'const c_oAscExternalReferenceType') + ';\nreturn c_oAscKeyCodeAnalogues;')(Asc.c_oAscKeyCodes);
	Asc.c_oAscSpreadsheetShortcutType = new Function(extract(apiDefines, 'const c_oAscSpreadsheetShortcutType = ') + ';\nreturn c_oAscSpreadsheetShortcutType;')();
	Asc.CAscShortcut = new Function(extract(apiCommon, 'function CAscShortcut(') + '\nreturn CAscShortcut;')();
	return Asc;
}

function CShortcutsFactory(Asc) {
	const body = extract(editorsCommon, 'function CShortcuts()') + '\n' +
		between(editorsCommon, 'CShortcuts.GetShortcutIndex = function', 'function CCustomShortcutActionSymbol(') +
		'\nreturn CShortcuts;';
	return new Function('Asc', 'CCustomShortcutActionSymbol', 'AscCommon', body)(Asc, function () {}, { c_oAscCustomShortcutType: {} });
}

function makeApi(isMac) {
	const Asc = buildAsc();
	const AscCommon = { AscBrowser: { isMacOs: isMac } };
	const window = { Asc, AscCommon };
	window['Asc'] = Asc;
	// Shortcuts.js is an IIFE over window/Asc/AscCommon
	new Function('window', 'Asc', 'AscCommon', 'AscCommonExcel', shortcutsJs)(window, Asc, AscCommon, {});
	assert(Asc.c_oAscDefaultShortcuts, 'Shortcuts.js did not export c_oAscDefaultShortcuts');

	const CShortcuts = CShortcutsFactory(Asc);
	function baseEditorsApi() { this.Shortcuts = new CShortcuts(); }
	new Function('baseEditorsApi', 'Asc',
		extract(apiBase, 'baseEditorsApi.prototype.initDefaultShortcuts = function') + ';\n' +
		extract(apiBase, 'baseEditorsApi.prototype.getShortcut = function') + ';')(baseEditorsApi, Asc);
	const api = new baseEditorsApi();
	api.initDefaultShortcuts();

	// the real keydown -> CKeyboardEvent conversion
	const ke = new Function('AscCommon',
		extract(workEvents, 'function CKeyboardEvent()') + '\n' +
		between(workEvents, 'CKeyboardEvent.prototype.Up = function', 'CKeyboardEvent.prototype.GetKeyCode') +
		extract(workEvents, 'CKeyboardEvent.prototype.GetKeyCode = function') + ';\n' +
		'var global_keyboardEvent = new CKeyboardEvent();\n' +
		extract(workEvents, 'function check_KeyboardEvent(e)') + '\n' +
		'return function (e) { check_KeyboardEvent(e); return global_keyboardEvent; };')(
		Object.assign({ getAltGr: () => false }, AscCommon));
	return { Asc, action: (e) => api.getShortcut(ke(Object.assign({ altKey: false, shiftKey: false, ctrlKey: false, metaKey: false }, e))) };
}

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

const mac = makeApi(true), pc = makeApi(false);
const T = mac.Asc.c_oAscSpreadsheetShortcutType, K = mac.Asc.c_oAscKeyCodes;
const nameOf = (v) => Object.keys(T).find((k) => T[k] === v) || String(v);

check('macOS: Control+U opens the cell editor (Excel for Mac)', () =>
	assert.strictEqual(nameOf(mac.action({ keyCode: K.KeyU, ctrlKey: true })), 'EditOpenCellEditor'));
check('macOS: Cmd+U still underlines', () =>
	assert.strictEqual(nameOf(mac.action({ keyCode: K.KeyU, metaKey: true })), 'Underline'));
check('macOS: F2 (fn+F2) still opens the cell editor', () =>
	assert.strictEqual(nameOf(mac.action({ keyCode: K.F2 })), 'EditOpenCellEditor'));
check('Windows/Linux: F2 opens the cell editor', () =>
	assert.strictEqual(nameOf(pc.action({ keyCode: K.F2 })), 'EditOpenCellEditor'));
check('Windows/Linux: Ctrl+U still underlines', () =>
	assert.strictEqual(nameOf(pc.action({ keyCode: K.KeyU, ctrlKey: true })), 'Underline'));

/* the action itself: the real EditOpenCellEditor case of _onWindowKeyDown */
check('EditOpenCellEditor opens the editor on the active cell with focus', () => {
	const kase = extract(eventsCtl, 'case Asc.c_oAscSpreadsheetShortcutType.EditOpenCellEditor: {');
	const calls = [];
	const self = {
		getCellEditMode: () => false,
		handlers: { trigger: (...a) => calls.push(a) },
	};
	function CEditorEnterOptions() { this.focus = null; }
	const oRet = { keyResult: 0 };
	new Function('Asc', 'AscBrowser', 'AscCommonExcel', 'bCanEdit', 'bSelectionDialogMode', 'oRet', 'keydownresult_PreventNothing',
		'switch (Asc.c_oAscSpreadsheetShortcutType.EditOpenCellEditor) {' + kase + '}')
		.call(self, mac.Asc, { isOpera: false }, { CEditorEnterOptions }, true, false, oRet, 7);
	assert.strictEqual(calls.length, 1);
	assert.strictEqual(calls[0][0], 'editCell');
	assert.strictEqual(calls[0][1].focus, true);
});

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
