/*
 * #2318 - "Some fonts are not properly rendered on Linux". The reporter's form
 * (Formulaire conflit interet Cos-2026.docx) opens a boxed paragraph with a
 * Wingdings run U+F0E8 U+F020 - a heavy right arrow and a space. Office draws
 * the arrow; on Linux we drew a circled P.
 *
 * Wingdings is not installed on Linux, so the picker substitutes OpenSymbol,
 * which ONLYOFFICE bundles (core-fonts/openoffice). OpenSymbol has none of the
 * U+F0xx codes Word stores for Wingdings; it carries the Wingdings set in its own
 * private-use area (U+E400...). common/libfont/map.js has the recode table for
 * that (ChangeGlyphsMap), but it held ten bullets. U+F0E8 missed it, so the
 * shaper went to the by-character fallback: with no font carrying U+F0E8 it is
 * drawn blank (reproduced with x2t and a Linux font set), and where some other
 * installed font carries that private-use code it draws that font's glyph.
 *
 * A second cause sits in the shaper: CTextShaper.private_CheckNewSegment applied
 * the remap only on the GetFontBySymbol branch, i.e. to the first code of a
 * segment. Later codes passed CheckUnicodeInCurrentFont (which tests the remapped
 * code) and were then shaped raw, so "U+F06C U+F0A7" showed only the bullet.
 *
 * This extracts by brace matching the real ChangeGlyphsMap, GetReplaceGlyph and
 * CheckReplaceGlyphsMap (map.js), the real CheckUnicodeInCurrentFont and
 * GetFontBySymbol (textmeasurer.js) and the real private_CheckNewSegment
 * (textshaper.js), and runs them against the cmap and outlines read from the real
 * OpenSymbol file in core-fonts. Nothing here transcribes the table or the logic.
 *
 * Claimed: the reporter's codes and every code in the table reach a glyph with
 * an outline in the shipped OpenSymbol, and every code of a Wingdings run - not
 * only the first - is shaped as its remapped value.
 * NOT claimed: that each OpenSymbol glyph looks like its Wingdings original (that
 * was checked by eye, rendering both side by side, when the table was built), or
 * anything about systems where Wingdings is substituted by a font other than
 * OpenSymbol. The MS Gothic box-spacing difference in the same report is a
 * metric substitution, not this bug, and is not touched.
 *
 * RD_REPO overrides the sdkjs checkout, RD_OPENSYMBOL the font file.
 * BASELINE=1 reads the sources from git at BASE_REF and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const FONT = process.env.RD_OPENSYMBOL || path.join(ROOT, 'core-fonts', 'openoffice', 'opens___.ttf');
// Pinned to the parent of the fix commit, never HEAD: HEAD carries the fix.
const BASE_REF = process.env.BASE_REF || '0f18391e82^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* --- bracket matching that skips strings and // comments --- */
function matched(text, from) {
	const start = text.indexOf('{', from);
	let depth = 0, inStr = null;
	for (let i = start; i < text.length; i++) {
		const c = text[i];
		if (inStr) {
			if (c === '\\') i++;
			else if (c === inStr) inStr = null;
			continue;
		}
		if (c === '"' || c === "'") { inStr = c; continue; }
		if (c === '/' && text[i + 1] === '/') { i = text.indexOf('\n', i); continue; }
		if (c === '{') depth++;
		else if (c === '}' && --depth === 0) return text.slice(start, i + 1);
	}
	throw new Error('unbalanced braces');
}
function after(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return at + marker.length;
}
/* "name = function(args) {...}" or "name : function(args) {...}" -> function source */
function fn(text, marker) {
	const at = after(text, marker);
	const head = text.slice(at, text.indexOf('{', at));
	return head.trim() + ' ' + matched(text, at);
}

/* --- the real OpenSymbol: cmap (3,1) format 4 and glyph outlines --- */
const ttf = fs.readFileSync(FONT);
const tables = {};
for (let i = 0, n = ttf.readUInt16BE(4); i < n; i++) {
	const r = 12 + 16 * i;
	tables[ttf.toString('latin1', r, r + 4)] = { off: ttf.readUInt32BE(r + 8), len: ttf.readUInt32BE(r + 12) };
}
const cmap = new Map();
{
	const c = tables.cmap.off;
	let sub = -1;
	for (let i = 0, n = ttf.readUInt16BE(c + 2); i < n; i++) {
		const r = c + 4 + 8 * i;
		if (ttf.readUInt16BE(r) === 3 && ttf.readUInt16BE(r + 2) === 1) sub = c + ttf.readUInt32BE(r + 4);
	}
	assert.notStrictEqual(sub, -1, 'OpenSymbol has no (3,1) cmap');
	assert.strictEqual(ttf.readUInt16BE(sub), 4);
	const segX2 = ttf.readUInt16BE(sub + 6);
	const ends = sub + 14, starts = ends + segX2 + 2, deltas = starts + segX2, ranges = deltas + segX2;
	for (let s = 0; s < segX2; s += 2) {
		const end = ttf.readUInt16BE(ends + s), start = ttf.readUInt16BE(starts + s);
		const delta = ttf.readInt16BE(deltas + s), ro = ttf.readUInt16BE(ranges + s);
		for (let u = start; u <= end && u !== 0xFFFF; u++) {
			let g;
			if (ro === 0) g = (u + delta) & 0xFFFF;
			else {
				g = ttf.readUInt16BE(ranges + s + ro + 2 * (u - start));
				if (g) g = (g + delta) & 0xFFFF;
			}
			if (g) cmap.set(u, g);
		}
	}
}
const longLoca = ttf.readInt16BE(tables.head.off + 50) === 1;
function glyphBytes(g) {
	const l = tables.loca.off;
	return longLoca ? ttf.readUInt32BE(l + 4 * (g + 1)) - ttf.readUInt32BE(l + 4 * g)
		: 2 * (ttf.readUInt16BE(l + 2 * (g + 1)) - ttf.readUInt16BE(l + 2 * g));
}
const inked = (u) => cmap.has(u) && glyphBytes(cmap.get(u)) > 0;
assert.ok(inked(0xE4AE) && !cmap.has(0xF0E8), 'font sanity: OpenSymbol has U+E4AE and no U+F0E8');

