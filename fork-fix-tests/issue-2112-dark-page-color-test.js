/*
 * #2112 "Advanced Paste Options and True Black Dark Theme" - the true-black part:
 * "for the dark theme, please make the document page itself black".
 *
 * Before: the document dark mode page was a constant #3A3A3A
 * (word/api.js getPageBackgroundColor, "TODO: get color from theme") and
 * AscCommon.darkModeCorrectColor2 (common/Drawings/GraphicsBase.js) mapped
 * white to the matching constant lightness 58. No theme could change it.
 *
 * Now: the page colour is the skin colour PageBackgroundDark, filled from the
 * theme colour canvas-dark-content-background (common/skin.js colorMap), and
 * darkModeCorrectColor2 maps white to its lightness. web-apps sends the token
 * (Themes.js themeColorTokens) with #3a3a3a in the base colour table, so all
 * built-in themes are unchanged; a custom theme can set #000000.
 *
 * This loads the REAL common/skin.js and common/Drawings/GraphicsBase.js in a
 * vm, the REAL CColorModifiers RGB2HSL/HSL2RGB/Hue_2_RGB (brace-extracted from
 * common/Drawings/Format/Format.js, ClampColor from ColorArray.js) and the REAL word/api.js
 * getPageBackgroundColor, applies a theme with AscCommon.updateGlobalSkin as
 * asc_setSkin does, and checks page colour + recoloured white/black. The
 * web-apps part (token sent, default #3a3a3a) is checked by reading Themes.js
 * / colors-table.less when RD_WEBAPPS is set (default ../web-apps).
 *
 * NOT claimed: how the page looks on screen (needs a GUI check); PDF editor
 * dark mode (own constants) is unchanged; macOS has no local-theme import.
 *
 *   node fork-fix-tests/issue-2112-dark-page-color-test.js
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs)   RD_WEBAPPS=<web-apps> (default ../web-apps)
 *   BASELINE=1  reads BASE_REF (sdkjs) / WEBAPPS_BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
const BASE_REF = process.env.BASE_REF || '96dcdf31dd^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || 'fe6457de1f^';
const BASELINE = !!process.env.BASELINE;

function src(repo, ref, rel) {
	return BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
const sdk = (rel) => src(SDKJS, BASE_REF, rel);
function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}

function makeEditor() {
	const ctx = { window: {} };
	ctx.window.AscCommon = {};
	ctx.AscCommon = ctx.window.AscCommon;
	ctx.AscFormat = { CColorModifiers: function () {} };
	vm.createContext(ctx);
	const fmt = sdk('common/Drawings/Format/Format.js');
	const maxHls = /var max_hls = [0-9.]+;/.exec(fmt);
	assert.ok(maxHls, 'max_hls not found');
	vm.runInContext(maxHls[0], ctx);
	const clamp = extract(sdk('common/Drawings/ColorArray.js'), 'function dBoundColor(c)');
	vm.runInContext(clamp + '; AscFormat.ClampColor = dBoundColor;', ctx);
	for (const m of ['RGB2HSL', 'HSL2RGB', 'Hue_2_RGB']) {
		const s = extract(fmt, 'CColorModifiers.prototype.' + m + ' = function');
		assert.ok(s, m + ' not found');
		vm.runInContext('var CColorModifiers = AscFormat.CColorModifiers; ' + s + ';', ctx);
	}
	vm.runInContext(sdk('common/skin.js'), ctx);
	vm.runInContext(sdk('common/Drawings/GraphicsBase.js'), ctx);
	const pbc = extract(sdk('word/api.js'), 'asc_docs_api.prototype.getPageBackgroundColor = function');
	vm.runInContext('var asc_docs_api = function () {}; ' + pbc + '; var api = new asc_docs_api(); api.isDarkMode = true;', ctx);
	return ctx;
}
/* what asc_setSkin gets from web-apps: the token values of the theme (plus type/name) */
function applyTheme(ctx, colors) {
	ctx.AscCommon.updateGlobalSkin(Object.assign({ type: 'dark', name: 'theme-x' }, colors));
}
const page = (ctx) => { const c = ctx.api.getPageBackgroundColor(); return [c.R, c.G, c.B]; };
const recolor = (ctx, r, g, b) => { const c = ctx.AscCommon.darkModeCorrectColor2(r, g, b); return [c.R, c.G, c.B]; };

const cases = [
	['A. a theme with canvas-dark-content-background #000000 gives a black page', () => {
		const e = makeEditor();
		applyTheme(e, { 'canvas-dark-content-background': '#000000' });
		assert.deepStrictEqual(page(e), [0, 0, 0]);
	}],
	['B. ... and white on the page is recoloured to the page colour (black), black text to white', () => {
		const e = makeEditor();
		applyTheme(e, { 'canvas-dark-content-background': '#000000' });
		assert.deepStrictEqual(recolor(e, 255, 255, 255), [0, 0, 0]);
		assert.deepStrictEqual(recolor(e, 0, 0, 0), [255, 255, 255]);
	}],
	['C. switching back to a theme without the colour set restores #3A3A3A', () => {
		const e = makeEditor();
		applyTheme(e, { 'canvas-dark-content-background': '#000000' });
		applyTheme(e, { 'canvas-dark-content-background': '#3a3a3a' });
		assert.deepStrictEqual(page(e), [0x3a, 0x3a, 0x3a]);
		assert.deepStrictEqual(recolor(e, 255, 255, 255), [58, 58, 58]);
	}],
	/* unchanged behaviour */
	['D. built-in dark theme (#3a3a3a) / no token / garbage: page #3A3A3A, white -> 58 as before', () => {
		for (const colors of [{ 'canvas-dark-content-background': '#3a3a3a' }, {}, { 'canvas-dark-content-background': '' }]) {
			const e = makeEditor();
			applyTheme(e, colors);
			assert.deepStrictEqual(page(e), [0x3a, 0x3a, 0x3a]);
			assert.deepStrictEqual(recolor(e, 255, 255, 255), [58, 58, 58]);
			assert.deepStrictEqual(recolor(e, 0, 0, 0), [255, 255, 255]);
		}
	}],
	['E. light mode page stays white', () => {
		const e = makeEditor();
		applyTheme(e, { 'canvas-dark-content-background': '#000000' });
		e.api.isDarkMode = false;
		assert.deepStrictEqual(page(e), [255, 255, 255]);
	}],
];
if (fs.existsSync(path.join(WEBAPPS, '.git'))) {
	cases.push(['F. web-apps sends canvas-dark-content-background, default #3a3a3a', () => {
		const themes = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/common/main/lib/controller/Themes.js');
		const at = themes.indexOf('const themeColorTokens = [');
		const list = themes.slice(at, themes.indexOf('];', at));
		assert.ok(list.includes('"canvas-dark-content-background"'), 'token not sent to asc_setSkin');
		const less = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/common/main/resources/less/colors-table.less');
		assert.ok(/--canvas-dark-content-background:\s*#3a3a3a;/.test(less), 'default #3a3a3a not defined');
	}]);
}

let failed = 0;
for (const [name, fn] of cases) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failed++; console.log('FAIL ' + name + ' :: ' + e.message.split('\n').slice(0,8).join(' ')); }
}
if (failed) {
	console.log(`FAIL #2112: ${failed}/${cases.length} cases` + (BASELINE ? ' (BASELINE, expected)' : ''));
	process.exit(1);
}
console.log('PASS #2112: the dark-mode page colour follows the theme (black possible); built-in themes unchanged' + (BASELINE ? ' (BASELINE?!)' : ''));
