/*
 * #1568 - "Update style to match selection" (and "New style from selection")
 * ignored the highlight of the selected text: the style, and every other
 * paragraph using it, stayed unhighlighted. The reporter also named font
 * colour; that one was already captured.
 *
 * Both menu commands take their style from Paragraph.GetStyleFromFormatting
 * (word/Editor/Paragraph.js), which copies the first selected run's TextPr
 * into the paragraph style and its linked character style - but explicitly
 * cleared TextPr.HighLight first ("В стиль не добавляется HighLight"). Word
 * keeps w:highlight in a style's rPr; x2t round-trips it and CTextPr.Merge
 * and the highlight draw state already apply a style-level HighLight, so the
 * only thing missing was this copy.
 *
 * This extracts the real Paragraph.prototype.GetStyleFromFormatting and the
 * real asc_CStyle (constructor + prototype methods, Styles.js) and drives
 * them with a stub paragraph whose selected run has a yellow highlight, a
 * theme (Unifill) colour and an RGB colour. Run with BASELINE=1 to check the
 * same test against the parent of the fix, where it must fail.
 *
 * Claimed: the returned style object (and its linked run style) carries the
 * highlight and the font colour of the selection, both with a selection and
 * with a bare cursor. NOT claimed here: CStyles.Create_StyleFromInterface,
 * rendering or saving - those were checked with the headless word editor and
 * a real desktop save (styles.xml got <w:highlight w:val="yellow"/> and
 * <w:color ... w:themeColor="accent2"/> on "Heading 1", and survived a
 * reopen), not by this test.
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
const BASE_REF = process.env.BASE_REF || '85cc0673e2^';

function read(rel) {
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

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const paragraphJs = read('word/Editor/Paragraph.js');
const stylesJs = read('word/Editor/Styles.js');

/* the real asc_CStyle: constructor plus every asc_CStyle.prototype.X = function */
let styleSrc = extract(stylesJs, 'function asc_CStyle()') + '\n';
const re = /^asc_CStyle\.prototype\.(\w+)\s*=\s*function/mg;
let m;
while ((m = re.exec(stylesJs)))
	styleSrc += block(stylesJs, m.index) + ';\n';
assert.ok(/fill_TextPr/.test(styleSrc), 'asc_CStyle.fill_TextPr not extracted');

/* --- stubs --- */
// Stand-in for CTextPr: Copy clones own fields (CTextPr.Copy keeps HighLight and Unifill too).
function TextPr(obj) { Object.assign(this, obj); }
TextPr.prototype.Copy = function () { return new TextPr(JSON.parse(JSON.stringify(this))); };
function CParaPr() {}
CParaPr.prototype.Copy = function () { return new CParaPr(); };

const asc_CStyle = new Function('CTextPr', 'CParaPr', 'styletype_Paragraph', styleSrc + '\nreturn asc_CStyle;')(TextPr, CParaPr, 1);

function Paragraph() {}
new Function('Paragraph', 'asc_CStyle', 'styletype_Paragraph', 'styletype_Character',
	extract(paragraphJs, 'Paragraph.prototype.GetStyleFromFormatting = function') + ';')(
	Paragraph, asc_CStyle, 1, 2);

const heading = { Get_Name: () => 'Heading 1', Get_Next: () => 'normal' };
const normal = { Get_Name: () => 'Normal', GetName: () => 'Normal', Get_Next: () => null };
const styles = {
	Get(id) { return id === 'h1' ? heading : id === 'normal' ? normal : null; },
	GetDefaultParagraph: () => 'normal',
};

function para(selected) {
	const runPr = new TextPr({
		Bold: true,
		HighLight: { r: 255, g: 255, b: 0 },
		Unifill: { fill: { color: { color: { id: 1 } } } }, // theme colour accent2
		Color: { r: 192, g: 80, b: 77, Auto: false },
	});
	const p = new Paragraph();
	p.Pr = new CParaPr();
	p.Pr.PStyle = 'h1';
	p.Parent = { Get_Styles: () => styles };
	p.Content = [
		{ IsSelectionEmpty: () => true, Get_FirstTextPr: () => new TextPr({}) },
		{ IsSelectionEmpty: () => false, Get_FirstTextPr: () => runPr },
		{ IsSelectionEmpty: () => true, Get_FirstTextPr: () => new TextPr({}) },
	];
	p.Selection = { Use: selected, StartPos: 2, EndPos: 0 };
	p.CurPos = { ContentPos: 1 };
	return { p, runPr };
}

for (const selected of [true, false]) {
	const { p, runPr } = para(selected);
	const style = p.GetStyleFromFormatting();
	const what = selected ? 'selection' : 'cursor';
	assert.strictEqual(style.get_BasedOn(), 'Heading 1');
	for (const [kind, s] of [['paragraph style', style], ['linked run style', style.get_Link()]]) {
		const pr = s.get_TextPr();
		assert.deepStrictEqual(pr.HighLight, { r: 255, g: 255, b: 0 },
			`${what}: ${kind} lost the highlight - "update style" would not pass it on`);
		assert.deepStrictEqual(pr.Unifill, runPr.Unifill, `${what}: ${kind} lost the theme font colour`);
		assert.deepStrictEqual(pr.Color, runPr.Color, `${what}: ${kind} lost the RGB font colour`);
		assert.strictEqual(pr.Bold, true);
	}
	assert.ok(runPr.HighLight, 'the run itself must keep its highlight');
}

console.log('PASS #1568: style from selection keeps highlight and font colour' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
