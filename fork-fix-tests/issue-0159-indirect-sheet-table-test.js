/*
 * #159 - list data validation via INDIRECT of a table on another sheet.
 *
 * The reporter's reftest.xlsx (works in Excel and WPS) has four list
 * validations. In our 9.4 cell engine, run headless on that file, $G$4:$G$6
 * and List2!$B$14:$B$16 gave their lists, but
 * INDIRECT("List1!TableTest1[Column1]") and INDIRECT("List2!TableTest2[Column1]")
 * evaluated to #REF! (no drop-down); in a cell the same INDIRECT gave #VALUE!,
 * while the unqualified INDIRECT("TableTest1[Column1]") already worked.
 *
 * Cause: cINDIRECT.prototype.Calculate's parseReference() handled a sheet
 * prefix followed by an area, a cell or a name only, never a structured table
 * reference. Fix: after a single-sheet prefix it also resolves a table
 * reference (cStrucTable.createFromVal + toRef), accepted only if the table is
 * on that sheet.
 *
 * What runs: the REAL cINDIRECT.prototype.Calculate (lookupandreferenceFunctions.js),
 * extracted by brace matching, with stand-in parserHelp / cStrucTable / operand
 * classes that model the parser's answers for "Sheet!Table[Column]". Checked:
 * "List2!TableTest2[Column1]" -> the table's range on List2; the same with
 * the wrong sheet -> #REF!; an unqualified "TableTest2[Column1]" unchanged.
 *
 * NOT claimed: the real formula parser here. The end-to-end run (headless
 * Chromium, real cell sdk, the reporter's file: C4 -> TestT1..3, C7 ->
 * TestL1..3) is described in the commit. Typing =List1!TableTest1[Column1]
 * directly into a cell is still not parsed (separate, not changed).
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs); BASELINE=1 reads BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || 'e09e6b2cd5^';
const REL = 'cell/model/FormulaObjects/lookupandreferenceFunctions.js';

const text = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function block(t, from) {
	const open = t.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < t.length; i++) {
		if (t[i] === '{') depth++;
		else if (t[i] === '}' && --depth === 0) return t.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
const at = text.indexOf('cINDIRECT.prototype.Calculate = function');
assert.notStrictEqual(at, -1, 'cINDIRECT.prototype.Calculate not found');
const calcSrc = block(text, at);

/* --- stand-ins --- */
const cElementType = { error: 'error', array: 'array', name: 'name', name3D: 'name3D', cellsRange3D: 'area3D' };
const cErrorType = { bad_reference: '#REF!' };
function cError(t) { this.type = cElementType.error; this.errorType = t; }
function cBool(v) { this.value = v; }
function cArray() {}
function Sheet(name) { this.name = name; } Sheet.prototype.getName = function () { return this.name; };
const list1 = new Sheet('List1'), list2 = new Sheet('List2');
const wb = { aWorksheets: [list1, list2] };
list1.workbook = list2.workbook = wb;
const tables = { TableTest1: list1, TableTest2: list2 };
function Area3D(ws) { this.type = cElementType.cellsRange3D; this.ws = ws; }
Area3D.prototype.getWS = function () { return this.ws; };
function unused(n) { return function () { throw new Error(n + ' not expected here'); }; }

/* the parser's answers: "Sheet!" prefix, then "Table[Column]" */
const parserHelp = {
	is3DRef(f, pos) {
		const m = /^([A-Za-z0-9]+)!/.exec(f.slice(pos));
		if (!m) return [false];
		this.pCurrPos = pos + m[0].length;
		return [true, m[1], null];
	},
	isArea() { return false; },
	isRef() { return false; },
	isName() { return false; },
	isTable(f, pos) {
		const m = /^([A-Za-z0-9]+)\[([A-Za-z0-9]+)\]$/.exec(f.slice(pos));
		return m ? { tableName: m[1], columnName: m[2] } : null;
	},
};
const AscCommonExcel = {
	executeInR1C1Mode(_, fn) { fn(); },
	g_cCalcRecursion: { saveFunctionResult() {} },
	cStrucTable: { prototype: { createFromVal(v) {
		const ws = tables[v.tableName];
		return ws ? { type: 'table', toRef: () => new Area3D(ws) } : new cError(cErrorType.bad_reference);
	} } },
};

function cINDIRECT() {}
new Function('cINDIRECT', 'cBool', 'cError', 'cErrorType', 'cElementType', 'parserHelp', 'AscCommonExcel', 'cArray',
	'cArea3D', 'cRef3D', 'cName3D', 'cArea', 'cRef', 'cName',
	calcSrc + ';')(cINDIRECT, cBool, cError, cErrorType, cElementType, parserHelp, AscCommonExcel, cArray,
	unused('cArea3D'), unused('cRef3D'), unused('cName3D'), unused('cArea'), unused('cRef'), unused('cName'));
cINDIRECT.prototype.name = 'INDIRECT';

function indirect(str, ws) {
	const arg0 = { type: 'string', toString: () => str, tocString() { return this; } };
	return new cINDIRECT().Calculate([arg0], null, null, ws);
}
function show(r) { return r.type === cElementType.error ? r.errorType : 'range on ' + r.getWS().getName(); }

let r = indirect('TableTest2[Column1]', list1);
assert.strictEqual(show(r), 'range on List2', 'unqualified table reference: ' + show(r));
console.log('ok   INDIRECT("TableTest2[Column1]") -> range on List2 (unchanged)');

r = indirect('List2!TableTest2[Column1]', list1);
assert.strictEqual(show(r), 'range on List2', 'sheet-qualified table reference gave ' + show(r) + ' (the reporter\'s C7 list)');
console.log('ok   INDIRECT("List2!TableTest2[Column1]") -> range on List2');

r = indirect('List1!TableTest2[Column1]', list1);
assert.strictEqual(show(r), '#REF!', 'table on another sheet than named must be #REF!');
console.log('ok   INDIRECT("List1!TableTest2[Column1]") -> #REF! (table is not on List1)');
