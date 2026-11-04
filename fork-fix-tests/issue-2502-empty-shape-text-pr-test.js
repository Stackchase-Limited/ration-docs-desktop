/*
 * #2502 - "font size is all over the place in presentations": after deleting
 * all the text of a text box or placeholder, the next typed text came out at
 * the list-style default size (18pt, 24pt) instead of the size of the text
 * that was deleted, and a deleted bulleted list lost its bullet and spacing.
 * Reproduced headless in docbuilder on the reporter's bug.pptx: a 22pt text
 * box, Ctrl+A, Delete, type -> 18pt; slide 1's 25pt bulleted list, Ctrl+A,
 * Delete or Backspace, type -> 24pt, no bullet, line spacing 0.9.
 *
 * Cause 1: CDocumentContentBase.private_Remove (word/Editor/DocumentContentBase.js)
 * swaps the emptied paragraph for private_CreateNewParagraph() when (a) the
 * one fully selected paragraph is removed with forward Delete, or (b) a
 * selection covering all paragraphs leaves both end paragraphs empty. In
 * shape text (bPresentation) the emptied first paragraph is now kept and the
 * cursor goes to its start (the emptied text run, not the paragraph-end run).
 *
 * Cause 2: the PPTY writer (common/Shapes/SerializeWriter.js) always wrote
 * endParaRPr from the paragraph-end run, so an empty paragraph whose text run
 * still held the deleted text's formatting (after Backspace) was saved with
 * the old endParaRPr and reopened at that size (the reporter's 32pt "A" that
 * came back as 24pt). Empty paragraphs now take endParaRPr from that run.
 *
 * This extracts the real private_Remove and WriteParagraph (+ the new
 * GetEndParaRunPr helper) and drives them with stub paragraphs/runs. It does
 * NOT claim anything about rendering, the toolbar size box, or autofit
 * (normAutofit shrinking 30pt to 27pt in the report is autofit, unchanged).
 * Document-editor behaviour (bPresentation false) is asserted unchanged.
 *
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs). BASELINE=1 reads the
 * sources at BASE_REF (default: parent of the fix) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'd303d6b9f0^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return '';
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const failures = [];
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures.push(name); console.log('FAIL ' + name + ': ' + e.message); }
}

/* ---------- part 1: private_Remove ---------- */

const type_Paragraph = 1, type_Table = 2, type_BlockLevelSdt = 3;
const contentBase = src('word/Editor/DocumentContentBase.js');
function CDocumentContentBase() {}
new Function('CDocumentContentBase', 'type_Paragraph', 'type_Table', 'type_BlockLevelSdt', 'AscWord',
	'reviewtype_Add', 'reviewtype_Remove',
	extract(contentBase, 'CDocumentContentBase.prototype.private_Remove = function') + ';')(
	CDocumentContentBase, type_Paragraph, type_Table, type_BlockLevelSdt, {}, 1, 2);

/* A paragraph whose selection covers all of its text and its paragraph mark. */
function StubPara(name) {
	this.name = name;
	this.empty = false;
	this.cursorAtStart = false;
}
StubPara.prototype.GetType = function() { return type_Paragraph; };
StubPara.prototype.IsParagraph = function() { return true; };
StubPara.prototype.IsTable = function() { return false; };
StubPara.prototype.IsSelectionEmpty = function() { return false; };
StubPara.prototype.IsSelectionToEnd = function() { return true; };
StubPara.prototype.IsSelectedOnlyParagraphMark = function() { return false; };
StubPara.prototype.Remove = function() { this.empty = true; return false; }; // false: paragraph mark selected
StubPara.prototype.IsEmpty = function() { return this.empty; };
StubPara.prototype.MoveCursorToStartPos = function() { this.cursorAtStart = true; };
StubPara.prototype.MoveCursorToEndPos = function() {};

function makeContent(nParas, bPresentation) {
	const c = new CDocumentContentBase();
	c.bPresentation = bPresentation;
	c.Content = [];
	for (let i = 0; i < nParas; i++) c.Content.push(new StubPara('P' + i));
	c.Selection = { Use: true, StartPos: 0, EndPos: nParas - 1 };
	c.CurPos = { ContentPos: 0 };
	c.GetLogicDocument = () => null;
	c.IsNumberingSelection = () => false;
	c.RemoveNumberingSelection = () => {};
	c.IsTrackRevisions = () => false;
	c.private_CreateNewParagraph = () => new StubPara('fresh');
	c.Internal_Content_Add = function(pos, el) { this.Content.splice(pos, 0, el); };
	c.Internal_Content_Remove = function(pos, n) { this.Content.splice(pos, n); };
	c.RemoveFromContent = c.Internal_Content_Remove;
	return c;
}

