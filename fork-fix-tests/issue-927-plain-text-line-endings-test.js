/*
 * DesktopEditors #927 - "When pasting text from OnlyOffice into a notepad
 * document, line breaks appear" (Linux only; "does not occur on Windows",
 * "LibreOffice doesn't have this problem").
 *
 * Cause: the word editor's text/plain clipboard flavour is
 * CDocument.GetSelectedText(false) (word/api.js asc_CheckCopy). The run-level
 * getter (word/Editor/Run.js ParaRun.prototype.GetSelectedText) ends a
 * paragraph or a table row with "\r\n" and a soft break (Shift+Enter) with a
 * lone "\r" unless the caller passes separators. Measured in the headless word
 * editor (real sdk, Chromium 138): three typed lines with a soft break copy as
 * "First line\r\nSecond\rsoft\r\n\r\n". Blink converts text/plain newlines only
 * on Windows, so Linux/macOS receive the CRs as is, and editors and terminals
 * there take each "\r" as a break of its own.
 *
 * Fix: asc_CheckCopy passes ParaSeparator / TableRowSeparator /
 * NewLineSeparator "\n" when AscBrowser.isWindows is false; Windows unchanged.
 *
 * This extracts the REAL asc_CheckCopy (word/api.js) and the REAL
 * ParaRun.prototype.GetSelectedText (word/Editor/Run.js) by brace matching; a
 * stub logic document feeds the separator options asc_CheckCopy hands it into
 * the real run getter over a paragraph "ab<soft break>c<para end>" and a last
 * table cell "d<para end>".
 *
 * Claimed: off Windows the Text flavour contains no "\r" (paragraph, soft
 * break and table row all "\n", cell tab kept); on Windows it is byte for byte
 * the old CR/LF output. NOT claimed: what a given Linux editor shows for CRs
 * (not run on a Linux desktop), or anything about the text/html flavour.
 * Also seen in the headless editor: pasting the copied text back as plain
 * text, the old lone "\r" was dropped ("Secondsoft"); with "\n" the soft break
 * comes back as a paragraph break.
 *
 *   node fork-fix-tests/issue-927-plain-text-line-endings-test.js
 *   RD_REPO=<sdkjs checkout>   (default ../sdkjs)
 *   BASELINE=1                 runs against BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '981db8c0e0^';

function src(rel) {
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

function fn(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) throw new Error(marker + ' not found');
	return block(text, text.indexOf('function', at));
}

/* --- the real run getter --- */
const P = { para_Text: 1, para_Space: 2, para_Tab: 3, para_NewLine: 4, para_End: 5, para_Drawing: 6, para_Numbering: 7,
	para_PresentationNumbering: 8, para_PageNum: 9, para_PageCount: 10, para_Math_Text: 11, para_Math_BreakOperator: 12 };
const AscCommonRun = { encodeSurrogateChar: c => String.fromCodePoint(c) };
const runGetSelectedText = new Function(...Object.keys(P), 'AscCommon',
	'return ' + fn(src('word/Editor/Run.js'), 'ParaRun.prototype.GetSelectedText = function'))(...Object.values(P), AscCommonRun);

const ch = c => ({ Type: P.para_Text, GetCodePoint: () => c.codePointAt(0) });
function run(items, para) {
	return { Content: items, Selection: { Use: false }, State: {}, GetParagraph: () => para, GetSelectedText: runGetSelectedText };
}
const bodyPara = { Get_DocumentNext: () => ({}), IsTableCellContent: () => false };
const lastCellPara = { Get_DocumentNext: () => null, IsTableCellContent: () => true, Parent: { IsLastTableCellInRow: () => true } };
const firstCellPara = { Get_DocumentNext: () => null, IsTableCellContent: () => true, Parent: { IsLastTableCellInRow: () => false } };
const runs = [
	run([ch('a'), ch('b'), { Type: P.para_NewLine }, ch('c'), { Type: P.para_End }], bodyPara),
	run([ch('x'), { Type: P.para_End }], firstCellPara),
	run([ch('d'), { Type: P.para_End }], lastCellPara),
];
const seenPr = [];
const logicDocument = {
	GetSelectedText(bClearText, oPr) {
		seenPr.push(oPr);
		return runs.map(r => r.GetSelectedText(true, bClearText, oPr)).join('');
	},
	IsDrawingSelected: () => false,
};

/* --- the real asc_CheckCopy --- */
const F = { Text: 1, Html: 2, Internal: 4, HtmlElement: 8, Rtf: 16, Image: 32 };
function copyText(isWindows) {
	const AscCommon = { c_oAscClipboardDataFormat: F, AscBrowser: { isWindows } };
	const checkCopy = new Function('AscCommon', 'window',
		'return ' + fn(src('word/api.js'), 'asc_docs_api.prototype.asc_CheckCopy = function'))(AscCommon, {});
	const api = { WordControl: { m_oLogicDocument: logicDocument } };
	const data = {};
	checkCopy.call(api, { pushData(f, v) { data[f] = v; } }, F.Text);
	return data[F.Text];
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + ': ' + e.message); }
}

const offWindows = copyText(false);
const onWindows = copyText(true);
console.log('  off Windows text/plain:', JSON.stringify(offWindows));
console.log('  on Windows  text/plain:', JSON.stringify(onWindows));

check('Linux/macOS: no CR in text/plain (paragraph, soft break, table row are LF)', () =>
	assert.strictEqual(offWindows, 'ab\nc\nx\td\n'));
check('Windows: unchanged CR/LF output', () =>
	assert.strictEqual(onWindows, 'ab\rc\r\nx\td\r\n'));

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE ' + BASE_REF + ')' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
