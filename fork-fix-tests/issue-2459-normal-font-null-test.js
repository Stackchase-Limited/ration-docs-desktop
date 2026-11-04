/*
 * #2459 - "Onlyoffice crashes while editing the file": after pasting a table in
 * the spreadsheet editor the desktop showed "An error occurred while working
 * with the document. Use Save as..." and the document could not be edited.
 *
 * One way to get exactly that, found while reproducing the report headless
 * (real cell sdk in Chromium, stubbed desktop host): paste a styled table with
 * a totals row into a workbook that was opened without a styles part. That
 * workbook never reaches StyleManager.init, so g_StyleCache.normalXf stays the
 * empty CellXfs made by the StyleCache constructor (font null). CellXfs.merge
 * calls Font.isNormalXfColor for every table-styled cell font, and it read
 * g_StyleCache.normalXf.font.c -> TypeError on every redraw of the range ->
 * window.onerror -> EditingError.
 *
 * This extracts the real Font.prototype.isNormalXfColor and the real
 * ColorManager prototype (both cell/model/WorkbookElems.js) and calls it in
 * the state such a workbook leaves behind, plus the normal state.
 *
 * NOT claimed: that this is the reporter's trigger (their file never reached
 * the issue; their target workbook was a new ONLYOFFICE file, which has a
 * styles part). Rendering and the paste itself are not exercised here.
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
const BASE_REF = process.env.BASE_REF || '46a524f72c^';
const REL = 'cell/model/WorkbookElems.js';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

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

function extract(marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at) + ';\n';
}

/* --- stubs for what the extracted code only compares --- */
function RgbColor(rgb) { this.rgb = rgb; }
RgbColor.prototype.getRgb = function () { return this.rgb; };
function ThemeColor(rgb) { this.rgb = rgb; }
ThemeColor.prototype.getRgb = function () { return this.rgb; };
function Font(c) { this.c = c; }

const env = new Function('RgbColor', 'ThemeColor', 'Font', 'g_StyleCache', 'g_oDefaultFormat',
	'function ColorManager() {}\n' +
	extract('ColorManager.prototype =') +
	'var g_oColorManager = new ColorManager();\n' +
	extract('Font.prototype.isNormalXfColor = function') +
	'return { set: function (sc, df) { g_StyleCache = sc; g_oDefaultFormat = df; } };');

let api = env(RgbColor, ThemeColor, Font, null, null);

/* 1. a workbook opened without a styles part: normalXf exists but has no font,
      and the default font was never set either. */
api.set({ normalXf: { font: null } }, { Font: null });
const headerFont = new Font(new ThemeColor(0xFFFFFF)); // table header: white text
let res;
assert.doesNotThrow(() => { res = headerFont.isNormalXfColor(); },
	'isNormalXfColor threw for a workbook without a Normal font: the editor dies on paste');
assert.strictEqual(res, false, 'a colored font is not the (automatic) Normal color');
assert.strictEqual(new Font(null).isNormalXfColor(), true, 'automatic color equals an automatic Normal color');

/* 2. same, but the default font is known: compare with it. */
api.set({ normalXf: { font: null } }, { Font: new Font(new ThemeColor(0x000000)) });
assert.strictEqual(new Font(new ThemeColor(0x000000)).isNormalXfColor(), true);
assert.strictEqual(headerFont.isNormalXfColor(), false);

/* 3. the ordinary case is unchanged: Normal font color decides. */
api.set({ normalXf: { font: new Font(new ThemeColor(0x111111)) } }, { Font: new Font(new ThemeColor(0x000000)) });
assert.strictEqual(new Font(new ThemeColor(0x111111)).isNormalXfColor(), true);
assert.strictEqual(new Font(new ThemeColor(0x000000)).isNormalXfColor(), false);

console.log('PASS #2459: table font color check survives a workbook without a Normal font' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
