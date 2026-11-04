/*
 * #2455 - a gradient imported from PowerPoint with a different transparency on
 * each stop lost those transparencies as soon as the user changed any stop's
 * color or position in the fill panel: every stop became opaque (and the
 * whole-gradient slider could then only give them one shared value).
 *
 * Each stop's transparency is an "alpha" modifier on the stop's color. The panel
 * (web-apps ShapeSettings onColorsGradientSelect/_gradientApplyFunc) sends the
 * stops back as plain asc_CColor values, and CorrectUniFill (Format.js) rebuilt
 * every stop through CorrectUniColor, which clears all modifiers.
 *
 * This extracts the real CorrectUniFill and CorrectUniColor, the real color
 * modifier methods (CColorMod, CColorModifiers.getModValue/getMod/addMod,
 * CUniColor.setMods/getModValue/getMod/checkWordMods/convertToPPTXMods) and, on
 * the fixed tree, GetGradAlphaAtPos/SetGradStopAlpha, and replays what the panel
 * sends for: moving a stop, recoloring a stop, adding a stop and removing one.
 *
 * NOT claimed: the panel itself (it still has no per-stop transparency control;
 * that part of the report is a feature request), rendering, and pptx save are
 * not exercised.
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
const BASE_REF = process.env.BASE_REF || '23b782f0a4^';
const REL = 'common/Drawings/Format/Format.js';

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

function extract(marker, optional) {
	const at = source.indexOf(marker);
	if (at === -1 && optional) return '';
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at) + ';\n';
}

/* --- stubs for what the extracted code only constructs or compares --- */
const c_oAscColor = { COLOR_TYPE_NONE: 0, COLOR_TYPE_SRGB: 1, COLOR_TYPE_PRST: 2, COLOR_TYPE_SCHEME: 3 };
const c_oAscFill = { FILL_TYPE_NONE: 0, FILL_TYPE_BLIP: 1, FILL_TYPE_NOFILL: 2, FILL_TYPE_SOLID: 3, FILL_TYPE_GRAD: 4, FILL_TYPE_PATT: 5, FILL_TYPE_GRP: 6 };
const c_oAscFillGradType = { GRAD_LINEAR: 1, GRAD_PATH: 2 };
const isRealNumber = (n) => typeof n === 'number' && !isNaN(n);
function CRGBColor() { this.type = c_oAscColor.COLOR_TYPE_SRGB; this.RGBA = { R: 0, G: 0, B: 0, A: 255 }; }
function CUniColor() { this.color = null; this.Mods = null; this.RGBA = { R: 0, G: 0, B: 0, A: 255 }; }
function CGs() { this.color = null; this.pos = 0; }
function CGradFill() { this.type = c_oAscFill.FILL_TYPE_GRAD; this.colors = []; this.lin = null; this.path = null; }
function CUniFill() { this.fill = null; this.transparent = null; }
function GradLin() { this.angle = 0; this.scale = false; }
function GradPath() {}

const names = ['c_oAscColor', 'c_oAscFill', 'c_oAscFillGradType', 'isRealNumber', 'CRGBColor', 'CUniColor', 'CGs',
	'CGradFill', 'CUniFill', 'GradLin', 'GradPath', 'AscFormat', 'editor'];
const body =
	extract('function CColorMod(') +
	extract('function CColorModifiers()') +
	extract('CColorModifiers.prototype.getModValue = function') +
	extract('CColorModifiers.prototype.getMod = function') +
	extract('CColorModifiers.prototype.addMod = function') +
	extract('CUniColor.prototype.setMods = function') +
	extract('CUniColor.prototype.getModValue = function') +
	extract('CUniColor.prototype.getMod = function') +
	extract('CUniColor.prototype.checkWordMods = function') +
	extract('CUniColor.prototype.convertToPPTXMods = function') +
	extract('function GetGradAlphaAtPos(', true) +
	extract('function SetGradStopAlpha(', true) +
	extract('function CorrectUniColor(') +
	extract('function CorrectUniFill(') +
	'return {CorrectUniFill, CColorMod, CColorModifiers};';
const AscFormat = { isRealNumber };
const api = new Function(...names, body)(c_oAscColor, c_oAscFill, c_oAscFillGradType, isRealNumber, CRGBColor,
	CUniColor, CGs, CGradFill, CUniFill, GradLin, GradPath, AscFormat, undefined);
