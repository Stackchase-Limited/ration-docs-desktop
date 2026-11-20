/*
 * Upstream fcd820a9de (bug 81637): View > Macros clicked before the editors'
 * post-launch scripts have loaded threw "TypeError: Common.Views.MacrosDialog
 * is not a constructor" (document, spreadsheet, presentation and PDF editors).
 *
 * This test extracts the real ViewTab controller onClickMacros of each editor
 * and runs it
 *  1. with Common.Views.MacrosDialog not loaded yet: it must not throw
 *     (baseline: TypeError -> FAILS);
 *  2. with a stub dialog class loaded: it must create the dialog with the
 *     editor api and show it.
 *
 * NOT claimed: the real dialog renders; a later click after loading is the
 * user's own action (the click before loading does nothing).
 *
 * Env: RD_REPO   web-apps checkout (default ../../web-apps)
 *      BASELINE=1 reads web-apps from BASE_REF (default 12a95aaeda) via git show; must FAIL.
 */
'use strict';
const assert = require('assert');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const WEB = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '12a95aaeda';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEB, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(WEB, rel), 'utf8');
}

// text of the balanced {...} block that starts at the first '{' at or after `from`
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}

// the real method `name: function(args) {...}` of a controller, as a function that sees `deps` by name
function method(text, name, deps) {
	const m = new RegExp('\\b' + name + '\\s*:\\s*function\\s*\\(([^)]*)\\)').exec(text);
	if (!m) return null;
	const body = block(text, m.index + m[0].length);
	const names = Object.keys(deps || {});
	return new Function(...names, `return function(${m[1]}) ${body};`)(...names.map(k => deps[k]));
}

const files = [
	'apps/documenteditor/main/app/controller/ViewTab.js',
	'apps/spreadsheeteditor/main/app/controller/ViewTab.js',
	'apps/presentationeditor/main/app/controller/ViewTab.js',
	'apps/pdfeditor/main/app/controller/ViewTab.js',
];

let failed = 0;
for (const rel of files) {
	const text = src(rel);
	const Common = { Views: {} };
	const onClickMacros = method(text, 'onClickMacros', { Common });
	assert(onClickMacros, `${rel}: onClickMacros not found`);
	const api = { id: 'api' };
	try {
		onClickMacros.call({ api });
		console.log(`ok   ${rel}: click before the dialog is loaded does not throw`);
	} catch (e) {
		failed++;
		console.log(`FAIL ${rel}: click before the dialog is loaded throws: ${e.message}`);
	}
	let shown = null;
	Common.Views.MacrosDialog = function (opts) { this.opts = opts; this.show = () => { shown = this.opts; }; };
	onClickMacros.call({ api });
	if (shown && shown.api === api) console.log(`ok   ${rel}: click after loading opens the dialog with the api`);
	else { failed++; console.log(`FAIL ${rel}: click after loading did not open the dialog`); }
}
if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log('PASS');
