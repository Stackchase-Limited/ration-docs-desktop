/*
 * #2560 - on macOS, picking an accent for a letter typed into a text box in the
 * spreadsheet editor doubled it: "e" became "eé" instead of "é". Cell editing,
 * Word body text and Presentation text boxes were fine.
 *
 * How the input arrives: macOS replaces the letter that was already typed
 * (press-and-hold accent menu, and input methods that commit through
 * insertText:replacementRange:), so the hidden textarea's value goes from "e"
 * to "é" outside a composition. CTextInput2.onInput (common/text_input2.js) sees
 * a removed "e" and an added "é" and calls asc_correctEnterText([e], [é]); only
 * if that refuses does it fall back to asc_enterText([é]), which appends.
 *
 * Cause: for a shape in a sheet, asc_correctEnterText lands in
 * DrawingObjects.prototype.CorrectEnterText (common/Charts/DrawingObjects.js),
 * which replaces only when AscWord.checkAsYouTypeEnterText (word/Editor/Common.js)
 * confirms the last history point typed that letter. In the spreadsheet that is
 * CHistory.prototype.checkAsYouTypeEnterText (cell/model/History.js), whose list
 * of "typing" descriptions lacked historydescription_Spreadsheet_ParagraphAdd -
 * the description DrawingObjectsController.enterText (cell/view/
 * DrawingObjectsController.js) gives to text typed into a sheet shape. So the
 * correction was always refused and the accented letter was appended.
 *
 * This extracts the real CTextInput2 onInput/checkTextInput/addTextCodes, the real
 * DrawingObjects.prototype.CorrectEnterText, the real word checkAsYouTypeEnterText
 * and the real cell CHistory.prototype.checkAsYouTypeEnterText; the history
 * description of the typed "e" is read from the real enterText source and the
 * AscDFH numbers from HistoryCommon.js. Stubs: a one-run text model for the
 * shape's content, the textarea, font picker and the history point's items
 * (shaped like the ones seen in headless Chromium: a CChangesRunAddItem as Class).
 *
 * NOT claimed: the real macOS event sequence (verified only by replaying it in
 * headless Chromium with the real cell sdk, "e" then a textarea replacement ->
 * "eé" before / "é" after); a dead key that arrives as a composition was already
 * correct there and is not exercised here. Needs a GUI check on a Mac.
 *
 * BASELINE=1 runs against the parent of the fix, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '6e82adabb0^';

function src(rel) {
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

/* --- AscDFH: the real numbers where HistoryCommon.js gives a literal --- */
const AscDFH = {};
for (const m of src('common/HistoryCommon.js').matchAll(/window\['AscDFH'\]\.(\w+)\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*;/g))
	AscDFH[m[1]] = Number(m[2]);
assert.ok(AscDFH.historydescription_Spreadsheet_ParagraphAdd !== undefined, 'Spreadsheet_ParagraphAdd not parsed');
const ParaRunAddItem = 'historyitem_ParaRun_AddItem';
if (AscDFH[ParaRunAddItem] === undefined) AscDFH[ParaRunAddItem] = 'ParaRun_AddItem';

/* the description a letter typed into a sheet shape is recorded under */
const enterText = extract(src('cell/view/DrawingObjectsController.js'), 'DrawingObjectsController.prototype.enterText = function');
const descName = (enterText.match(/AscDFH\.(historydescription_\w+)/) || [])[1];
assert.ok(descName && AscDFH[descName] !== undefined, 'enterText history description not found');

/* --- shape content: one run, cursor, left-extending selection --- */
class CRun {}
const run = new CRun();
const content = {
	chars: [], pos: 0, selStart: null,
	IsSelectionUse() { return this.selStart !== null; },
	GetCurrentParagraph() { return { GetContentPosition: () => [{ Class: run, Position: content.pos }] }; },
	MoveCursorLeft(add) { if (add && this.selStart === null) this.selStart = this.pos; if (this.pos > 0) this.pos--; },
	GetSelectedText() { return this.selStart === null ? '' : this.chars.slice(this.pos, this.selStart).join(''); },
	Remove() { if (this.selStart !== null) { this.chars.splice(this.pos, this.selStart - this.pos); this.selStart = null; } },
	AddToParagraph(item) { // records the run change into the open history point, like ParaRun.Add_ToContent
		history.Points[history.Index].Items.push(runAdd(this.pos, item.Value));
		this.chars.splice(this.pos++, 0, String.fromCodePoint(item.Value));
	},
};
const history = {
	Points: [], Index: -1,
	CheckUnionLastPoints() {},
	isEmpty() { return this.Points.length === 0; },
	Create_NewPoint(desc) { this.Points.push({ Description: desc, Items: [] }); this.Index = this.Points.length - 1; },
};
new Function('CHistory', 'AscDFH',
	extract(src('cell/model/History.js'), 'CHistory.prototype.checkAsYouTypeEnterText = function') + ';')(
	{ prototype: history }, AscDFH);

