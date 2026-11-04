/*
 * #2459 - a table column named "Rückweg [km]" made its formulas fail with
 * FrmlAnotherParsingError (-305): the totals row could not be set to Sum, a
 * file holding SUBTOTAL(109,Table1[Rückweg '[km']]) showed #NAME? after a
 * recalculation, and a pasted copy of the table kept "Tabelle1[...]" (the
 * rename to the pasted table's name runs only on a formula that parses).
 *
 * In ms a column name inside a structured reference escapes [ ] # ' @ with an
 * apostrophe - Table1[Rückweg '[km']] - in the formula bar and in the file.
 *
 * - Parsing, cell/model/FormulaObjects/parserFormula.js cStrucTable._parseVal:
 *   for the one-column form the code stripped optional brackets around the
 *   name by slicing from the FIRST "[" to the last "]", so the escaped "'["
 *   inside the name was taken as the opening bracket and "km'" was looked up.
 *   (The [[Rückweg '[km']]] form goes through another branch and worked.)
 *   Now only a bracket that opens the column text is stripped.
 * - Writing, cell/model/WorkbookElems.js TableColumn.getTotalRowFormula built
 *   SUBTOTAL(109,Table1[<raw name>]) without escaping. Now escaped.
 *
 * This loads XRegExp from sdkjs/vendor, builds the real structured-reference
 * regex (build_rx_table/build_rx_table_cur, common/editorscommon.js), and runs
 * the real escapeTableCharacters, Worksheet.getTableIndexColumnByName,
 * cStrucTable._parseVal and TableColumn.getTotalRowFormula on it.
 *
 * NOT claimed: the formula autocomplete (WorkbookView insertInCellEditor)
 * still inserts the raw column name; the rest of the parser/calc is not run
 * here (verified separately headless: parse, recalc, x2t xlsx round trip).
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
const BASE_REF = process.env.BASE_REF || '63ec31f34d^';

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

const XRegExp = require(path.join(SDKJS, 'vendor', 'xregexp-all-min.js'));
const common = read('common/editorscommon.js');
const parser = read('cell/model/FormulaObjects/parserFormula.js');
const workbook = read('cell/model/Workbook.js');
const elems = read('cell/model/WorkbookElems.js');

/* --- the real structured-reference regex and escape helper --- */
const namedRanges = /var str_namedRanges\s*=\s*"(A-Za-z[^"]*)"/.exec(common);
assert.ok(namedRanges, 'str_namedRanges not found');
const rx = new Function('XRegExp', 'window', 'FormulaSeparators', 'str_namedRanges',
	'"use strict"; var cStrucTableLocalColumns;\n' +
	extract(common, 'function build_rx_table(local)') + '\n' +
	extract(common, 'function build_rx_table_cur()') + '\n' +
	'return build_rx_table(null);'
)(XRegExp, { AscCommon: {} }, { functionArgumentSeparator: ',' }, JSON.parse('"' + namedRanges[1] + '"'));
const parserHelp = {
	escapeTableCharacters: new Function('return ' + fnExpr(extract(common, 'parserHelper.prototype.escapeTableCharacters = function')))(),
};

/* --- a workbook with one table: the real Worksheet lookup over a TablePart stand-in --- */
const COLUMNS = ['Datum', 'Rückweg [km]', 'Erfasste\nStunden', "It's #1 @home", 'KM'];
const table = {
	DisplayName: 'Table1',
	getTableIndexColumnByName(name) { const i = COLUMNS.findIndex(c => c.toLowerCase() === name.toLowerCase()); return i < 0 ? null : i; },
};
const ws = { TableParts: [table] };
ws.getTableIndexColumnByName = new Function('parserHelp', 'return ' +
	fnExpr(extract(workbook, 'Worksheet.prototype.getTableIndexColumnByName = function')))(parserHelp);
const wb = {
	getTableIndexColumnByName(t, c) { const i = ws.getTableIndexColumnByName(t, c); return i === null ? null : { index: i, name: COLUMNS[i] }; },
};

const AscCommon = { FormulaTablePartInfo: { all: 0, data: 1, headers: 2, totals: 3, thisRow: 4 } };
const parseVal = new Function('parserHelp', 'AscCommon', 'return ' +
	fnExpr(extract(parser, 'cStrucTable.prototype._parseVal = function')))(
	Object.assign({ getColumnTypeByName: () => 0 }, parserHelp), AscCommon);

/* parse the structured reference at the start of `text` as the formula parser does; returns the column name it resolved to */
function resolve(text) {
	const match = XRegExp.exec(text, rx);
	assert.ok(match && match.tableName, 'the structured-reference regex did not match ' + JSON.stringify(text));
	assert.strictEqual(match[0], text, 'the regex stopped early in ' + JSON.stringify(text));
	const st = { wb };
	if (!parseVal.call(st, match)) return null;
	const idx = st.oneColumnIndex || st.hdtcstartIndex || st.colStartIndex;
	return idx ? idx.name : null;
}

/* sanity on both trees */
assert.strictEqual(resolve('Table1[KM]'), 'KM');
assert.strictEqual(resolve('Table1[[KM]]'), 'KM');
assert.strictEqual(resolve("Table1[[Rückweg '[km']]]"), 'Rückweg [km]', 'the [[...]] form already resolved before the fix');
assert.strictEqual(resolve('Table1[@KM]'), 'KM');

/* the defect: the one-column form with an escaped bracket in the name */
assert.strictEqual(resolve("Table1[Rückweg '[km']]"), 'Rückweg [km]',
	"Table1[Rückweg '[km']] did not resolve to its column (the formula fails with -305)");
assert.strictEqual(resolve("Table1[@Rückweg '[km']]"), 'Rückweg [km]');
assert.strictEqual(resolve("Table1[It''s '#1 '@home]"), "It's #1 @home");
assert.strictEqual(resolve('Table1[Erfasste\nStunden]'), 'Erfasste\nStunden');

/* --- writing: the totals row formula of such a column --- */
const getTotalRowFormula = new Function('parserHelp', 'AscCommonExcel', 'AscCommon', 'Asc', 'return ' +
	fnExpr(extract(elems, 'TableColumn.prototype.getTotalRowFormula = function')))(
	parserHelp, {}, { FormulaSeparators: { functionArgumentSeparator: ',' } },
	{ ETotalsRowFunction: { totalrowfunctionAverage: 1, totalrowfunctionCount: 2, totalrowfunctionCountNums: 3, totalrowfunctionCustom: 4,
		totalrowfunctionMax: 5, totalrowfunctionMin: 6, totalrowfunctionNone: 7, totalrowfunctionStdDev: 8, totalrowfunctionSum: 9, totalrowfunctionVar: 10 } });
function totals(name) {
	return getTotalRowFormula.call({ Name: name, TotalsRowFunction: 9 }, { DisplayName: 'Table1' }, false);
}
assert.strictEqual(totals('KM'), 'SUBTOTAL(109,Table1[KM])');
const generated = totals('Rückweg [km]');
assert.strictEqual(generated, "SUBTOTAL(109,Table1[Rückweg '[km']])",
	'the totals row formula must escape the column name as ms does, got ' + generated);
/* and what is written reads back as the same column */
for (const name of COLUMNS) {
	const ref = /,(Table1\[.*\])\)$/s.exec(totals(name))[1];
	assert.strictEqual(resolve(ref), name, 'round trip of ' + JSON.stringify(name) + ' via ' + JSON.stringify(ref));
}

console.log("ok - column names with [ ] # ' @ are escaped in structured references and parsed back");