AscFormat.CColorMod = api.CColorMod;

/* --- a gradient as read from the reporter-style pptx: stops with their own alpha --- */
function stop(hex, pos, alpha) {
	const gs = new CGs();
	gs.pos = pos;
	gs.color = new CUniColor();
	gs.color.color = new CRGBColor();
	gs.color.color.RGBA = { R: parseInt(hex.slice(0, 2), 16), G: parseInt(hex.slice(2, 4), 16), B: parseInt(hex.slice(4, 6), 16), A: 255 };
	gs.color.Mods = new api.CColorModifiers();
	if (alpha !== null) gs.color.Mods.addMod('alpha', alpha);
	return gs;
}
function brush(stops) {
	const u = new CUniFill();
	u.fill = new CGradFill();
	u.fill.lin = new GradLin();
	u.fill.colors = stops;
	return u;
}
/* what the panel sends: plain colors (Common.Utils.ThemeColor.getRgbColor -> asc_CColor, a = 255) */
function ascColor(hex) {
	return { r: parseInt(hex.slice(0, 2), 16), g: parseInt(hex.slice(2, 4), 16), b: parseInt(hex.slice(4, 6), 16), a: 255,
		asc_getType: () => c_oAscColor.COLOR_TYPE_SRGB };
}
function ascGrad(hexes, positions) {
	const f = { Colors: hexes ? hexes.map(ascColor) : undefined, Positions: positions, GradType: c_oAscFillGradType.GRAD_LINEAR,
		LinearAngle: 0, LinearScale: true };
	return { type: c_oAscFill.FILL_TYPE_GRAD, fill: f, transparent: undefined };
}
const alphas = (u) => u.fill.colors.map((gs) => gs.color.getModValue('alpha'));
const original = () => brush([stop('ff0000', 0, null), stop('00ff00', 50000, 30000), stop('0000ff', 100000, 70000)]);

/* 1. drag the middle stop (_gradientApplyFunc: positions + colors) */
let u = api.CorrectUniFill(ascGrad(['ff0000', '00ff00', '0000ff'], [0, 60000, 100000]), original());
console.log('move stop    ->', JSON.stringify(alphas(u)));
assert.deepStrictEqual(alphas(u), [null, 30000, 70000], 'moving one stop must not strip the stops\' own alpha');
assert.strictEqual(u.fill.colors[1].pos, 60000);

/* 2. recolor the first stop (onColorsGradientSelect on a gradient: colors only) */
u = api.CorrectUniFill(ascGrad(['ffff00', '00ff00', '0000ff'], undefined), original());
console.log('recolor stop ->', JSON.stringify(alphas(u)));
assert.deepStrictEqual(alphas(u), [null, 30000, 70000], 'recoloring one stop must not strip the others\' alpha');
assert.strictEqual(u.fill.colors[0].color.color.RGBA.G, 255);

/* 3. add a stop at 75% -> kept stops keep theirs, the new one is interpolated */
u = api.CorrectUniFill(ascGrad(['ff0000', '00ff00', '00ffff', '0000ff'], [0, 50000, 75000, 100000]), original());
console.log('add stop     ->', JSON.stringify(alphas(u)));
assert.deepStrictEqual(alphas(u), [null, 30000, 50000, 70000]);

/* 4. remove the middle stop */
u = api.CorrectUniFill(ascGrad(['ff0000', '0000ff'], [0, 100000]), original());
console.log('remove stop  ->', JSON.stringify(alphas(u)));
assert.deepStrictEqual(alphas(u), [null, 70000]);

/* 5. an opaque gradient gets no alpha modifiers */
u = api.CorrectUniFill(ascGrad(['ff0000', '00ff00', '0000ff'], [0, 40000, 100000]),
	brush([stop('ff0000', 0, null), stop('00ff00', 50000, null), stop('0000ff', 100000, null)]));
assert.deepStrictEqual(alphas(u), [null, null, null]);
u = api.CorrectUniFill(ascGrad(['ff0000', '777777', '00ff00', '0000ff'], [0, 20000, 50000, 100000]),
	brush([stop('ff0000', 0, null), stop('00ff00', 50000, null), stop('0000ff', 100000, null)]));
assert.deepStrictEqual(alphas(u), [null, null, null, null]);

console.log('PASS #2455: per-stop gradient alpha survives stop edits' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
