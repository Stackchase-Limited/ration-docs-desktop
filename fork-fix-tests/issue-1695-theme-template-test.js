/*
 * #1695 "Template for custom themes?" - theme authors have no list of the keys
 * a desktop theme file takes, and the examples in web-apps did not work.
 *
 * Before: apps/common/main/resources/themes/full-theme-dark.json.example - the
 * full example to copy - was not valid JSON ("canvas-high-contrast": "#fff",,)
 * so a theme made from it was refused on Windows/Linux ("This theme file is
 * not valid") and ignored by the editors. Both full examples listed 86-87 of
 * the 141 colour tokens the editors read (Themes.js themeColorTokens) and three
 * tokens nothing reads any more (canvas-cell-title*).
 *
 * Now both full examples are valid JSON and list every colour token in
 * themeColorTokens (all but the two non-colour entries toolbar-height-controls
 * and sprite-button-icons-uid), and only tokens the colour tables define.
 *
 * This reads the REAL example files, the REAL themeColorTokens list (Themes.js)
 * and the token names of the REAL colour table (colors-table.less), parses
 * every *.json.example with JSON.parse, and runs the REAL create_colors_css
 * (brace-extracted from Themes.js) on each full example to check the CSS the
 * editors inject carries every token.
 *
 * NOT claimed: how a theme looks (needs a GUI check); macOS has no "Add theme"
 * (a custom theme can't be loaded there); the desktop's own validateTheme
 * (cthemes.cpp) is not run - it is a Qt JSON parse plus an id/key character
 * check, which these files pass.
 *
 *   node fork-fix-tests/issue-1695-theme-template-test.js
 *   RD_REPO=<web-apps checkout> (default ../web-apps)   BASELINE=1 reads BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
const BASE_REF = process.env.BASE_REF || 'c1f5d70991^';
const BASELINE = !!process.env.BASELINE;
const THEMES = 'apps/common/main/resources/themes';

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}
function list(rel) {
	return BASELINE
		? execFileSync('git', ['-C', REPO, 'ls-tree', '--name-only', `${BASE_REF}:${rel}`], { encoding: 'utf8' }).split('\n').filter(Boolean)
		: fs.readdirSync(path.join(REPO, rel));
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) throw new Error('not found: ' + marker);
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

const themesJs = src('apps/common/main/lib/controller/Themes.js');
const tokens = JSON.parse('[' + /const themeColorTokens = \[([\s\S]*?)\];/.exec(themesJs)[1].replace(/,\s*$/, '') + ']')
	.filter(t => t !== 'toolbar-height-controls' && t !== 'sprite-button-icons-uid');
const lessTokens = new Set([...src('apps/common/main/resources/less/colors-table.less').matchAll(/^\s*--([\w-]+)\s*:/mg)].map(m => m[1]));
const sandbox = {};
vm.runInNewContext(extract(themesJs, 'var create_colors_css = function') + '; this.create_colors_css = create_colors_css;', sandbox);

const examples = list(THEMES).filter(f => f.endsWith('.json.example'));
check(examples.includes('full-theme-dark.json.example') && examples.includes('full-theme-light.json.example'), 'full dark and light examples exist');
const parsed = {};
for (const f of examples) {
	try { parsed[f] = JSON.parse(src(`${THEMES}/${f}`)); check(true, `${f} is valid JSON`); }
	catch (e) { check(false, `${f} is valid JSON (${e.message})`); }
}
for (const f of ['full-theme-dark.json.example', 'full-theme-light.json.example']) {
	const t = parsed[f];
	if (!t) { check(false, `${f}: could not be checked`); continue; }
	check(!!t.id && !!t.name && /^(dark|light)$/.test(t.type), `${f}: has id, name and type`);
	const missing = tokens.filter(k => !(k in t.colors));
	check(missing.length === 0, `${f}: lists all ${tokens.length} colour tokens` + (missing.length ? ` (missing ${missing.length}: ${missing.slice(0, 6).join(', ')}...)` : ''));
	const unknown = Object.keys(t.colors).filter(k => !lessTokens.has(k));
	check(unknown.length === 0, `${f}: no token the colour table does not define` + (unknown.length ? ` (${unknown.join(', ')})` : ''));
	const css = sandbox.create_colors_css(t.id, t.colors);
	check(tokens.every(k => css.includes(`--${k}:${t.colors[k]};`)), `${f}: create_colors_css emits every token`);
}
console.log(failed ? `FAILED (${failed})` : 'PASS');
process.exit(failed ? 1 : 0);
