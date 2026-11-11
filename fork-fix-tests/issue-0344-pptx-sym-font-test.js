/*
 * #344 (and #328) - symbols in pptx slides drew as unrelated glyphs.
 *
 * PowerPoint's Insert > Symbol writes the symbol as a private-use code
 * U+F020..U+F0FF in a run carrying <a:sym typeface="Symbol"/> (or "Wingdings 2",
 * ...): PowerPoint draws those characters with the sym font and the rest of the
 * run with the latin font. The pptx reader (common/Shapes/Serialize.js,
 * ReadRunProperties record 6) skipped a:sym, so the symbols were drawn with the
 * latin font, which has no U+F0xx, i.e. by the by-character fallback: the
 * reporter's Symbol arrow U+F0AC (u <- 0) came out as a Wingdings star; #328's
 * Pi, epsilon, approx-equal and arrows as Wingdings pictures. (Drawing them with
 * the font named Symbol is wrong too on a Mac: Apple's Symbol.ttf has no symbol
 * cmap and U+F0AC lands on U+00AC, a "not" sign - measured in the editor.)
 *
 * Fixed: a:sym "Symbol" codes become the Unicode characters they are (Adobe
 * Symbol encoding); another sym font is given to the symbol characters only, by
 * cutting the run. Measured in the real editor (headless Chromium,
 * .rd-work/wt/cx-tmp/h/shot.js on the reporter's TD02_2019.pptm-5.pptx and
 * #328's lec5.pptx): before "u ✶ 0", "✍ is (t, ♏)"; after "u ← 0",
 * "Π is (t, ε)", matching #328's LibreOffice screenshots.
 *
 * This extracts from the real Serialize.js the table and helpers, the a:sym
 * record of ReadRunProperties and the reader's text-run block
 * (case AscFormat.PARRUN_TYPE_RUN of ReadParagraph), and runs the block on a
 * scripted stream with stub ParaRun/CTextPr/paragraph.
 * NOT claimed: glyph drawing itself (font files), the sym font of a run whose
 * symbol is not a U+F0xx code, saving (a:sym is not written back; the Symbol
 * characters are saved as their Unicode characters, which PowerPoint draws).
 *
 * RD_REPO=<sdkjs checkout> overrides the tree. BASELINE=1 reads the sources at
 * BASE_REF (the parent of the fix) with git show, and must fail there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// the parent of the #344 commit; the integrator re-pins it after cherry-picking
const BASE_REF = process.env.BASE_REF || '6884d875b3^';
const rel = 'common/Shapes/Serialize.js';
const text = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, rel), 'utf8');

function block(src, from) {
	const open = src.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < src.length; i++) {
		if (src[i] === '{') depth++;
		else if (src[i] === '}' && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function find(marker, from) {
	const at = text.indexOf(marker, from || 0);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return at;
}

/* helpers (absent before the fix: then the block below must not need them) */
let helpers = '';
const tableAt = text.indexOf('var SYMBOL_FONT_TO_UNICODE = {');
if (tableAt !== -1) {
	helpers += block(text, tableAt) + ';\n';
	for (const fn of ['IsSymFontCode', 'MapSymbolFontCodes', 'SplitTextBySymFont'])
		helpers += block(text, find(`function ${fn}(`)) + '\n';
}

/* the a:sym record of ReadRunProperties: "case 6:" after the "//cs" one */
const rrp = find('this.ReadRunProperties = function()');
const symCase = block(text, find('case 6:', find('//cs', rrp)));

/* the text-run block of ReadParagraph */
const runCase = block(text, find('case AscFormat.PARRUN_TYPE_RUN:', find('this.ReadParagraph = function')));

/* --- stubs --- */
const g_nodeAttributeEnd = 0xFB;
function CTextPr() { this.RFonts = { Ascii: undefined, HAnsi: undefined }; }
CTextPr.prototype.Set_FromObject = function (o) { this.RFonts.Ascii = o.RFonts.Ascii; this.RFonts.HAnsi = o.RFonts.HAnsi; };
CTextPr.prototype.Copy = function () { const c = new CTextPr(); c.Set_FromObject(this); return c; };
function ParaRun(par) { this.Pr = null; this.text = ''; }
ParaRun.prototype.Set_Pr = function (pr) { this.Pr = pr; };
ParaRun.prototype.AddText = function (t) { this.text += t; };
function ParaHyperlink() { this.Content = []; }
ParaHyperlink.prototype.SetValue = function () {};
ParaHyperlink.prototype.Add_ToContent = function (i, r) { this.Content.splice(i, 0, r); };