function runAdd(pos, code) {
	return { Class: { Type: AscDFH[ParaRunAddItem], Class: run, Pos: pos, Items: [{ GetCodePoint: () => code }], IsContentChange: () => true } };
}

/* typing a letter into the shape the way enterText records it */
function typeLetter(ch) {
	const code = ch.codePointAt(0);
	history.Create_NewPoint(AscDFH[descName]);
	history.Points[history.Index].Items.push(
		{ Class: {} }, // the sheet's own UndoRedoClassBase item comes first
		runAdd(content.pos, code));
	content.chars.splice(content.pos++, 0, ch);
}

const AscCommon = { History: history, CollaborativeEditing: { Is_Fast: () => false }, IsSpace: c => c === 32 };
const AscWord = {
	CRun,
	CRunText: function (v) { this.Value = v; },
	CRunSpace: function (v) { this.Value = v; },
};
AscWord.checkAsYouTypeEnterText = new Function('AscCommon',
	extract(src('word/Editor/Common.js'), 'function checkAsYouTypeEnterText(') + '\nreturn checkAsYouTypeEnterText;')(AscCommon);

function DrawingObjects() {}
new Function('DrawingObjects', 'AscWord', 'AscCommon', 'AscDFH',
	extract(src('common/Charts/DrawingObjects.js'), 'DrawingObjects.prototype.CorrectEnterText = function') + ';')(
	DrawingObjects, AscWord, AscCommon, AscDFH);
const drawingObjects = new DrawingObjects();
drawingObjects.controller = {
	getTargetDocContent: () => content,
	Save_DocumentStateBeforeLoadChanges() {}, loadDocumentStateAfterLoadChanges() {},
	resetSelection() { content.pos = content.selStart === null ? content.pos : content.selStart; content.selStart = null; },
	startRecalculate() {}, updateSelectionState() {},
};
drawingObjects.drawingDocument = { TargetStart() {}, TargetShow() {} };

/* --- the real hidden-textarea input path --- */
String.prototype.codePointsArray = function () { return Array.from(this, c => c.codePointAt(0)); };
String.prototype.getUnicodeIterator = function () {
	const cps = this.codePointsArray(); let i = 0;
	return { check: () => i < cps.length, next: () => { i++; }, value: () => cps[i] };
};
function CTextInput2() {}
const ti2 = src('common/text_input2.js');
const window = {};
new Function('CTextInputPrototype', 'AscFonts', 'window',
	['CTextInputPrototype.onInput = function', 'CTextInputPrototype.checkTextInput = function', 'CTextInputPrototype.addTextCodes = function']
		.map(m => extract(ti2, m) + ';').join('\n'))(
	CTextInput2.prototype, { FontPickerByCharacter: { checkTextLight: () => false } }, window);

const input = new CTextInput2();
Object.assign(input, {
	Text: '', TextBeforeComposition: '', IsComposition: false, area: '',
	Api: {
		isLongAction: () => false,
		asc_enterText(codes) { for (const c of codes) typeLetter(String.fromCodePoint(c)); },
		// what spreadsheet_api.asc_correctEnterText -> WorkbookView.CorrectEnterText does for a shape
		asc_correctEnterText: (oldCodes, newCodes) => drawingObjects.CorrectEnterText(oldCodes, newCodes),
	},
	log() {}, onFocusInputTextEnd() {}, clear() { this.Text = ''; this.area = ''; },
	getAreaValue() { return this.area; },
});
const ev = { type: 'input', preventDefault() {}, stopPropagation() {} };

/* 1. type "a" and "e", then macOS replaces the "e" with "é" in the textarea */
input.area = 'a'; input.onInput(ev);
input.area = 'ae'; input.onInput(ev);
assert.strictEqual(content.chars.join(''), 'ae');
input.area = 'aé'; input.onInput(ev);
assert.strictEqual(content.chars.join(''), 'aé', 'the accented letter must replace the typed one, got "' + content.chars.join('') + '"');

/* 2. choosing again from the menu replaces the replacement (last point is now CorrectEnterText) */
input.area = 'aè'; input.onInput(ev);
assert.strictEqual(content.chars.join(''), 'aè');

console.log('PASS #2560: accent replacement in a spreadsheet text box replaces the letter (' + descName + ')' +
	(process.env.BASELINE ? ' (BASELINE?!)' : ''));
