/*
 * #2459 - formula autocomplete inserted the raw table column name. Typing
 * =SUM(Tabelle1[Rü in a cell and choosing "Rückweg [km]" from the list gave
 * =SUM(Tabelle1[Rückweg [km]]), which fails on Enter with -305
 * (FrmlAnotherParsingError). ms inserts Tabelle1[Rückweg '[km']]: inside a
 * structured reference [ ] # ' @ in a column name are escaped with '.
 *
 * Cause: cell/view/WorkbookView.js WorkbookView.prototype.insertInCellEditor
 * wrote the name of the chosen c_oAscPopUpSelectorType.TableColumnName item
 * into the cell editor as listed. It now goes through
 * parserHelp.escapeTableCharacters(name, true) first (the list itself still
 * shows the plain name, as in ms).
 *
 * This extracts the real insertInCellEditor and the real escapeTableCharacters
 * (common/editorscommon.js) and calls insertInCellEditor with a stub cell
 * editor, in both of its insert paths (replacing the typed part of the name,
 * and plain insert at the cursor). Functions, defined names and the
 * #This Row item are checked to be inserted unchanged.
 *
 * NOT claimed: the autocomplete list built in WorkbookView (it matches typed
 * text against the plain column name, so typing an already escaped prefix
 * such as "Rückweg '[" does not filter the list). The full flow - type,
 * pick from the real list, Enter - was run headless in Chromium against the
 * built sdk: baseline gives -305, fixed gives =SUM(Tabelle1[Rückweg '[km']]).
 *
 * RD_REPO overrides the sdkjs checkout. BASELINE=1 reads the parent of the fix
 * (BASE_REF), where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '7657e6076b^';

function read(rel) {
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
function extract(source, marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at);
}
/* `X.prototype.name = function (args) {...}` -> an anonymous function expression */
const fnExpr = src => 'function' + src.slice(src.indexOf('('));

const common = read('common/editorscommon.js');
const wbView = read('cell/view/WorkbookView.js');
const defines = read('cell/apiDefines.js');

const c_oAscPopUpSelectorType = new Function('return ' + block(defines, defines.indexOf('{', defines.indexOf('var c_oAscPopUpSelectorType'))).trim())();
const parserHelp = {
	escapeTableCharacters: new Function('return ' + fnExpr(extract(common, 'parserHelper.prototype.escapeTableCharacters = function')))(),
};
const insertInCellEditor = new Function('c_oAscPopUpSelectorType', 'AscCommon', 'AscCommonExcel', 'AscFonts', 'return ' +
	fnExpr(extract(wbView, 'WorkbookView.prototype.insertInCellEditor = function')))(
	c_oAscPopUpSelectorType, { parserHelp }, {}, {});

/* a cell editor holding `text`, the cursor at its end; lastFPos/lastFNameLength as set by the autocomplete for the typed part */
function editorWith(text, lastFPos, lastFNameLength) {
	const ce = {
		text, cursorPos: text.length, skipTLUpdate: true,
		getText(pos, len) { return this.text.substr(pos, len); },
		replaceText(pos, len, s) { this.text = this.text.slice(0, pos) + s + this.text.slice(pos + len); },
		insertFormula(s) { this.text = this.text.slice(0, this.cursorPos) + s + this.text.slice(this.cursorPos); return true; },
		close() { throw new Error('the editor should stay open'); },
	};
	return {
		cellEditor: ce, lastFPos, lastFNameLength, arrExcludeFormulas: [], skipHelpSelector: false,
		getWorksheet() { return {}; }, getCellEditMode() { return true; },
	};
}
function pick(typed, prefixLen, name, type) {
	const wb = editorWith(typed, prefixLen === null ? -1 : typed.length - prefixLen, prefixLen === null ? 0 : prefixLen);
	insertInCellEditor.call(wb, name, type, false);
	return wb.cellEditor.text;
}
const T = c_oAscPopUpSelectorType;

/* unchanged on both trees */
assert.strictEqual(pick('=SU', 2, 'SUM', T.Func), '=SUM(');
assert.strictEqual(pick('=SUM(Tabelle1[K', 1, 'KM', T.TableColumnName), '=SUM(Tabelle1[KM');
assert.strictEqual(pick('=SUM(Tabelle1[Er', 2, 'Erfasste Stunden', T.TableColumnName), '=SUM(Tabelle1[Erfasste Stunden');
assert.strictEqual(pick('=SUM(Tab', 3, 'Tabelle1', T.Table), '=SUM(Tabelle1');

/* the defect: a column name with characters that must be escaped in a structured reference */
assert.strictEqual(pick('=SUM(Tabelle1[Rü', 2, 'Rückweg [km]', T.TableColumnName), "=SUM(Tabelle1[Rückweg '[km']",
	'autocomplete inserted the raw column name; =SUM(Tabelle1[Rückweg [km]]) fails with -305');
assert.strictEqual(pick('=SUM(Tabelle1[', null, 'Rückweg [km]', T.TableColumnName), "=SUM(Tabelle1[Rückweg '[km']");
assert.strictEqual(pick('=Tabelle1[@It', 2, "It's #1 @home", T.TableColumnName), "=Tabelle1[@It''s '#1 '@home");
/* what was inserted reads back as the column name */
assert.strictEqual(parserHelp.escapeTableCharacters("Rückweg '[km']", false), 'Rückweg [km]');

console.log("ok - autocomplete inserts table column names escaped: Tabelle1[Rückweg '[km']]");
