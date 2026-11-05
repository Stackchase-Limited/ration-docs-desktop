/*
 * #2459 (found while working on it) - asc_changeFormatTableInfo(name, rowTotal,
 * true) on a table that already has a totals row changed the table: it inserted
 * another row, grew the table (A1:C5 -> A1:C6) and set TotalsRowCount to null,
 * so the old totals row became a data row. rowHeader false on a table without a
 * header row cleared its first data row, turned the header back on and shrank
 * the table (A2:C7 -> A3:C7). The UI checkboxes send only real changes; the
 * API, macros and plugins can send the current state.
 *
 * Cause: AutoFilters.changeFormatTableInfo (cell/model/autofilters.js) only
 * toggles TotalsRowCount / HeaderRowCount and never compares them with the
 * requested value, and WorksheetView.af_changeFormatTableInfo
 * (cell/view/WorksheetView.js) passed every request on.
 *
 * This extracts by brace matching the real WorksheetView.af_changeFormatTableInfo
 * and TablePart isTotalsRow / isHeaderRow and checks that a boolean
 * rowTotal/rowHeader request equal to the table's state stops before the
 * change starts (af_checkChangeTableInfo, the first step towards locks, history
 * and the model change, is not called), while real changes and value-less
 * toggles still go on.
 * Stubbed: af_checkChangeTableInfo (a spy returning false so nothing further
 * runs), the model's table lookup, filteringMode.
 * NOT claimed here: the model change itself (verified in a headless editor
 * with the real desktop save, see the commit message).
 *
 * RD_REPO overrides the sdkjs checkout; BASELINE=1 reads the sources from
 * BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit (re-pinned by the integrator after
// cherry-picking). Never HEAD: once the fix lands HEAD carries it.
const BASE_REF = process.env.BASE_REF || 'c5160011f4^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match forward from the first '{' at or after `from`. */
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
/* `marker` ends with "function"; returns "(args) { body }" */
function fn(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return matched(text, at + marker.length);
}
const make = (src, scope) => {
	const names = Object.keys(scope || {});
	return new Function(...names, '"use strict"; return function' + src)(...names.map(n => scope[n]));
};

const view = read('cell/view/WorksheetView.js');
const elems = read('cell/model/WorkbookElems.js');

/* the module's own copy of Asc.c_oAscChangeTableStyleInfo (cell/apiDefines.js) */
const apiDefines = read('cell/apiDefines.js');
const c_oAscChangeTableStyleInfo = new Function('return ' + matched(apiDefines, apiDefines.indexOf('var c_oAscChangeTableStyleInfo = ') + 'var c_oAscChangeTableStyleInfo = '.length))();
const scope = { window: { AscCommonExcel: { filteringMode: true } }, c_oAscChangeTableStyleInfo, Asc: { c_oAscChangeTableStyleInfo } };
const afChangeFormatTableInfo = make(fn(view, 'WorksheetView.prototype.af_changeFormatTableInfo = function'), scope);
const isTotalsRow = make(fn(elems, 'TablePart.prototype.isTotalsRow = function'));
const isHeaderRow = make(fn(elems, 'TablePart.prototype.isHeaderRow = function'));

/* does the request get past the early checks? */
function goesOn(table, optionType, val) {
	let checked = 0;
	const tablePart = Object.assign({ TableStyleInfo: {}, isTotalsRow, isHeaderRow }, table);
	const wsView = {
		model: { autoFilters: { _getFilterByDisplayName: () => tablePart }, selectionRange: { getLast: () => ({}) } },
		af_checkChangeTableInfo() { checked++; return false; },
	};
	afChangeFormatTableInfo.call(wsView, 'Table1', optionType, val);
	return checked === 1;
}
const T = c_oAscChangeTableStyleInfo;
const withTotals = { TotalsRowCount: 1, HeaderRowCount: null }, noTotals = { TotalsRowCount: null, HeaderRowCount: null };
const noHeader = { TotalsRowCount: null, HeaderRowCount: 0 };

assert.strictEqual(goesOn(withTotals, T.rowTotal, true), false, 'totals row on, on a table with a totals row, must not change the table');
assert.strictEqual(goesOn(noTotals, T.rowTotal, false), false, 'totals row off, on a table without one, must not change the table');
assert.strictEqual(goesOn(withTotals, T.rowHeader, true), false, 'header row on, on a table with a header row, must not change the table');
assert.strictEqual(goesOn(noHeader, T.rowHeader, false), false, 'header row off, on a table without one, must not change the table');
/* real changes and toggles go on */
assert.strictEqual(goesOn(withTotals, T.rowTotal, false), true);
assert.strictEqual(goesOn(noTotals, T.rowTotal, true), true);
assert.strictEqual(goesOn(noHeader, T.rowHeader, true), true);
assert.strictEqual(goesOn(withTotals, T.rowHeader, false), true);
assert.strictEqual(goesOn(withTotals, T.rowTotal, undefined), true);
assert.strictEqual(goesOn(withTotals, T.rowBanded, undefined), true);

console.log('ok - asking a table for the totals/header row state it already has changes nothing');
