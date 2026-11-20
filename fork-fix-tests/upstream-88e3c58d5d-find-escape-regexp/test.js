/*
 * Upstream 88e3c58d5d (2026-08-05, no bug number) - user text went into
 * new RegExp() unescaped in the spreadsheet editor; a "(" in it threw a
 * SyntaxError, which the editor's global error handler turns into an editing
 * error (the editor drops to view-only).
 *
 * Places fixed (now AscCommon.escapeRegExp first): whole-word Find
 * (Worksheet._findAllCells, cell/model/Workbook.js), the spell-check "Change"
 * replacement (asc_nextWord, cell/api.js), and the translated subtotal caption
 * / show-details sheet-name prefix (cell/model/PivotTables.js).
 *
 * What runs: the WHOLE spreadsheet engine headless in docbuilder (shared
 * harness ../lib/sdkjs-docbuilder.js); the real search (Asc.editor.wb.Search,
 * what Find > Whole words runs) over A1:A6 = x | see f(x) here | f(x | aab |
 * a+b | aab.
 * Claimed: whole-word "f(x" (and "F(X", not match case) no longer throws and
 * finds the two cells; whole-word "a+b" finds the one "a+b" cell, not the two
 * "aab" cells the unescaped pattern matched.
 * NOT claimed: the spell-check and pivot-table paths (not driven here; same
 * one-call change).
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

// [search text, match case, expected count]
const CASES = [['f(x', false, 2], ['F(X', false, 2], ['f(x', true, 2], ['a+b', false, 1]];
const r = h.run({
	editor: 'cell', baseRef: BASE_REF, tag: 'findre', script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var sh = Api.GetActiveSheet();
['x', 'see f(x) here', 'f(x', 'aab', 'a+b', 'aab'].forEach(function (v, i) { sh.GetRange('A' + (i + 1)).SetValue(v); });
var CASES = ${JSON.stringify(CASES)};
for (var i = 0; i < CASES.length; i++) {
	try {
		var o = new Asc.asc_CFindOptions();
		o.asc_setFindWhat(CASES[i][0]); o.asc_setIsWholeWord(true); o.asc_setIsMatchCase(CASES[i][1]); o.asc_setScanOnOnlySheet(true);
		out(i, Asc.editor.wb.Search(o).Count);
	} catch (e) { out(i, 'exception: ' + e); }
}
builder.CloseFile();
` });

const ck = h.checker();
CASES.forEach((c, i) => {
	const got = r.results.get(i);
	ck.check(`whole-word find "${c[0]}"${c[1] ? ' (match case)' : ''}`, got === c[2], `${got} (want ${c[2]})`);
});
ck.finish(r);
