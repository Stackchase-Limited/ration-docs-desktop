/*
 * DesktopEditors #334 - "Copy/paste does not preserve alignement inside a
 * table": in the reporter's Document3.docx a display equation (m:oMathPara,
 * m:jc center) sits in a table cell; Ctrl+A, Ctrl+C, Ctrl+V at the end -> the
 * pasted equation is left-aligned.
 *
 * Reproduced in 9.4 in the headless word editor (real sdk + the real desktop
 * save replayed by x2t): the pasted formula's ParaMath.Jc was align_Left and
 * the saved docx had <m:oMathParaPr><m:jc m:val="left"/> for the copy, "center"
 * for the original. Two causes, both in word/Editor/Math.js:
 *  - CopyProcessor.CopyRunContent (common/wordcopypaste.js) renders every
 *    formula to a picture for text/html via ParaMath.MathToImageConverter()
 *    with no bCopy: the formula object itself is laid out in a preview
 *    paragraph, and par.Set_Align(align_Left) there also sets the formula's
 *    Jc (Paragraph.Set_Align pushes into display formulas). That same object is
 *    then written to the internal binary the paste reads.
 *  - ParaMath.Copy did not copy Jc, so the selected-content copy had lost the
 *    justification anyway (the paste would fall back to the default).
 * Fix: MathToImageConverter restores the formula's Jc after drawing (without
 * bCopy), and ParaMath.Copy carries Jc over with Set_Align.
 *
 * This extracts the REAL ParaMath.prototype.Copy / Set_Align / raw_SetAlign /
 * MathToImageConverter / getPropsForWrite (word/Editor/Math.js) and
 * Paragraph.prototype.Set_Align (word/Editor/Paragraph.js) by brace matching and
 * runs the copy-processor sequence on stubs: Copy(false) of a centred formula,
 * MathToImageConverter() on that copy, then getPropsForWrite() (what
 * WriteOMathParaPr serialises).
 *
 * Claimed: the serialised copy keeps Jc = centre (and right / centerGroup);
 * a formula without its own Jc stays without one. NOT claimed: layout or the
 * rendered picture (stubbed here; in the headless editor the paste came back
 * centred and the replayed docx had m:jc="center" for both tables), inline
 * formulas (their alignment is the paragraph's, unaffected).
 *
 *   node fork-fix-tests/issue-334-copy-math-justification-test.js
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
const BASE_REF = process.env.BASE_REF || 'b7a1614833^';

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

const align_Right = 0, align_Left = 1, align_Center = 2, align_Justify = 3, para_Math = 77;

/* --- stub environment --- */
let historyOn = true;
const historyLog = [];
const History = { TurnOff() { historyOn = false; }, TurnOn() { historyOn = true; }, Add(c) { if (historyOn) historyLog.push(c); } };
function CChangesMathParaJc(cls, oldV, newV) { this.Class = cls; this.New = newV; }
function CChangesParagraphAlign(cls, oldV, newV) { this.Class = cls; this.New = newV; }

const mathSrc = src('word/Editor/Math.js');
const paraSrc = src('word/Editor/Paragraph.js');

function ParaMath() {
	this.Type = para_Math;
	this.Jc = undefined;
	this.Root = { CopyTo() {}, Correct_Content() {} };
}
const mathEnv = { ParaMath, History, CChangesMathParaJc, align_Left };
const mk = (text, marker, env) => new Function(...Object.keys(env), 'return ' + fn(text, marker))(...Object.values(env));
ParaMath.prototype.Copy = mk(mathSrc, 'ParaMath.prototype.Copy = function', mathEnv);
ParaMath.prototype.Set_Align = mk(mathSrc, 'ParaMath.prototype.Set_Align = function', mathEnv);
ParaMath.prototype.raw_SetAlign = mk(mathSrc, 'ParaMath.prototype.raw_SetAlign = function', mathEnv);
ParaMath.prototype.getPropsForWrite = mk(mathSrc, 'ParaMath.prototype.getPropsForWrite = function', mathEnv);
ParaMath.prototype.Is_Inline = () => false;
ParaMath.prototype.Get_JointSize = () => ({ W: 20, H: 5 });

// The preview paragraph of textArtPreviewManager's shape, with the real Paragraph.Set_Align.
const AscCommonStub = {
	History,
	g_dKoef_mm_to_pix: 3.78,
	IsShapeToImageConverter: false,
	isRealObject: o => null != o,
	CGraphics: function () { this.m_oCoordTransform = {}; this.init = () => {}; this.transform = () => {}; },
};
const previewPara = {
	Pr: {}, CompiledPr: {}, Content: [], Lines: [{ Ranges: [{ W: 20 }] }],
	private_AddPrChange() {}, private_UpdateTrackRevisionOnChangeParaPr() {},
	Internal_Content_Add(pos, item) { this.Content.splice(pos, 0, item); },
	Set_Tabs() {}, Set_Ind() {}, Set_Spacing() {}, Draw() {},
	Set_Align: mk(paraSrc, 'Paragraph.prototype.Set_Align = function', { AscCommon: AscCommonStub, CChangesParagraphAlign, para_Math }),
};
const editor = {
	ShowParaMarks: false,
	textArtPreviewManager: { getShape: () => ({ getDocContent: () => ({ Content: [previewPara], Reset() {}, Recalculate_Page() {} }) }) },
};
const document = { createElement: () => ({ getContext: () => ({}), toDataURL: () => 'data:image/png;base64,' }) };
const convEnv = {
	g_oTableId: { m_bTurnOff: false }, History, AscCommonWord: { Default_Tab_Stop: 12.5 },
	Asc: { editor, linerule_Auto: 1 }, editor, CParaTabs: function () {}, CParaInd: function () {},
	AscWord: { ParaSpacing: function () {} }, align_Left, AscCommon: AscCommonStub, window: {}, document,
	CNativeGraphics: function () {},
};
ParaMath.prototype.MathToImageConverter = mk(mathSrc, 'ParaMath.prototype.MathToImageConverter = function', convEnv);

/* --- what CopyProcessor does with a formula in the selection --- */
function copyAndSerialise(jc) {
	previewPara.Content.length = 0;
	previewPara.Pr = {};
	const original = new ParaMath();
	if (undefined !== jc)
		original.raw_SetAlign(jc);
	const copy = original.Copy(false);                 // selected-content copy
	const pic = copy.MathToImageConverter();           // CopyRunContent: <img> for text/html
	assert.ok(pic && 'string' === typeof pic.ImageUrl, 'picture rendered');
	return { written: copy.getPropsForWrite().Jc, original: original.Jc }; // WriteOMathParaPr
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + ': ' + e.message); }
}

for (const [name, jc] of [['centre', align_Center], ['right', align_Right], ['centerGroup', align_Justify]]) {
	const r = copyAndSerialise(jc);
	console.log(`  ${name}: copy serialised with Jc=${r.written}`);
	check(`${name} display formula: copied formula is written with the source Jc`, () => assert.strictEqual(r.written, jc));
	check(`${name} display formula: source formula untouched`, () => assert.strictEqual(r.original, jc));
}
check('formula without its own Jc: copy has none either (default applies)', () =>
	assert.strictEqual(copyAndSerialise(undefined).written, undefined));

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE ' + BASE_REF + ')' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
