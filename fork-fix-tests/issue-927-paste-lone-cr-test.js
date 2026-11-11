/*
 * #927's neighbour (paste side) - plain text whose lines end with a lone CR
 * ("one\rtwo\rthree": classic Mac line ends, some Mac apps, and our own copies
 * before #927 for soft breaks) was pasted into a document as ONE paragraph with
 * the lines run together: "onetwothree".
 *
 * Measured first: headed Chromium 109 (the CEF our 9.4 app ships) under Xvfb, a
 * GTK clipboard owner offering "one\rtwo\rthree", a real Ctrl+V: the paste event's
 * getData('text/plain') is 'one\rtwo\rthree' - the browser passes CRs on as they
 * are (CRLF and LF arrive unchanged too). So the editor sees the lone CRs.
 *
 * Cause: common/wordcopypaste.js PasteProcessor._pasteText hands the text to
 * _getContentFromText (word), textToPresentationContent (slides) and
 * textToPDFContent (PDF); all three start a paragraph on LF only and `continue`
 * on CR (13). CRLF works because of the LF; a lone CR is simply dropped.
 * (The spreadsheet path, cell/model/clipboard.js _getTableFromText, already
 * treats CR as a row break.)
 *
 * Fix: _pasteText turns CRLF and lone CR into LF before any of the three run.
 *
 * This extracts the REAL _pasteText and _getContentFromText from the
 * PasteProcessor prototype (brace matching) plus the real
 * String.prototype.getUnicodeIterator (vendor/string.js), and runs the word
 * path with stub paragraphs/runs that record what is inserted.
 *
 * Claimed: LF, CRLF and lone-CR text all paste as the same paragraphs in the
 * word editor; LF and CRLF results are unchanged from before. NOT claimed: the
 * slide and PDF paths (same normalisation, same input to the same kind of loop,
 * not run here); what macOS apps put on the pasteboard (not run on macOS).
 *
 *   node fork-fix-tests/issue-927-paste-lone-cr-test.js
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
const BASE_REF = process.env.BASE_REF || 'd60507f1e5^';

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
function method(text, name) {
	const at = text.indexOf('\n\t' + name + ': function');
	if (at === -1) throw new Error(name + ' not found');
	return block(text, text.indexOf('function', at));
}

// the real unicode iterator the paste loop walks with
new Function(fs.readFileSync(path.join(SDKJS, 'vendor/string.js'), 'utf8'))();
assert.ok(String.prototype.getUnicodeIterator, 'vendor/string.js did not install getUnicodeIterator');

const wcp = src('common/wordcopypaste.js');
const pasteTextSrc = method(wcp, '_pasteText');
const contentSrc = method(wcp, '_getContentFromText');
assert.ok(pasteTextSrc.includes('fPasteTextWordCallback') && contentSrc.includes('getNewParagraph'), 'sliced the wrong methods');

/* --- stubs: paragraphs and runs that just record what goes in --- */
class Paragraph { constructor() { this.Content = [{ end: true }]; } Internal_Content_Add(pos, run) { this.Content.splice(pos, 0, run); } Set_Pr() {} }
class ParaRun { constructor() { this.Content = []; } AddToContent(pos, item) { this.Content.push(item); } }
const AscWord = {
	Paragraph,
	CRunTab: function () { this.ch = '\t'; },
	CRunText: function (c) { this.ch = String.fromCodePoint(c); },
	CRunSpace: function () { this.ch = ' '; },
};
const Asc = { c_dMaxParaRunContentLength: 256 };
const PasteElementsId = { g_bIsDocumentCopyPaste: true, g_bIsPDFCopyPaste: false };
const factory = new Function('AscWord', 'ParaRun', 'Asc', 'PasteElementsId', 'window', 'editor',
	'return { _pasteText: ' + pasteTextSrc + ', _getContentFromText: ' + contentSrc + ' };');

function paste(text) {
	const proc = factory(AscWord, ParaRun, Asc, PasteElementsId, { AscCommon: { g_specialPasteHelper: { specialPasteStart: false } } }, {});
	let inserted = null;
	proc.oDocument = { GetDirectParaPr: () => null, GetDirectTextPr: () => null, GetCurrentParagraph: () => null };
	proc.bNested = false;
	proc._AddNextPrevToContent = () => {};
	proc.InsertInDocument = function () { inserted = this.aContent; };
	proc.api = { pre_Paste: (a, b, cb) => cb() };
	proc._pasteText(text);
	return inserted.map(p => p.Content.filter(r => r.Content).map(r => r.Content.map(i => i.ch).join('')).join(''));
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + ': ' + e.message); }
}

const lf = paste('one\ntwo\nthree');
const crlf = paste('one\r\ntwo\r\nthree');
const cr = paste('one\rtwo\rthree');
const crEnd = paste('one\rtwo\r');
console.log('  LF  :', JSON.stringify(lf));
console.log('  CRLF:', JSON.stringify(crlf));
console.log('  CR  :', JSON.stringify(cr));

check('LF text pastes as three paragraphs', () => assert.deepStrictEqual(lf, ['one', 'two', 'three']));
check('CRLF text pastes as three paragraphs', () => assert.deepStrictEqual(crlf, ['one', 'two', 'three']));
check('lone-CR text pastes as three paragraphs (was one: "onetwothree")', () => assert.deepStrictEqual(cr, ['one', 'two', 'three']));
check('lone-CR text with a trailing CR: two paragraphs, no empty third', () => assert.deepStrictEqual(crEnd, ['one', 'two']));
check('a tab inside a line is kept', () => assert.deepStrictEqual(paste('a\tb\rc'), ['a\tb', 'c']));

console.log(failed ? `${failed} FAILED` + (process.env.BASELINE ? ' (BASELINE)' : '') : 'all passed');
process.exit(failed ? 1 : 0);
