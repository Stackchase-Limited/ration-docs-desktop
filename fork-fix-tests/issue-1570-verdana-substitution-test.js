/*
 * #1570 - "Docx file opens with text in two pages instead of one". The reporter's
 * form (PT - Formulario GPDR.docx) is written entirely in Verdana 10pt. On a Linux
 * flatpak Verdana is not installed, so every line is re-measured against whatever
 * the substitution scorer picks - and it picked Open Sans, whose line box is
 * 1.36182em against Verdana's 1.21533em. Every line is 12.05% taller: 4.804mm
 * instead of 4.287mm at 10pt. Across the 35 lines of the closing table that is
 * +18.1mm, which is what pushes "Data: ____ Assinatura do Cliente:" onto page 2.
 *
 * common/libfont/map.js already carries the mechanism for this - the
 * FD_Ascii_Font_Like_Names groups, which is how Arial reaches Liberation Sans and
 * Cambria reaches Caladea. GetFaceNamePenalty_private charges 10000 for a name
 * that does not match and 999 for one in the requested font's group, so a group
 * entry is worth 9001 points and decides the pick outright. Verdana had no group.
 * It now names DejaVu Sans, which descends from Bitstream Vera and was drawn to
 * Verdana's proportions - and is what LibreOffice, the renderer in the report,
 * substitutes.
 *
 * This extracts the real GetFaceNamePenalty_private and the real CheckLikeFonts by
 * brace matching, and the real FD_Ascii_Font_Like_Names / FD_Ascii_Font_Like_Main
 * tables by bracket matching, all out of common/libfont/map.js, and scores real
 * candidate names through them. Nothing here is a transcription.
 *
 * It also checks the two halves that make the fix mean anything:
 *   - the converter's copy of the table (core's CFontListNamePicker) declares the
 *     same groups, or a document lays out one way on screen and another once it is
 *     rendered;
 *   - the substitute is metrically justified, measured from the hhea tables of the
 *     real font files in core-fonts.
 *
 * BASELINE=1 re-reads both files from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = path.join(ROOT, 'sdkjs');
const CORE = path.join(ROOT, 'core');
const MAP_REL = 'common/libfont/map.js';
const PICKER_REL = 'DesktopEditor/fontengine/ApplicationFonts.h';

// Pinned to the submodule heads this fix is built on - NOT HEAD, which carries the
// fix once it is committed and would leave the baseline passing while proving
// nothing. sdkjs and core are separate repositories and need separate SHAs: asking
// git for one repo's commit in the other fails in a way that looks exactly like a
// real baseline failure.
const BASE_REF_SDKJS = process.env.BASE_REF_SDKJS || 'ec823d0ce633e9c8a895ba0e0176a2d9eb097181';
const BASE_REF_CORE = process.env.BASE_REF_CORE || 'af68137e075d3169e24d93590f3844290a9605ef';

function read(repo, rel, ref) {
	if (!process.env.BASELINE) return fs.readFileSync(path.join(repo, rel), 'utf8');
	return execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 });
}

const source = read(SDKJS, MAP_REL, BASE_REF_SDKJS);
const picker = read(CORE, PICKER_REL, BASE_REF_CORE);

/* --- bracket matching, for both {...} and [...] --- */
function matched(text, from, open) {
	const close = open === '{' ? '}' : ']';
	const start = text.indexOf(open, from);
	assert.notStrictEqual(start, -1, 'no ' + open + ' after offset ' + from);
	let depth = 0;
	let inStr = null;
	for (let i = start; i < text.length; i++) {
		const c = text[i];
		if (inStr) {
			if (c === '\\') i++;
			else if (c === inStr) inStr = null;
			continue;
		}
		if (c === '"' || c === "'") { inStr = c; continue; }
		if (c === '/' && text[i + 1] === '/') { i = text.indexOf('\n', i); if (i === -1) break; continue; }
		if (c === open) depth++;
		else if (c === close && --depth === 0) return text.slice(start, i + 1);
	}
	throw new Error('unbalanced ' + open);
}

function literal(marker, open) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found in ' + MAP_REL);
	return new Function('"use strict"; return ' + matched(source, at + marker.length, open))();
}

function method(name) {
	const marker = name + ' : function';
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, name + ' not found in ' + MAP_REL);
	// keep the argument list: rebuild "function(args){body}" from the real text
	const parenAt = source.indexOf('(', at + marker.length - 1);
	const args = source.slice(parenAt, source.indexOf(')', parenAt) + 1);
	return { args, body: matched(source, parenAt, '{') };
}

