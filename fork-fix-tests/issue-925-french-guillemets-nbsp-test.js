/*
 * DesktopEditors #925 - "Auto-correction does not properly insert
 * non-breaking spaces inside French quotes": in French text, typing « or »
 * directly (bépo / AFNOR AZERTY have keys for them) adds no non-breaking space,
 * while typing " is turned into «nbsp ... nbsp».
 *
 * Reproduced in 9.4 in the headless word editor (real sdk, run language
 * fr-FR, CDocument.EnterText per character): "dit «bonjour» ok" stayed as
 * typed, and "dit « bonjour » ok" kept breakable spaces next to the quotes;
 * "Quoi?" -> "Quoi<nbsp>?" and " -> «<nbsp> worked.
 *
 * Cause: word/Editor/Paragraph/RunContent/Text.js CRunText.GetAutoCorrectFlags
 * did not start the French punctuation autocorrect for « (U+00AB) / »
 * (U+00BB), and word/Editor/Paragraph/Run/RunAutoCorrect.js
 * private_ProcessFrenchPunctuation only knew : ; ? !.
 * Fix: in fr-FR text » gets a non-breaking space before it (typed spaces
 * replaced, also after ? and !), « gets one after it unless one is already
 * there, and a space typed right after «nbsp is dropped.
 *
 * This loads the REAL RunAutoCorrect.js module (its IIFE, with stubs for the
 * paragraph/run model and CParagraphRunElements) and the REAL
 * CRunText.GetAutoCorrectFlags / CRunSpace.GetAutoCorrectFlags, then types
 * strings character by character into a one-run paragraph the way
 * ParaRun.Add does: add the element, ask it for its flags, run
 * CRunAutoCorrect.DoAutoCorrect.
 *
 * Claimed: the resulting text for « », typed spaces around them, ? before »,
 * an existing nbsp after «, and that : ? and " are not changed by the fix.
 * NOT claimed: the other autocorrects in DoAutoCorrect (only the French flag is
 * passed through here - the headless editor run covered the full chain, Undo
 * and the desktop save: "X «nbsp oui nbsp»" round-tripped through x2t), other
 * French locales (fr-CA/fr-CH/...; the existing rule is fr-FR only too).
 *
 *   node fork-fix-tests/issue-925-french-guillemets-nbsp-test.js
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
const BASE_REF = process.env.BASE_REF || '49123ea9fe^';

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

const para_Text = 1, para_Space = 2;
const window = { AscWord: {} };
const AscWord = window.AscWord;

/* --- run elements: real GetAutoCorrectFlags --- */
function CRunText(v) { this.Value = v; }
CRunText.prototype.Type = para_Text;
CRunText.prototype.IsText = () => true;
CRunText.prototype.IsNBSP = function () { return 0x00A0 === this.Value; };
CRunText.prototype.IsNumber = function () { return this.Value >= 0x30 && this.Value <= 0x39; };
CRunText.prototype.IsPunctuation = function () { return !/[\p{L}\p{N}]/u.test(String.fromCodePoint(this.Value)); };
function CRunSpace(v) { this.Value = undefined !== v ? v : 0x20; }
CRunSpace.prototype.Type = para_Space;
CRunSpace.prototype.IsText = () => false;
CRunSpace.prototype.IsNBSP = () => false;
AscWord.CRunText = CRunText;
AscWord.CRunSpace = CRunSpace;

/* --- the paragraph model the autocorrect walks --- */
class Pos {
	constructor(arr) { this.arr = arr.slice(); }
	Update(v, d) { this.arr[d] = v; this.arr.length = d + 1; }
	GetDepth() { return this.arr.length - 1; }
	Copy() { return new Pos(this.arr); }
	get idx() { return this.arr[this.arr.length - 1]; }
}
function CParagraphRunElements(contentPos, count, types) {
	this.pos = contentPos; this.count = count; this.types = types; this.els = []; this.positions = [];
	this.breakOnBadType = false;
}
CParagraphRunElements.prototype.SetBreakOnBadType = function (b) { this.breakOnBadType = b; };
CParagraphRunElements.prototype.SetBreakOnDifferentClass = function () {};
CParagraphRunElements.prototype.SetBreakOnMath = function () {};
CParagraphRunElements.prototype.SetSaveContentPositions = function () {};
CParagraphRunElements.prototype.GetElements = function () { return this.els; };
CParagraphRunElements.prototype.GetContentPositions = function () { return this.positions; };
CParagraphRunElements.prototype.take = function (el, i) {
	if (this.types && this.types.indexOf(el.Type) === -1) return !this.breakOnBadType;
	this.els.push(el); this.positions.push(new Pos([0, i]));
	return this.els.length < this.count;
};

