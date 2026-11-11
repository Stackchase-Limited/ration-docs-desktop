/*
 * DesktopEditors #565 - "Incorrect display of formulas with vectors": i\vec and
 * j\vec (any i or j under an accent) showed no letter; other letters were fine.
 *
 * Reproduced in 9.4 with x2t (reporter's bug.docx -> PDF on macOS, fonts cache
 * without Cambria Math): the accent arrow is drawn, the i/j is not. With the
 * math runs set to Cambria Math (substituted by Asana Math) the i/j came out as
 * two circles and a brace.
 * Cause, word/Math/mathText.js: for an i/j under an accent
 * CMathText.private_getCode returns a glyph index of Cambria Math (2835 = italic
 * dotless i, 2836 = j, ...), and CMathText.Measure sets RecalcInfo.bAccentIJ so
 * that it is measured and drawn by GID. In any other font - the substitute where
 * Cambria Math is not installed (macOS, Linux), or the text font of a run with
 * its own w:rFonts - that index is an unrelated glyph or none.
 * Fix: Measure sets the font up for that letter like for any other (Draw already
 * did) and keeps the GID only if the loaded font's family is Cambria Math;
 * otherwise it uses the dotless code point (math italic U+1D6A4/U+1D6A5 for
 * default italic math letters, else U+0131/U+0237, whichever the font has).
 *
 * This extracts the REAL CMathText.prototype.private_getCode / Measure (and the
 * new helpers when present), CMathInfoTextPr with NeedUpdateFont & co. and the
 * lookup tables from mathText.js, and the TXT_ / STY_ constants from
 * mathTypes.js, and measures an accented i/j against a stub text measurer whose
 * loaded font is Cambria Math, Asana Math or Arial.
 *
 * Claimed: without Cambria Math the measured/drawn code is a dotless i/j code
 * point the font has, not a GID; with Cambria Math the GID path is unchanged; an
 * unaccented letter is unchanged. NOT claimed: glyph shapes or accent placement
 * (checked by eye in x2t PDFs: 𝚤/𝚥 under the arrow, Asana Math; ı/ȷ in Arial),
 * the on-screen editor (same Measure/Draw code, not run here).
 *
 *   node fork-fix-tests/issue-0565-accent-dotless-ij-test.js
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
const BASE_REF = process.env.BASE_REF || 'aa43ce0290^';

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

// "X = function ..." / "function X(...)" / "var X = {...}" -> its source text
function piece(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return '';
		throw new Error(marker + ' not found');
	}
	return block(text, at) + ';\n';
}

const mathText = src('word/Math/mathText.js');
const mathTypes = src('word/Math/mathTypes.js');

const consts = (mathTypes.match(/^var (TXT|STY)_[A-Z_]+\s*=\s*\d+;/gm) || []).join('\n') + '\n'
	+ (mathText.match(/^var MathTextInfo_[A-Za-z]+\s*=\s*\d+;/gm) || []).join('\n') + '\n';

const code = [
	consts,
	piece(mathText, 'var q_Math_Arrows ='),
	piece(mathText, 'var q_Math_SpecialEquals ='),
	piece(mathText, 'var q_Math_SpecialSymbols ='),
	piece(mathText, 'var q_Math_Apostrophe ='),
	'var para_Math_Placeholder = 0x7FFF;\n',
	'function CMathText(v) { this.value = v; this.Type = 0; this.bJDraw = false; this.RecalcInfo = {}; this.size = {}; }\n',
	'CMathText.prototype.IsPlaceholder = function () { return false; };\n',
	piece(mathText, 'CMathText.prototype.private_getCode = function'),
	piece(mathText, 'CMathText.prototype.Measure = function'),
	piece(mathText, 'CMathText.prototype.private_IsCambriaMathFont = function', true),
	piece(mathText, 'CMathText.prototype.private_getDotlessIJCode = function', true),
	piece(mathText, 'function CMathInfoTextPr('),
	piece(mathText, 'CMathInfoTextPr.prototype.NeedUpdateFont = function'),
	piece(mathText, 'CMathInfoTextPr.prototype.private_GetFontSize = function'),
	piece(mathText, 'CMathInfoTextPr.prototype.GetFontKoef = function'),
	piece(mathText, 'CMathInfoTextPr.prototype.GetFontSlot = function'),
	piece(mathText, 'CMathInfoTextPr.prototype.IsSpecilalOperator = function'),
	'return { CMathText, CMathInfoTextPr };',
].join('\n');

/* --- stub environment --- */
const AscWord = {
	fontslot_ASCII: 0, fontslot_EastAsia: 1, fontslot_CS: 2, fontslot_HAnsi: 3, TEXTWIDTH_DIVIDER: 16384,
	GetFontSlotByTextPr: () => 0,
};
const MatGetKoeffArgSize = () => 1;