check('shape text: Ctrl+A, Delete on one paragraph keeps the paragraph', () => {
	const c = makeContent(1, true), p0 = c.Content[0];
	c.private_Remove(1, true, false, false, false);
	assert.strictEqual(c.Content.length, 1);
	assert.strictEqual(c.Content[0].name, 'P0', 'paragraph was replaced by a fresh one: its run/paragraph properties are gone');
	assert.ok(p0.cursorAtStart, 'cursor must be put into the emptied text run, not left in the paragraph-end run');
});

for (const count of [1, -1]) {
	check('shape text: Ctrl+A, ' + (count > 0 ? 'Delete' : 'Backspace') + ' over several paragraphs keeps the first one', () => {
		const c = makeContent(3, true);
		c.private_Remove(count, true, false, false, false);
		assert.strictEqual(c.Content.length, 1);
		assert.strictEqual(c.Content[0].name, 'P0', 'first paragraph was replaced by a fresh one: bullet, spacing and size lost');
		assert.ok(c.Content[0].cursorAtStart);
	});
}

check('document text: unchanged, a fresh paragraph still replaces the emptied one', () => {
	const one = makeContent(1, false);
	one.private_Remove(1, true, false, false, false);
	assert.strictEqual(one.Content[0].name, 'fresh');
	const many = makeContent(3, false);
	many.private_Remove(-1, true, false, false, false);
	assert.deepStrictEqual(many.Content.map(p => p.name), ['fresh']);
});

/* ---------- part 2: endParaRPr written for an empty paragraph ---------- */

const para_Run = 39, para_Text = 1;
const writerSrc = src('common/Shapes/SerializeWriter.js');
const STOP = new Error('stop after endParaRPr');

function writeEndParaRPr(paragraph) {
	const w = {
		written: null,
		WriteRecord1() {},
		WriteRecord2(type, value) { if (type === 1) this.written = value; },
		StartRecord() { throw STOP; }, // the run list follows; endParaRPr is already out
	};
	new Function('oThis', 'para_Run', 'AscFormat', 'CTextPr',
		extract(writerSrc, 'this.GetEndParaRunPr = function', true) + ';\n' +
		extract(writerSrc, 'this.WriteParagraph = function') + ';').call(
		w, w, para_Run, { CTextParagraphPr: function() {} }, function() {});
	try { w.WriteParagraph(paragraph); } catch (e) { if (e !== STOP) throw e; }
	return w.written;
}

function run(pr, text, isEnd) {
	return {
		Type: para_Run, Pr: pr,
		Content: text.split('').map(ch => ({ Type: para_Text, Value: ch.charCodeAt(0) })),
		IsParaEndRun: () => !!isEnd,
	};
}
function paragraph(runs, endPr) {
	return {
		Pr: { Bullet: null, Lvl: 0, DefaultRunPr: null },
		TextPr: { Value: endPr },
		Content: runs,
		Is_Empty() { return runs.every(r => r.IsParaEndRun() || r.Content.length === 0); },
	};
}

check('empty paragraph: endParaRPr carries the emptied run\'s size (32pt "A" deleted)', () => {
	const kept = { FontSize: 32, Bold: true }, staleEnd = { FontSize: 24, Bold: true };
	const p = paragraph([run(kept, ''), run(staleEnd, '', true)], staleEnd);
	assert.strictEqual(writeEndParaRPr(p), kept, 'endParaRPr written from the paragraph-end run: reopens at 24pt');
});

check('non-empty paragraph: endParaRPr still comes from the paragraph-end run', () => {
	const endPr = { FontSize: 18 };
	const p = paragraph([run({ FontSize: 22 }, 'text'), run(endPr, '', true)], endPr);
	assert.strictEqual(writeEndParaRPr(p), endPr);
});

if (failures.length) {
	console.log('FAIL #2502: ' + failures.length + ' check(s) failed' + (process.env.BASELINE ? ' (expected on BASELINE)' : ''));
	process.exit(1);
}
console.log('PASS #2502: emptied shape text keeps its formatting in the editor and in the saved file' +
	(process.env.BASELINE ? ' (BASELINE?!)' : ''));