let actions = 0;
const doc = {
	IsDocumentEditor: () => true, IsPresentationEditor: () => false,
	IsAutoCorrectFrenchPunctuation: () => true,
	StartAction() { actions++; }, FinalizeAction() {},
	GetHistory: () => ({}), IsSelectionLocked: () => false,
};
function makeRun() {
	const para = {
		GetLogicDocument: () => doc, GetPosByElement: () => new Pos([0]),
		TurnOffCorrectContent() {}, TurnOnCorrectContent() {},
		GetPrevRunElements(re) { for (let i = re.pos.idx - 1; i >= 0 && re.take(run.Content[i], i); i--); },
		GetNextRunElements(re) { for (let i = re.pos.idx; i < run.Content.length && re.take(run.Content[i], i); i++); },
		RemoveRunElement(p) { run.RemoveFromContent(p.idx, 1); return true; },
	};
	const run = {
		Content: [], State: { ContentPos: 0 },
		AddToContent(i, el) { this.Content.splice(i, 0, el); },
		RemoveFromContent(i, n) { this.Content.splice(i, n); },
		GetElement(i) { return this.Content[i]; },
		GetElementsCount() { return this.Content.length; },
		Get_CompiledPr: () => ({ Lang: { Val: 1036 } }),
		GetParagraph: () => para, GetParentForm: () => null,
	};
	return run;
}

/* --- load the real module --- */
const AscDFH = { historydescription_Document_AutoCorrectCommon: 1, historydescription_Document_AutoCorrectSmartQuotes: 2 };
new Function('window', 'AscWord', 'AscDFH', 'AscCommon', 'CParagraphRunElements', 'para_Text', 'para_Space', 'para_Math', 'para_Run',
	src('word/Editor/Paragraph/Run/RunAutoCorrect.js'))(window, AscWord, AscDFH, {}, CParagraphRunElements, para_Text, para_Space, 99, 98);
const FRENCH = AscWord.AUTOCORRECT_FLAGS_FRENCH_PUNCTUATION;
assert.ok(FRENCH && AscWord.CRunAutoCorrect, 'module loaded');
const textSrc = src('word/Editor/Paragraph/RunContent/Text.js');
const spaceSrc = src('word/Editor/Paragraph/RunContent/Space.js');
CRunText.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(textSrc, 'CRunText.prototype.GetAutoCorrectFlags = function'))(AscWord);
CRunSpace.prototype.GetAutoCorrectFlags = new Function('AscWord', 'return ' + fn(spaceSrc, 'CRunSpace.prototype.GetAutoCorrectFlags = function'))(AscWord);

/* ParaRun.Add: add at the cursor, then autocorrect from the element's own flags */
function type(s, run = makeRun()) {
	for (const ch of s) {
		const cp = ch.codePointAt(0);
		const el = 0x20 === cp ? new CRunSpace(cp) : new CRunText(cp);
		run.AddToContent(run.State.ContentPos, el);
		run.State.ContentPos++;
		const flags = el.GetAutoCorrectFlags();
		if (flags & FRENCH)
			new AscWord.CRunAutoCorrect(run, run.State.ContentPos - 1).DoAutoCorrect(flags & FRENCH);
	}
	return run.Content.map(e => (0x00A0 === e.Value ? '~' : String.fromCodePoint(e.Value))).join('');
}

let failed = 0;
function check(name, input, expected) {
	let got;
	try { got = type(input); assert.strictEqual(got, expected); console.log(`ok   - ${name}: ${JSON.stringify(input)} -> ${got}`); }
	catch (e) { failed++; console.log(`FAIL - ${name}: ${JSON.stringify(input)} -> ${got} (want ${expected}; ~ = nbsp)`); }
}

check('« » typed without spaces', 'dit «bonjour» ok', 'dit «~bonjour~» ok');
check('« » typed with ordinary spaces', 'dit « bonjour » ok', 'dit «~bonjour~» ok');
check('» after a question mark', '«Quoi ?»', '«~Quoi~?~»');
check('empty quotes', '« »', '«~»');
// unchanged behaviour
check(': and ? unchanged', 'Note : quoi?', 'Note~: quoi~?');
check('straight " is not touched by the French punctuation rule', 'a "b"', 'a "b"');
{
	// « typed in front of an existing nbsp: no second one
	const run = makeRun();
	type('~b'.replace('~', ' '), run);
	run.State.ContentPos = 0;
	const got = type('«', run);
	if (got === '«~b') console.log('ok   - « before an existing nbsp adds none: «~b');
	else { failed++; console.log('FAIL - « before an existing nbsp: ' + got); }
}

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE ' + BASE_REF + ')' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