/* --- the real recode table and its two functions (map.js) --- */
const map = src('common/libfont/map.js');
const ChangeGlyphsMap = new Function('return ' + matched(map, after(map, 'this.ChangeGlyphsMap =')) + ';')();
const app = new Function(
	'var o = {};' +
	'o.g_fontDictionary = { ChangeGlyphsMap: arguments[0] };' +
	'o.CheckReplaceGlyphsMap = ' + fn(map, 'this.CheckReplaceGlyphsMap =') + ';' +
	'o.GetReplaceGlyph = ' + fn(map, 'this.GetReplaceGlyph =') + ';' +
	'return o;')(ChangeGlyphsMap);
const replace = app.CheckReplaceGlyphsMap('Wingdings', { Name: 'OpenSymbol' });
assert.ok(replace, 'no Wingdings -> OpenSymbol entry');

/* 1. the reporter's run, and the document's Wingdings bullet (U+F0A7) */
const failures = [];
for (const [u, what] of [[0xF0E8, 'arrow U+F0E8'], [0xF020, 'space U+F020'], [0xF0A7, 'bullet U+F0A7']]) {
	const to = app.GetReplaceGlyph(u, replace);
	if (!cmap.has(to)) failures.push(`${what} -> U+${to.toString(16).toUpperCase()}, not in OpenSymbol`);
}
assert.deepStrictEqual(failures, [], 'reporter codes do not reach OpenSymbol:\n  ' + failures.join('\n  '));
assert.strictEqual(app.GetReplaceGlyph(0xF0E8, replace), app.GetReplaceGlyph(0xE8, replace),
	'raw 0xE8 in a Wingdings run is the same arrow');

/* 2. the table against the real font: every target has an outline (the space excepted) */
const blanks = replace.MapDst.filter((d) => d !== 0x20 && !inked(d)).map((d) => d.toString(16));
assert.deepStrictEqual(blanks, [], 'table targets with no outline in OpenSymbol');
assert.strictEqual(replace.MapSrc.length, replace.MapDst.length);
assert.strictEqual(new Set(replace.MapSrc).size, replace.MapSrc.length, 'duplicate source code');

/* 3. the shaper: every code of a Wingdings run is shaped remapped, not only the first */
const tm = src('common/libfont/textmeasurer.js');
const shaperSrc = src('common/libfont/textshaper.js');
const g_fontApplication = app;
const openSymbol = {
	GetGIDByUnicode: (u) => cmap.get(u) || 0,
	Picker: { GetFontBySymbolWithSize: () => null }, // no other font carries U+F0xx
};
const measurer = new Function('g_fontApplication',
	'return {' +
	'CheckUnicodeInCurrentFont : ' + fn(tm, 'CheckUnicodeInCurrentFont :') + ',' +
	'GetFontBySymbol : ' + fn(tm, 'GetFontBySymbol :') + '};')(g_fontApplication);
measurer.m_oManager = { m_pFont: openSymbol };
measurer.LastFontOriginInfo = { Name: 'OpenSymbol', Replace: replace }; // as LoadFont("Wingdings") leaves it
measurer.GetCurrentFont = () => openSymbol;

const AscFonts = { HB_STRING_MAX_LEN: 1024, HB_SCRIPT: { HB_SCRIPT_INHERITED: 1 }, g_fontApplication: app };
const AscCommon = { g_oTextMeasurer: measurer };
const AscWord = { fontslot_None: -1 };
const checkNewSegment = new Function('AscFonts', 'AscCommon', 'AscWord',
	'return ' + fn(shaperSrc, 'CTextShaper.prototype.private_CheckNewSegment =') + ';')(AscFonts, AscCommon, AscWord);

const shaper = {
	Buffer: [], Script: -1, FontId: -1, FontSubst: false, FontSlot: -1,
	FlushWord() { this.Buffer.length = 0; this.Script = -1; this.FontId = -1; },
	GetTextScript: () => 0, GetDirection: () => 0, GetFontSlot: () => 0, private_CheckFont() {},
	private_CheckBufferInFont: () => true,
	private_CheckNewSegment: checkNewSegment,
};
const run = [0xF06C, 0xF0A7, 0xF0E8, 0xF020];
const shaped = run.map((u) => { const c = shaper.private_CheckNewSegment(u); shaper.Buffer.push(u); return c; });
const raw = shaped.map((c, i) => [run[i], c]).filter(([, c]) => !cmap.has(c))
	.map(([u, c]) => `U+${u.toString(16).toUpperCase()} shaped as U+${c.toString(16).toUpperCase()}`);
assert.deepStrictEqual(raw, [], 'codes shaped with a value OpenSymbol does not have (drawn blank):\n  ' + raw.join('\n  '));

console.log('PASS #2318: Wingdings run U+F06C U+F0A7 U+F0E8 U+F020 shapes as ' +
	shaped.map((c) => 'U+' + c.toString(16).toUpperCase()).join(' ') +
	` in OpenSymbol; ${replace.MapSrc.length} table codes all have outlines` + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
