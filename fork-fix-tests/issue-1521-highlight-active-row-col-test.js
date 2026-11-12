/*
 * #1521 - "Column/Row Highlighting" (as in LibreOffice 24.2): tint the active cell's row and
 * column across the sheet, so a row of a wide table is easy to follow. kappe-c asked in the
 * thread for row-only and column-only too. Nothing like it existed (only the row/column
 * headers of the selection are highlighted). Now possible, off by default:
 * File > Advanced settings > Workspace > "Highlight active row/column":
 * None (default) / Row and column / Row only / Column only.
 *
 * sdkjs: Asc.c_oAscActiveCellHighlight (cell/apiDefines.js, a bit mask Row=1, Column=2);
 * api.asc_setActiveCellHighlight / asc_getActiveCellHighlight (cell/api.js) store the mode
 * and redraw the selection; WorksheetView._drawActiveCellHighlight (cell/view/
 * WorksheetView.js) fills the bands on the selection overlay with _drawSelectionElement
 * (fill only, no border; frozen panes handled by _drawElements), called from _drawSelection
 * before the selection itself; cleanSelection clears the whole overlay while a tint is on
 * (as it does for print lines / cut range), since the bands span the sheet.
 * web-apps: the combo in FileMenuPanels (sse-settings-highlight-rowcol in localStorage),
 * applied on load (Main.js) and on Apply (LeftMenu.applySettings).
 *
 * This extracts the REAL constants, asc_setActiveCellHighlight, _drawActiveCellHighlight and
 * _getActiveCellHighlight and runs them with a stub view that records the ranges drawn;
 * checks in the REAL _drawSelection / cleanSelection bodies that the tint is drawn before
 * the selection and forces the full overlay clear; and checks the web-apps wiring.
 *
 * NOT claimed: how it looks (colour: amber at the selection fill's 15% alpha; GUI check:
 * turn it on, move with arrows/mouse, scroll, freeze panes, select a shape, dark theme).
 *
 *   RD_REPO=<sdkjs> RD_WEBAPPS=<web-apps> (defaults ../sdkjs, ../web-apps)
 *   BASELINE=1 reads both from their BASE_REFs -> must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parents of the commits that landed this feature, never HEAD.
const BASE_REF = process.env.BASE_REF || 'b749c681ab^';
const BASE_REF_WEBAPPS = process.env.BASE_REF_WEBAPPS || '92fcc5c556^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
function matched(text, from, open) {
	const close = { '{': '}', '[': ']' }[open];
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
	if (at === -1) return null;
	const p = text.indexOf('(', at + marker.length - 10);
	return 'function' + text.slice(p, text.indexOf(')', p) + 1) + matched(text, p, '{');
}

let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(48)} ${JSON.stringify(got).slice(0, 60).padEnd(60)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}

console.log('sdkjs ' + (process.env.BASELINE ? '@ ' + BASE_REF : SDKJS));
const defines = src(SDKJS, BASE_REF, 'cell/apiDefines.js');
const at = defines.indexOf('var c_oAscActiveCellHighlight =');
const H = at === -1 ? null : new Function('return ' + matched(defines, at, '{'))();
check('Asc.c_oAscActiveCellHighlight', H, { None: 0, Row: 1, Column: 2, RowAndColumn: 3 });
if (!H) {
	console.log('\nFAILED - no active row/column highlight in this sdkjs');
	process.exit(1);
}

const wsJs = src(SDKJS, BASE_REF, 'cell/view/WorksheetView.js');
function Range(c1, r1, c2, r2) { Object.assign(this, { c1, r1, c2, r2 }); }
function CColor(r, g, b) { Object.assign(this, { r, g, b }); }
const AscCommonExcel = { selectionLineType: { Selection: 1, NotStroke: 64 } };
const mk = (marker) => new Function('c_oAscActiveCellHighlight', 'asc_Range', 'CColor', 'AscCommonExcel', 'return ' + fnAt(wsJs, marker))(H, Range, CColor, AscCommonExcel);
const drawHighlight = mk('WorksheetView.prototype._drawActiveCellHighlight = function');
const getHighlight = mk('WorksheetView.prototype._getActiveCellHighlight = function');

function view(mode, row, col) {
	const v = {
		nColsCount: 30, nRowsCount: 100, drawn: [],
		workbook: { Api: { activeCellHighlight: mode } },
		model: { getSelection: () => ({ activeCell: { row, col } }) },
		_drawSelectionElement() {},
		_drawElements(f, range, type, color) {
			assert.strictEqual(f, this._drawSelectionElement);
			assert.strictEqual(type, 1 | 64, 'fill only, no border');
			this.drawn.push([range.c1, range.r1, range.c2, range.r2]);
		},
		_getActiveCellHighlight: getHighlight,
	};
	drawHighlight.call(v);
	return v.drawn;
}
check('None: nothing drawn', view(H.None, 5, 3), []);
check('Row only: row 5 across', view(H.Row, 5, 3), [[0, 5, 29, 5]]);
check('Column only: column 3 down', view(H.Column, 5, 3), [[3, 0, 3, 99]]);
check('Row and column: row + column without the crossing', view(H.RowAndColumn, 5, 3), [[0, 5, 29, 5], [3, 0, 3, 4], [3, 6, 3, 99]]);
check('Row and column at A1', view(H.RowAndColumn, 0, 0), [[0, 0, 29, 0], [0, 1, 0, 99]]);
check('no Api yet -> None', getHighlight.call({ workbook: {} }), H.None);

const apiJs = src(SDKJS, BASE_REF, 'cell/api.js');
const setHighlight = new Function('Asc', 'return ' + fnAt(apiJs, 'spreadsheet_api.prototype.asc_setActiveCellHighlight = function'))({ c_oAscActiveCellHighlight: H });
const calls = [];
const api = { activeCellHighlight: H.None, wb: { getWorksheet: () => ({
	cleanSelection: () => calls.push('clean@' + api.activeCellHighlight),
	_drawSelection: () => calls.push('draw@' + api.activeCellHighlight) }) } };
setHighlight.call(api, H.Row);
setHighlight.call(api, H.Row);
setHighlight.call(api, H.None);
check('asc_setActiveCellHighlight: clean old, draw new', calls, ['clean@0', 'draw@1', 'clean@1', 'draw@0']);
check('asc_setActiveCellHighlight exported', /prot\["asc_setActiveCellHighlight"\]/.test(apiJs), true);

const drawSel = fnAt(wsJs, 'WorksheetView.prototype._drawSelection = function');
const iH = drawSel.indexOf('this._drawActiveCellHighlight()'), iS = drawSel.indexOf('this._drawSelectionRange()');
check('_drawSelection: tint drawn, before the selection', iH !== -1 && iH < iS, true);
const clean = fnAt(wsJs, 'WorksheetView.prototype.cleanSelection = function');
check('cleanSelection: full clear while a tint is on', /this\.getDynamicArrayFirstCell\(\)\s*\|\|\s*this\._getActiveCellHighlight\(\)\)\s*\{\s*this\.overlayCtx\.clear\(\)/.test(clean), true);

/* web-apps wiring */
const wa = (rel) => src(WEBAPPS, BASE_REF_WEBAPPS, rel);
const panels = wa('apps/spreadsheeteditor/main/app/view/FileMenuPanels.js');
const cAt = panels.indexOf('this.cmbHighlightRowCol = new Common.UI.ComboBox(');
const combo = cAt === -1 ? [] : new Function('Asc', 'return ' + matched(panels, panels.indexOf('data', cAt), '[')).call({}, { c_oAscActiveCellHighlight: H });
check('web-apps combo values', combo.map((d) => d.value), [H.None, H.RowAndColumn, H.Row, H.Column]);
check('web-apps template has the combo', panels.includes("id=\"fms-cmb-highlight-rowcol\""), true);
check('web-apps Apply saves the setting', panels.includes('Common.localStorage.setItem("sse-settings-highlight-rowcol", this.cmbHighlightRowCol.getValue())'), true);
for (const rel of ['apps/spreadsheeteditor/main/app/controller/Main.js', 'apps/spreadsheeteditor/main/app/controller/LeftMenu.js'])
	check(path.basename(rel) + ' applies the stored setting', /getItem\("sse-settings-highlight-rowcol"\)[\s\S]{0,200}asc_setActiveCellHighlight\(value\)/.test(wa(rel)), true);

console.log(failures ? '\nFAILED' : '\nok - the active row/column can be highlighted (off by default)');
process.exit(failures ? 1 : 0);