// reads one <a:r>: text attribute, then an rPr record whose a:sym is `sym`
function readRun(runText, latin, sym) {
	const ops = [0, g_nodeAttributeEnd, 0];
	const s = {
		cur: 0,
		GetULong() { return 10; },          // _end = 0 + 10 + 4
		Skip2() {}, Seek2(p) { this.cur = p; }, SkipRecord() { this.skipped = true; },
		GetUChar() { return ops.shift(); },
		GetString2() { return runText; },
	};
	const reader = {
		stream: s, IsUseFullUrl: false, RebuildImages: [],
		ReadTextFontTypeface() { return sym; },
		ReadRunProperties() {
			const rPr = new CTextPr();
			rPr.RFonts.Ascii = rPr.RFonts.HAnsi = { Name: latin, Index: -1 };
			this.RunSymFont = null;
			if (sym) {
				// the real a:sym record handling
				new Function('s', 'rPr', `switch (6) { ${symCase} }`).call(this, s, rPr);
			}
			s.cur = 14;
			return rPr;
		},
	};
	const par = { content: [], Internal_Content_Add(pos, item) { this.content.splice(pos, 0, item); } };
	new Function('s', 'par', 'EndPos', 'g_nodeAttributeEnd', 'ParaRun', 'CTextPr', 'ParaHyperlink', 'AscFormat', 'Asc', 'g_dKoef_emu_to_mm',
		helpers + `switch (1) { case 1: ${runCase.slice(runCase.indexOf('{'))} }`)
		.call(reader, s, par, 0, g_nodeAttributeEnd, ParaRun, CTextPr, ParaHyperlink, { PARRUN_TYPE_RUN: 1 }, { editor: {} }, 1);
	return par.content.map(r => ({ text: r.text, font: r.Pr && r.Pr.RFonts.Ascii && r.Pr.RFonts.Ascii.Name }));
}

let failures = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failures++; console.log('FAIL ' + label + '\n     ' + e.message.split('\n')[0]); }
}
const show = runs => JSON.stringify(runs.map(r => [r.text.replace(/[^\x20-\x7e]/g, c => '\\u' + c.charCodeAt(0).toString(16)), r.font]));

check('#344 slide 2: "\\uf0ac" with sym Symbol reads as the arrow U+2190 in the latin font', () => {
	const runs = readRun('', 'Arial', 'Symbol');
	assert.deepStrictEqual(runs, [{ text: '←', font: 'Arial' }], show(runs));
});
check('#328 lec5: "\\uf050 is (t, \\uf065)-" with sym Symbol reads as "Π is (t, ε)-"', () => {
	const runs = readRun(' is (t, )-', 'Calibri', 'Symbol');
	assert.deepStrictEqual(runs, [{ text: 'Π is (t, ε)-', font: 'Calibri' }], show(runs));
});
check('#328 lec5: approx-equal, element, double arrow, right arrow, Sigma', () => {
	const runs = readRun('', 'Calibri', 'Symbol');
	assert.strictEqual(runs[0].text, '≈∈⇔→Σ', show(runs));
});
check('a Symbol extension piece with no Unicode character (U+F0E6) is kept as it was', () => {
	const runs = readRun('', 'Arial', 'Symbol');
	assert.strictEqual(runs[0].text, '', show(runs));
});
check('#344 slide 1: "\\uf043  " with sym Wingdings 2: the symbol gets Wingdings 2, the spaces stay Arial', () => {
	const runs = readRun('  ', 'Arial', 'Wingdings 2');
	assert.deepStrictEqual(runs, [{ text: '', font: 'Wingdings 2' }, { text: '  ', font: 'Arial' }], show(runs));
});
check('text around a Wingdings symbol is cut into three runs, only the symbol in Wingdings', () => {
	const runs = readRun('a  b', 'Arial', 'Wingdings');
	assert.deepStrictEqual(runs, [{ text: 'a ', font: 'Arial' }, { text: '', font: 'Wingdings' }, { text: ' b', font: 'Arial' }], show(runs));
});
check('a run with a:sym but no symbol character is unchanged ("½ …" in lec5)', () => {
	const runs = readRun('any better than ½ ', 'Calibri', 'Wingdings');
	assert.deepStrictEqual(runs, [{ text: 'any better than ½ ', font: 'Calibri' }], show(runs));
});
check('a run without a:sym is unchanged (U+F0AC stays)', () => {
	const runs = readRun('', 'Arial', null);
	assert.deepStrictEqual(runs, [{ text: '', font: 'Arial' }], show(runs));
});

console.log(process.env.BASELINE ? `baseline sources (${BASE_REF})` : 'fixed sources');
if (failures) { console.log(`${failures} FAILED`); process.exit(1); }
console.log('ALL PASS');