/* --- the real tables --- */
const FD_Ascii_Font_Like_Names = literal('this.FD_Ascii_Font_Like_Names =', '[');
const FD_Ascii_Font_Like_Main = literal('this.FD_Ascii_Font_Like_Main =', '{');
assert.ok(Array.isArray(FD_Ascii_Font_Like_Names) && FD_Ascii_Font_Like_Names.length >= 7,
	'extracted the wrong thing for FD_Ascii_Font_Like_Names');

/* --- the real CheckLikeFonts, bound to the real tables --- */
const clf = method('CheckLikeFonts');
const CheckLikeFonts = new Function(
	'FD_Ascii_Font_Like_Main', 'FD_Ascii_Font_Like_Names',
	'"use strict"; const self = { FD_Ascii_Font_Like_Main, FD_Ascii_Font_Like_Names };\n' +
	'return function' + clf.args + ' { return (function' + clf.args + clf.body + ').apply(self, arguments); };'
)(FD_Ascii_Font_Like_Main, FD_Ascii_Font_Like_Names);
assert.strictEqual(CheckLikeFonts('Liberation Sans', 'Arial'), true,
	'extracted CheckLikeFonts does not behave like CheckLikeFonts');

/* --- the real GetFaceNamePenalty_private, with CheckLikeFonts reachable where it
 *     really looks for it: g_fontApplication.g_fontDictionary --- */
const gfp = method('GetFaceNamePenalty_private');
const namePenalty = new Function(
	'g_fontApplication',
	'"use strict"; return function' + gfp.args + gfp.body + ';'
)({ g_fontDictionary: { CheckLikeFonts } });
assert.strictEqual(namePenalty('Arial', 'Arial'), 0, 'an exact name must cost nothing');

/* the scorer is called as GetFaceNamePenalty_private(requested, candidate) */
const score = (requested, candidate) => namePenalty(requested, candidate);

/* --- 0. the premise: a group entry is what decides a substitution --- */
{
	assert.strictEqual(score('Arial', 'Liberation Sans'), 999,
		'a font in the requested font\'s group must be cheap');
	assert.strictEqual(score('Arial', 'Caladea'), 10000,
		'a font outside the group must cost the full mismatch');
	assert.ok(10000 - 999 > 1000,
		'the group discount must outweigh the panose spread between sans faces, ' +
		'or naming a substitute would not actually change the pick');
}

/* --- 1. the defect: Verdana must reach DejaVu Sans, and beat Open Sans --- */
{
	const dejavu = score('Verdana', 'DejaVu Sans');
	const opensans = score('Verdana', 'Open Sans');

	assert.strictEqual(dejavu, 999,
		'Verdana must name a substitute, or the scorer falls back on panose and ' +
		'picks Open Sans - 12% taller per line, which is #1570 (cost was ' + dejavu + ')');

	assert.ok(dejavu < opensans,
		'DejaVu Sans must be strictly cheaper than Open Sans for a Verdana request ' +
		'(' + dejavu + ' vs ' + opensans + ')');

	assert.strictEqual(score('DejaVu Sans', 'Verdana'), 999,
		'the pairing must hold both ways, as every other group does');
}

/* --- 2. no other request changed --- */
{
	const unchanged = [
		['Arial', 'Liberation Sans', 999], ['Arial', 'Helvetica', 999], ['Arial', 'Nimbus Sans L', 999],
		['Times New Roman', 'Liberation Serif', 999],
		['Courier New', 'Liberation Mono', 999],
		['Cambria', 'Caladea', 999],
		['Cambria Math', 'Asana Math', 999], ['Cambria Math', 'XITS Math', 999],
		// "Symbol" is a substring of "OpenSymbol", so that pair takes the
		// one-name-inside-the-other branch and costs 700, not 999
		['Symbol', 'OpenSymbol', 700], ['Wingdings', 'OpenSymbol', 999],
		// and requests that must stay at the full mismatch
		['Tahoma', 'DejaVu Sans', 10000],
		['Georgia', 'DejaVu Sans', 10000],
		['Calibri', 'DejaVu Sans', 10000],
		['Arial', 'DejaVu Sans', 10000],
		['Verdana', 'Liberation Sans', 10000],
		['Verdana', 'Carlito', 10000]
	];
	for (const [req, cand, want] of unchanged) {
		assert.strictEqual(score(req, cand), want,
			'"' + req + '" -> "' + cand + '" must still cost ' + want);
	}
	assert.strictEqual(score('Verdana', 'Verdana'), 0,
		'when Verdana is installed the exact name still wins outright, so the ' +
		'group must not disturb a machine that has the font');
}

