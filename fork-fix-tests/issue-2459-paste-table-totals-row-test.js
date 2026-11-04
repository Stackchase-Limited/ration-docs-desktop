/*
 * #2459 (found verifying the earlier #2459 fixes) - copying a formatted table
 * with a totals row and pasting it into another workbook (or the same one)
 * dropped the totals row when the source xlsx's <tableStyleInfo> had no
 * showColumnStripes attribute. The attribute is optional; Excel always writes
 * it, some generators do not. The totals row then became a data row, its
 * SUBTOTAL(109,Table1[col]) referenced its own cell -> circular-reference
 * warning (-320), total 0.
 *
 * Cause: AutoFilters._addNewFilter (cell/model/autofilters.js), which builds
 * the table for a paste, a sheet-to-sheet table move and their redo, copied
 * HeaderRowCount/TotalsRowCount (and the style flags) only when
 * tablePart.TableStyleInfo.ShowColumnStripes was not null.
 *
 * This extracts the real _addNewFilter and the real TableStyleInfo
 * (cell/model/WorkbookElems.js) and calls _addNewFilter as the paste does
 * (style name, tablePart, offset) with minimal worksheet stubs, for sources
 * with and without the attribute, with a totals row and without a header row.
 *
 * Verified separately with the real cell sdk headless (x2t-converted xlsx,
 * copy A1:E5, paste into another workbook and the same one): before the fix
 * totals=null, total 0 and asc_onError -320; after, totals=1 and 66.
 * NOT claimed here: rendering, renameSheetCopy, history, or the file open
 * (which keeps TableStyleInfo with only that flag null - nothing lost there).
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
const BASE_REF = process.env.BASE_REF || '9d9df4637d^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match from the first '{' at or after `from`, returning source through its close. */
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const elems = read('cell/model/WorkbookElems.js');
const filters = read('cell/model/autofilters.js');

const TableStyleInfo = new Function(extract(elems, 'function TableStyleInfo()') + '\nreturn TableStyleInfo;')();
// "_addNewFilter: function (...) {...}" -> "function (...) {...}"
const addNewFilter = new Function('AscCommonExcel',
	'return ' + extract(filters, '_addNewFilter: function').replace(/^_addNewFilter:\s*/, '') + ';'
)({ TableStyleInfo: TableStyleInfo });

/* --- stubs: a worksheet that only collects table parts --- */
function TablePart() {
	this.Ref = null; this.HeaderRowCount = null; this.TotalsRowCount = null;
	this.TableStyleInfo = null; this.TableColumns = null; this.DisplayName = null;
}
TablePart.prototype.addAutoFilter = function () { this.AutoFilter = {}; };
TablePart.prototype.renameSheetCopy = function () {};
function makeCtx() {
	const ws = {
		TableParts: [],
		workbook: { dependencyFormulas: { getNextTableName: () => 'Table9' } },
		createTablePart: () => new TablePart(),
		addTablePart(t) { this.TableParts.push(t); },
	};
	return { worksheet: ws, _generateColumnNameWithoutTitle: () => [] };
}
function source(hdr, totals, flags) {
	const t = new TablePart();
	t.DisplayName = 'Table1';
	t.HeaderRowCount = hdr;
	t.TotalsRowCount = totals;
	t.TableStyleInfo = Object.assign(new TableStyleInfo(), { Name: 'TableStyleMedium2' }, flags);
	t.TableColumns = [{ clone() { return this; } }];
	return t;
}
const paste = (src) => addNewFilter.call(makeCtx(), { r1: 2, c1: 1, r2: 6, c2: 5 }, 'TableStyleMedium2', false, 'Table2', src, { row: 2, col: 1 });
const flags = (t) => ['ShowColumnStripes', 'ShowRowStripes', 'ShowFirstColumn', 'ShowLastColumn'].map(k => t.TableStyleInfo[k]).join('/');

/* 1. the reported file: <tableStyleInfo name=".." showRowStripes="1"/> and totalsRowCount="1" */
let t = paste(source(null, 1, { ShowRowStripes: true }));
assert.strictEqual(t.TotalsRowCount, 1, 'totals row dropped on paste: the SUBTOTAL in it becomes a circular reference');
assert.strictEqual(t.HeaderRowCount, null);
assert.strictEqual(flags(t), 'false/true/false/false');

/* 2. no header row, first column on, still no showColumnStripes */
t = paste(source(0, 1, { ShowRowStripes: true, ShowFirstColumn: true }));
assert.strictEqual(t.HeaderRowCount, 0, 'a table without a header row gained one on paste');
assert.strictEqual(t.TotalsRowCount, 1);
assert.strictEqual(flags(t), 'false/true/true/false', 'style flags of the source lost');

/* 3. a file with the attribute (as Excel writes it): unchanged */
t = paste(source(null, 1, { ShowColumnStripes: false, ShowRowStripes: true, ShowFirstColumn: false, ShowLastColumn: false }));
assert.strictEqual(t.TotalsRowCount, 1);
assert.strictEqual(flags(t), 'false/true/false/false');
t = paste(source(null, null, { ShowColumnStripes: true, ShowRowStripes: false, ShowFirstColumn: false, ShowLastColumn: true }));
assert.strictEqual(t.TotalsRowCount, null);
assert.strictEqual(flags(t), 'true/false/false/true');

/* 4. no source table (format as table): defaults as before */
t = addNewFilter.call(makeCtx(), { r1: 0, c1: 0, r2: 3, c2: 2 }, 'TableStyleMedium2', false, null, null, null);
assert.strictEqual(t.TotalsRowCount, null);
assert.strictEqual(t.HeaderRowCount, null);
assert.strictEqual(flags(t), 'false/true/false/false');

console.log('PASS #2459: pasted table keeps header/totals rows and style flags without showColumnStripes' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
