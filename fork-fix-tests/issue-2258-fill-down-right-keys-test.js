/*
 * #2258 - Ctrl+D / Ctrl+R to fill down / right in spreadsheets (Excel's keys).
 *
 * What there was: in the cell grid both keys did nothing. Ctrl+D has no shortcut in
 * sdkjs (web-apps only swallows it); Ctrl+R is the RightPara shortcut (the table
 * also lists PasteOnlyFormatting on Ctrl+R, but one key holds one action and
 * RightPara, added later, is the one in the map). RightPara right-aligns text in a
 * shape or chart - the drawing controller gets every key first - and when no
 * drawing takes it, cell/view/EventsController.js executeShortcut had no case for
 * it, so nothing happened. Fill Down/Right existed only in the toolbar's Fill menu
 * (asc_FillCells(c_oAscFillType.fillDown/fillRight)).
 * What now (an option, off by default - today's behaviour): File > Advanced
 * settings "Ctrl+D and Ctrl+R fill down and right in the cell grid" (⌘ on macOS),
 * stored as sse-settings-fill-shortcuts and handed to sdkjs as
 * asc_setFillShortcuts. The rule, with the option on:
 *   - Ctrl+R (Cmd+R): text in a selected shape/chart still gets it first and is
 *     right-aligned, as before; otherwise, in the grid with the cell editor
 *     closed and the sheet editable, it fills right (EventsController
 *     executeShortcut, case RightPara);
 *   - Ctrl+D (Cmd+D), no Shift/Alt: same place and conditions, fills down
 *     (_onWindowKeyDown's key switch, reached only when no action owns the key, so
 *     a user shortcut on Ctrl+D still wins).
 *
 * This test runs the REAL code, extracted by brace matching: asc_setFillShortcuts /
 * asc_getFillShortcuts (cell/api.js), EventsController.executeShortcut, the
 * `case 68` of _onWindowKeyDown's key switch, and WorkbookView.executeShortcut (the
 * drawing-first routing), against stubs that record asc_FillCells. Scenarios: option
 * off (nothing, as before), option on in the grid, Shift/Alt, cell editor open, view
 * only, a selected shape with text, macOS Cmd vs Ctrl. It also checks the web-apps
 * wiring (checkbox, saved key, Main/LeftMenu handing it to the api) by reading
 * RD_WEBAPPS.
 * BASELINE=1 reads sdkjs from BASE_REF: no option and RightPara/Ctrl+D do nothing
 * in the grid -> FAILS.
 *
 * NOT claimed: what Fill Down/Right does to the cells (that is the existing Fill
 * menu path); the settings checkbox's look; that CEF/the macOS menu do not take
 * Cmd+D/Cmd+R before the editor - needs a GUI check.
 *
 * Env: RD_REPO sdkjs checkout (default ../sdkjs), RD_WEBAPPS web-apps checkout
 *      (default ../web-apps), BASELINE=1 with BASE_REF / WEBAPPS_BASE_REF.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '343dd2ce50^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || 'd4d05aaed8^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
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
function fn(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return null;
		throw new Error(marker + ' not found');
	}
	return block(text, at);
}

const api = src(SDKJS, BASE_REF, 'cell/api.js');
const ec = src(SDKJS, BASE_REF, 'cell/view/EventsController.js');
const wbv = src(SDKJS, BASE_REF, 'cell/view/WorkbookView.js');

const setSrc = fn(api, 'spreadsheet_api.prototype.asc_setFillShortcuts = function', true);
const getSrc = fn(api, 'spreadsheet_api.prototype.asc_getFillShortcuts = function', true);
const execSrc = fn(ec, 'asc_CEventsController.prototype.executeShortcut = function');
const keyDown = fn(ec, 'asc_CEventsController.prototype._onWindowKeyDown = function');
const sw = keyDown.indexOf('switch (oEvent.GetKeyCode()) {');
const c68 = keyDown.indexOf('case 68:', sw);
const c82 = keyDown.indexOf('case 82:', sw);
const case68 = (c68 !== -1 && c68 < c82) ? keyDown.slice(c68, c82) : '';
const wbExec = fn(wbv, 'WorkbookView.prototype.executeShortcut = function');

const T = { RightPara: 168, Bold: 1 };
const Asc = {
	c_oAscSpreadsheetShortcutType: new Proxy(T, { get: (o, k) => (k in o ? o[k] : -1000 - String(k).length) }),
	c_oAscFillType: { fillDown: 12, fillRight: 14 },
	c_oAscCalculateType: {}, c_oAscNumFormatType: {},
};
const AscCommon = { c_oAscCustomShortcutType: { Symbol: 1 } };
const AscCommonExcel = {};
const keydownresult_PreventAll = 0x0101, keydownresult_PreventNothing = 0;

function Api() { this.fills = []; }
Api.prototype.asc_FillCells = function (t) { this.fills.push(t === 12 ? 'fillDown' : t === 14 ? 'fillRight' : t); };
Api.prototype.getCustomShortcutAction = function () { return null; };
if (setSrc) new Function('spreadsheet_api', setSrc + ';' + getSrc + ';')(Api);
else Api.prototype.asc_getFillShortcuts = function () { return false; }; // baseline: the api has no such option

function Controller(api, state) {
	this.view = { Api: api, setFontAttributes() {} };
	this.handlers = { trigger() {} };
	this.state = state;
}
Controller.prototype.getSelectionDialogMode = function () { return false; };
Controller.prototype.canEdit = function () { return this.state.canEdit; };
Controller.prototype.getCellEditMode = function () { return this.state.cellEdit; };
new Function('asc_CEventsController', 'Asc', 'AscCommon', 'AscCommonExcel', 'keydownresult_PreventAll',
	execSrc + ';')(Controller, Asc, AscCommon, AscCommonExcel, keydownresult_PreventAll);

// the real `case 68:` inside a switch like _onWindowKeyDown's
const key68 = new Function('oThis', 'oEvent', 'bIsSelect', 'bIsMacOs', 'bCanEdit', 'bSelectionDialogMode', 'keydownresult_PreventAll', 'Asc',
	`let nRetValue = 0;\nswitch (oEvent.GetKeyCode()) {\n${case68}\ncase 82: break;\n}\nreturn nRetValue;`);

function keyEvent(o) {
	return { GetKeyCode: () => 68, IsAlt: () => !!o.alt, IsCmd: () => !!o.cmd, IsShortcutCtrl: () => !!o.ctrl && !o.cmd };
}
function scenario(o) {
	const api = new Api();
	if (api.asc_setFillShortcuts) api.asc_setFillShortcuts(o.option);
	const c = new Controller(api, { canEdit: o.canEdit !== false, cellEdit: !!o.cellEdit });
	let ret;
	if (o.key === 'R') {
		if (o.shape) {
			// WorkbookView.executeShortcut: a selected shape with text takes RightPara first
			const wb = { getWorksheet: () => ({ objectRender: { getSelectedGraphicObjects: () => [1],
				controller: { executeShortcut: (n) => (n === T.RightPara ? (api.rightAligned = true) : false) } } }),
				getCellEditMode: () => false, controller: Object.assign(c, { isMousePressed: false, setSkipCellEditor() {} }),
				enableKeyEvents: true, isCellEditMode: false };
			ret = new Function('n', wbExec.replace(/^WorkbookView\.prototype\.executeShortcut = function\(nShortcutAction\)/, 'return (function(nShortcutAction)') + ').call(this, n);').call(wb, T.RightPara);
		} else {
			ret = c.executeShortcut(T.RightPara);
		}
	} else {
		ret = key68.call(c, c, keyEvent(o), !!o.shift, !!o.mac, o.canEdit !== false, false, keydownresult_PreventAll, Asc);
	}
	return api.rightAligned ? 'right-aligned the text' : (api.fills.join(',') || 'nothing');
}

const cases = [
	['option off: Ctrl+R in the grid', { option: false, key: 'R' }, 'nothing'],
	['option off: Ctrl+D in the grid', { option: false, key: 'D', ctrl: true }, 'nothing'],
	['option on:  Ctrl+R in the grid', { option: true, key: 'R' }, 'fillRight'],
	['option on:  Ctrl+D in the grid', { option: true, key: 'D', ctrl: true }, 'fillDown'],
	['option on:  Ctrl+Shift+D', { option: true, key: 'D', ctrl: true, shift: true }, 'nothing'],
	['option on:  Ctrl+Alt+D', { option: true, key: 'D', ctrl: true, alt: true }, 'nothing'],
	['option on:  Ctrl+R, cell editor open', { option: true, key: 'R', cellEdit: true }, 'nothing'],
	['option on:  Ctrl+D, cell editor open', { option: true, key: 'D', ctrl: true, cellEdit: true }, 'nothing'],
	['option on:  Ctrl+D, view only', { option: true, key: 'D', ctrl: true, canEdit: false }, 'nothing'],
	['option on:  Ctrl+R, shape with text selected', { option: true, key: 'R', shape: true }, 'right-aligned the text'],
	['option on:  macOS Cmd+D', { option: true, key: 'D', cmd: true, ctrl: true, mac: true }, 'fillDown'],
	['option on:  macOS Ctrl+D (no Cmd)', { option: true, key: 'D', ctrl: true, mac: true }, 'nothing'],
];
let failures = 0;
console.log('#2258 fill down / right keys:');
for (const [what, o, want] of cases) {
	const got = scenario(o);
	const ok = got === want;
	failures += !ok;
	console.log(`  ${what.padEnd(46)} -> ${got.padEnd(24)} ${ok ? 'ok' : 'FAILED, want ' + want}`);
}

/* web-apps wiring: the checkbox, its saved key, handed to the api at load and on Apply */
const panels = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/app/view/FileMenuPanels.js');
const main = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/app/controller/Main.js');
const left = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/app/controller/LeftMenu.js');
const en = JSON.parse(src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/locale/en.json'));
const wiring = [
	['checkbox in Advanced settings', /fms-chb-fill-shortcuts/.test(panels) && /chFillShortcuts = new Common\.UI\.CheckBox/.test(panels)],
	['saved as sse-settings-fill-shortcuts', /setItem\("sse-settings-fill-shortcuts", this\.chFillShortcuts\.isChecked\(\)/.test(panels)],
	['applied at load (off unless set)', /getBool\("sse-settings-fill-shortcuts"\);[\s\S]{0,200}asc_setFillShortcuts\(value\)/.test(main)],
	['applied on Apply', /getBool\("sse-settings-fill-shortcuts"\);[\s\S]{0,200}asc_setFillShortcuts\(value\)/.test(left)],
	['English label', !!en['SSE.Views.FileMenuPanels.MainSettingsGeneral.strFillShortcuts']],
];
for (const [what, ok] of wiring) {
	failures += !ok;
	console.log(`  web-apps: ${what.padEnd(40)} ${ok ? 'ok' : 'FAILED'}`);
}
if (failures) {
	console.log('FAIL');
	process.exit(1);
}
console.log('PASS #2258: with the option on, Ctrl+D/Ctrl+R fill down/right in the grid; off by default; shape text keeps Ctrl+R');