/* --- 3. the converter must carry the same groups ---
 * The editor scores substitutions in JS and x2t scores them in
 * core/DesktopEditor/fontengine/ApplicationFonts.h. If the two tables drift, a
 * document lays out one way on screen and another once it is rendered. */
{
	const at = picker.indexOf('class CFontListNamePicker');
	assert.notStrictEqual(at, -1, 'CFontListNamePicker not found in ' + PICKER_REL);
	const body = matched(picker, at, '{');

	// every group the JS table declares, the C++ table must declare too
	const groups = new Map(); // vector name -> [font names]
	for (const m of body.matchAll(/\bar(\d+)\.push_back\(L"([^"]+)"\)/g)) {
		if (!groups.has(m[1])) groups.set(m[1], []);
		groups.get(m[1]).push(m[2]);
	}
	const cppGroups = [...groups.values()].map(g => g.slice().sort().join('|'));
	const cppIndex = new Map();
	for (const m of body.matchAll(/m_mapNamesToIndex\.insert\(std::pair<std::wstring, int>\(L"([^"]+)", (\d+)\)\)/g))
		cppIndex.set(m[1], m[2]);

	const verdanaGroup = ['Verdana', 'DejaVu Sans'].sort().join('|');
	assert.ok(cppGroups.includes(verdanaGroup),
		'core\'s CFontListNamePicker must list the same Verdana group as ' + MAP_REL +
		', or the converter keeps substituting Open Sans and renders a different ' +
		'number of pages than the editor shows');
	assert.strictEqual(cppIndex.get('Verdana'), cppIndex.get('DejaVu Sans'),
		'both names must map to that group, as both do on the JS side');

	// and the groups that were already there must still be there
	for (const pair of [['Arial', 'Liberation Sans'], ['Times New Roman', 'Liberation Serif'],
		['Courier New', 'Liberation Mono'], ['Cambria', 'Caladea']]) {
		assert.strictEqual(cppIndex.get(pair[0]), cppIndex.get(pair[1]),
			pair.join(' / ') + ' must still share a group in ' + PICKER_REL);
	}
}

/* --- 4. the substitute is metrically justified, from the real font files ---
 * A line box is (ascender - descender + lineGap) / unitsPerEm. This is the
 * quantity that decides where the page breaks, so it is the quantity the choice of
 * substitute has to answer to. */
{
	function lineBox(file) {
		const buf = fs.readFileSync(file);
		const numTables = buf.readUInt16BE(4);
		const off = {};
		for (let i = 0; i < numTables; i++) {
			const rec = 12 + i * 16;
			off[buf.toString('latin1', rec, rec + 4)] = buf.readUInt32BE(rec + 8);
		}
		assert.ok(off.head && off.hhea, 'no head/hhea in ' + file);
		const upem = buf.readUInt16BE(off.head + 18);
		const asc = buf.readInt16BE(off.hhea + 4);
		const desc = buf.readInt16BE(off.hhea + 6);
		const gap = buf.readInt16BE(off.hhea + 8);
		return (asc - desc + gap) / upem;
	}

	const dejavu = lineBox(path.join(ROOT, 'core-fonts/dejavu/DejaVuSans.ttf'));
	const opensans = lineBox(path.join(ROOT, 'core-fonts/opensans/OpenSans-Regular.ttf'));

	// Verdana is proprietary and not in the tree; measure it when the machine has it
	const VERDANA = '/System/Library/Fonts/Supplemental/Verdana.ttf';
	const verdana = fs.existsSync(VERDANA) ? lineBox(VERDANA) : 2489 / 2048; // hhea 2059/-430/0

	const dDejavu = Math.abs(dejavu - verdana) / verdana;
	const dOpensans = Math.abs(opensans - verdana) / verdana;

	assert.ok(dDejavu < dOpensans,
		'DejaVu Sans must sit closer to Verdana\'s line box than Open Sans does, ' +
		'or the substitution is no better than the one it replaces (DejaVu ' +
		(dDejavu * 100).toFixed(2) + '%, Open Sans ' + (dOpensans * 100).toFixed(2) + '%)');

	assert.ok(dOpensans > 0.1,
		'Open Sans was more than 10% off Verdana - if that ever stops being true ' +
		'the premise of this fix has changed and it should be re-examined (was ' +
		(dOpensans * 100).toFixed(2) + '%)');

	assert.ok(dDejavu < 0.05,
		'the named substitute must be within 5% of Verdana\'s line box (was ' +
		(dDejavu * 100).toFixed(2) + '%)');
}

console.log('ok - Verdana substitutes to DejaVu Sans in both the editor and the converter');
