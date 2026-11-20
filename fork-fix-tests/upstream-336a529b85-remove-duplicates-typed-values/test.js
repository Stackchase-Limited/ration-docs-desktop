/*
 * Upstream 336a529b85 series (+ efcfc6f160, 1406a86512, 40cf307032; ONLYOFFICE
 * bugs 84133, 84135, 84136) - Data > Remove Duplicates deleted rows whose values
 * only LOOK the same once formatted.
 *
 * WorksheetView.setRemoveDuplicates compared rows by getValueWithFormat(), the
 * display text: 1.001 / 1.002 / 1.003 in a "0.00" column all show "1.00", so two
 * of the three rows were deleted (silent data loss); the number 1 and the text
 * "1" were also "duplicates". Fix: rows are compared by a key built from the
 * typed value (numbers by value, text/booleans case-insensitively). 40cf307032:
 * columns of the selection that props.columnList does not cover are compared
 * too; before, rows that differed only there were deleted.
 *
 * What runs: the WHOLE spreadsheet engine headless in docbuilder (shared harness
 * ../lib/sdkjs-docbuilder.js). Each case is a fresh sheet: values are set with
 * the builder API, the range is selected, and the real
 * WorksheetView.getRemoveDuplicates / setRemoveDuplicates run (what the Remove
 * Duplicates dialog's OK does); then the remaining values are read back.
 *
 * Claimed: formatted look-alike numbers and number-vs-text are kept; real
 * duplicates are still removed; "abc"/"ABC" count as duplicates (Excel);
 * a column outside a too-short columnList is compared (the columnList is
 * truncated by hand here - how the UI gets there is not reproduced).
 * NOT claimed: the dialog itself, undo, tables/autofilter ranges.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

// [name, cells [[addr, value, numFormat?]], range, truncate columnList to, expected column A after, expected B or null]
const CASES = [
	['numbers that all display "1.00"', [['A1', 'Key'], ['A2', '1.001', '0.00'], ['A3', '1.002', '0.00'], ['A4', '1.003', '0.00']],
		'A1:A4', 0, ['1.001', '1.002', '1.003'], null],
	['number 1 and text "1"', [['A1', 'Key'], ['A2', '1'], ['A3', '1', '@'], ['A4', '2']],
		'A1:A4', 0, ['1', '1', '2'], null],
	['real duplicates are still removed', [['A1', 'Key'], ['A2', '5'], ['A3', '5'], ['A4', '7']],
		'A1:A4', 0, ['5', '7', ''], null],
	['text compared case-insensitively, as Excel', [['A1', 'Key'], ['A2', 'abc'], ['A3', 'ABC'], ['A4', 'x']],
		'A1:A4', 0, ['abc', 'x', ''], null],
	['column outside a short columnList is compared', [['A1', 'Key'], ['B1', 'Other'], ['A2', '5'], ['B2', '1'], ['A3', '5'], ['B3', '2'], ['A4', '5'], ['B4', '3']],
		'A1:B4', 1, ['5', '5', '5'], ['1', '2', '3']],
];

const r = h.run({
	editor: 'cell', baseRef: BASE_REF, tag: 'rmdup', script: (work, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var CASES = ${JSON.stringify(CASES)};
for (var i = 0; i < CASES.length; i++) {
	var c = CASES[i];
	if (i > 0) Api.AddSheet('T' + i);
	var sh = Api.GetActiveSheet();
	for (var j = 0; j < c[1].length; j++) {
		if (c[1][j][2]) sh.GetRange(c[1][j][0]).SetNumberFormat(c[1][j][2]);
		sh.GetRange(c[1][j][0]).SetValue(c[1][j][1]);
	}
	sh.GetRange(c[2]).Select();
	try {
		var ws = Asc.editor.wb.getWorksheet();
		var props = ws.getRemoveDuplicates(false);
		if (c[3]) props.columnList.length = c[3];
		ws.setRemoveDuplicates(props);
		var a = [], b = [];
		for (var row = 2; row <= 4; row++) { a.push(String(sh.GetRange('A' + row).GetValue())); b.push(String(sh.GetRange('B' + row).GetValue())); }
		out(i, [a, b]);
	} catch (e) { out(i, 'exception: ' + e); }
}
builder.CloseFile();
` });

const ck = h.checker();
CASES.forEach((c, i) => {
	const got = r.results.get(i);
	const ok = Array.isArray(got) && JSON.stringify(got[0]) === JSON.stringify(c[4]) &&
		(c[5] === null || JSON.stringify(got[1]) === JSON.stringify(c[5]));
	ck.check(c[0], ok, `A2:A4=${JSON.stringify(got && got[0] || got)}${c[5] ? ' B2:B4=' + JSON.stringify(got && got[1]) : ''}` +
		` (want ${JSON.stringify(c[4])}${c[5] ? ' / ' + JSON.stringify(c[5]) : ''})`);
});
ck.finish(r);