// A text measurer whose loaded font is `family`, containing the code points in `has`.
function measurer(family, has) {
	const m = {
		gid: false, measured: [],
		SetFont() {}, SetFontSlot() {},
		SetStringGid(b) { this.gid = b; },
		GetCurrentFont: () => ({ GetFamilyName: () => family }),
		CheckUnicodeInCurrentFont: c => has.includes(c),
		MeasureCode(c) { this.measured.push({ code: c, gid: this.gid }); return { Width: 2, Height: 3, Ascent: 2, WidthG: 2 }; },
		Measure2Code() { return this.MeasureCode(0); },
	};
	return m;
}

const TXT_ROMAN = 0, STY_ITALIC = 2, STY_PLAIN = 3;

// Measure reaches g_oTextMeasurer as a free variable: each case gets fresh classes bound to its stub.
function build(m) {
	return new Function('AscWord', 'MatGetKoeffArgSize', 'g_oTextMeasurer', 'AscMath', code)(AscWord, MatGetKoeffArgSize, m, {});
}

// One letter in a math run, under an accent unless opts.accent === false, measured with a stub
// measurer whose loaded font is `family` and has the code points `has`.
function run(letter, family, has, opts) {
	opts = opts || {};
	const m = measurer(family, has);
	const { CMathText, CMathInfoTextPr } = build(m);
	const parentRun = {
		Pr: {},
		IsNormalText: () => false,
		IsAccent: () => opts.accent !== false,
		GetCompiled_ScrStyles: () => ({ scr: TXT_ROMAN, sty: opts.sty === undefined ? STY_ITALIC : opts.sty }),
	};
	const t = new CMathText(letter.charCodeAt(0));
	t.Parent = parentRun;
	// the run's own font: Cambria Math -> math text; anything else -> text font (MathTextInfo_NormalText)
	const font = opts.runFont || 'Cambria Math';
	const textPr = { FontSize: 11, FontSizeCS: 11, RFonts: { Ascii: { Name: font }, HAnsi: { Name: font }, CS: { Name: font }, EastAsia: { Name: font } } };
	const info = new CMathInfoTextPr({ TextPr: textPr, ArgSize: 0, bNormalText: false, bEqArray: false });
	t.Measure(m, textPr, info);
	const last = m.measured[m.measured.length - 1];
	return { code: t.RecalcInfo.StyleCode, byGid: !!t.RecalcInfo.bAccentIJ, measuredCode: last.code, measuredByGid: last.gid };
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + ': ' + e.message); }
}
const hex = c => '0x' + c.toString(16).toUpperCase();

const ALL = [0x1D6A4, 0x1D6A5, 0x131, 0x237];

let r = run('i', 'Asana Math', ALL);
console.log(`  i under accent, Asana Math: code ${hex(r.code)}, by GID ${r.byGid}`);
check('Asana Math (Cambria Math substitute): accented i is the math italic dotless i U+1D6A4, not a GID',
	() => { assert.strictEqual(r.code, 0x1D6A4); assert.strictEqual(r.byGid, false); assert.strictEqual(r.measuredByGid, false); });

r = run('j', 'Asana Math', ALL);
console.log(`  j under accent, Asana Math: code ${hex(r.code)}, by GID ${r.byGid}`);
check('Asana Math: accented j is U+1D6A5, not a GID',
	() => { assert.strictEqual(r.code, 0x1D6A5); assert.strictEqual(r.byGid, false); });

r = run('i', 'Asana Math', [0x131, 0x237]);
check('substitute without math dotless letters: falls back to U+0131',
	() => { assert.strictEqual(r.code, 0x131); assert.strictEqual(r.byGid, false); });

r = run('j', 'Arial', ALL, { runFont: 'Arial' });
console.log(`  j under accent, run in Arial: code ${hex(r.code)}, by GID ${r.byGid}`);
check('run in a text font (Arial): accented j is U+0237 (the font draws it italic), not a GID',
	() => { assert.strictEqual(r.code, 0x237); assert.strictEqual(r.byGid, false); });

r = run('i', 'Asana Math', [], { sty: STY_PLAIN });
check('font with no dotless i at all: the plain letter, never a GID',
	() => { assert.strictEqual(r.code, 0x69); assert.strictEqual(r.byGid, false); });

r = run('i', 'Cambria Math', ALL);
console.log(`  i under accent, Cambria Math: code ${r.code}, by GID ${r.byGid}`);
check('Cambria Math installed: unchanged, GID 2835 measured by GID',
	() => { assert.strictEqual(r.code, 2835); assert.strictEqual(r.byGid, true); assert.strictEqual(r.measuredByGid, true); });

r = run('i', 'Asana Math', ALL, { accent: false });
check('i not under an accent: unchanged (math italic i U+1D456)',
	() => { assert.strictEqual(r.code, 0x1D456); assert.strictEqual(r.byGid, false); });

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE ' + BASE_REF + ')' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
