/*
 * #2275 (follow-up) - a spreadsheet header/footer "&F" (file name) printed as
 * "null" in a PDF saved from the desktop app.
 *
 * The desktop's Save as PDF converts the recovery folder's Editor.bin. x2t then
 * has no source name to hand doctrenderer as <DocumentTitle> (cextracttools.cpp
 * skips Editor.bin on purpose), so api.documentTitle keeps baseEditorsApi's
 * placeholder - the STRING "null" - and HeaderFooterField.calculateText, with
 * no DocInfo in the converter, fell back to it. Reproduced with x2t on
 * Editor.bin and the JsonParams the editor sends:
 *     before: FILE=null   SHEET=S   PAGE=1      after: FILE=book.xlsx ...
 * Fix: take the editor's title from the save parameters
 * (spreadsheetLayout.formulaProps.docTitle, which getPrintOptionsJson fills
 * from DocInfo and CELL("filename") already reads), and never print "null".
 *
 * This extracts the REAL HeaderFooterField.prototype.calculateText from
 * sdkjs cell/model/HeaderFooter.js and runs it against stubs for the api and
 * the workbook view.
 * Claimed: in the converter (no DocInfo) the field resolves to the title in the
 * print options, else to doctrenderer's documentTitle, and is empty - not
 * "null" - when neither exists; an open editor's DocInfo still wins.
 * NOT claimed: the PDF rendering itself (checked by hand with x2t, see above);
 * a document literally titled "null" with no other source now prints "".
 *
 * RD_REPO=<sdkjs checkout> (default ../../sdkjs relative to this file's dir).
 * BASELINE=1 reads the source at BASE_REF with git; it must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'e773c13a4c^';
const REL = 'cell/model/HeaderFooter.js';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces');
}

const text = src(REL);
const asc = { c_oAscHeaderFooterField: { pageNumber: 0, pageCount: 1, sheetName: 2, fileName: 3, filePath: 4, date: 5, time: 6, lineBreak: 7 } };
function HeaderFooterField(field) { this.field = field; }
const window = { Asc: {} };
new Function('window', 'asc', 'Asc', 'HeaderFooterField',
	extract(text, 'HeaderFooterField.prototype.calculateText = function') + ';')(window, asc, {}, HeaderFooterField);

const ws = { model: { sName: 'S', PagePrintOptions: null }, workbook: null };
function fileName(api) {
	window.Asc.editor = api;
	return new HeaderFooterField(asc.c_oAscHeaderFooterField.fileName).calculateText(ws, 0, 1);
}
const desktopSaveOptions = { spreadsheetLayout: { formulaProps: { docTitle: 'book.xlsx' } } };

let failed = 0;
function check(name, got, want) {
	const ok = got === want;
	if (!ok) failed++;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: ${JSON.stringify(got)}${ok ? '' : ' (want ' + JSON.stringify(want) + ')'}`);
}

// 1. the desktop Save as PDF: converter api, documentTitle placeholder, the editor's save parameters
check('desktop Save as PDF (Editor.bin + save params)',
	fileName({ documentTitle: 'null', wb: { getPrintOptionsJson: () => desktopSaveOptions } }), 'book.xlsx');
// 2. nothing known at all: empty, never the placeholder
check('no title anywhere',
	fileName({ documentTitle: 'null', wb: { getPrintOptionsJson: () => null } }), '');
// 3. a direct conversion: doctrenderer set documentTitle from the source name
check('direct xlsx -> pdf (doctrenderer documentTitle)',
	fileName({ documentTitle: 'hf', wb: { getPrintOptionsJson: () => null } }), 'hf');
// 4. an open editor: DocInfo wins
check('open editor (DocInfo)',
	fileName({ DocInfo: { Title: 'real.xlsx' }, documentTitle: 'real.xlsx', wb: { getPrintOptionsJson: () => desktopSaveOptions } }), 'real.xlsx');

if (failed) {
	console.log(`FAIL #2275: ${failed} case(s) wrong` + (process.env.BASELINE ? ' (baseline, as expected)' : ''));
	process.exit(1);
}
console.log('PASS #2275: &F resolves to the document title in a desktop PDF export, never "null"' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
