/*
 * Upstream fe000348f0 (bug 81734): the spreadsheet opened by "Edit chart
 * data" in the document and presentation editors (isEditDiagram) threw a
 * TypeError. Its Main.applyModeEditorElements set up the Comments controller,
 * but Common.UI.ExternalUsers is never initialised in that mode (its api is
 * null), so the comment/user colour lookup ExternalUsers.getColor called
 * api.asc_getUserColorById on null.
 *
 * This test
 *  1. loads the real common/main/lib/controller/ExternalUsers.js in a vm and
 *     calls getColor without init: it must return a colour, not throw
 *     (baseline: TypeError -> FAILS); after init it must use the api colour;
 *  2. extracts the coauthoring part of the real spreadsheet
 *     Main.applyModeEditorElements and runs it against a stub Comments
 *     controller: for the chart-data editor the controller must not be set up
 *     (baseline: it is -> FAILS); for a normal spreadsheet it still is.
 *
 * NOT claimed: the rest of applyModeEditorElements, or the embedded editor in
 * a running app.
 *
 * Env: RD_REPO   web-apps checkout (default ../../web-apps)
 *      BASELINE=1 reads web-apps from BASE_REF (default 12a95aaeda) via git show; must FAIL.
 */
'use strict';
const assert = require('assert');
const vm = require('vm');
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

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

/* ---- 1. ExternalUsers.getColor without an api ---- */
function loadExternalUsers() {
	const ctx = { Common: { NotificationCenter: { on() {} }, Gateway: { on() {} } } };
	vm.createContext(ctx);
	vm.runInContext(src('apps/common/main/lib/controller/ExternalUsers.js'), ctx);
	return ctx.Common.UI.ExternalUsers;
}
{
	const eu = loadExternalUsers();
	let color, err;
	try { color = eu.getColor('user-1'); } catch (e) { err = e; }
	check(!err && typeof color === 'string', `getColor before init returns a colour (${err ? 'threw ' + err.message : color})`);
	const eu2 = loadExternalUsers();
	eu2.init(false, { asc_getUserColorById: () => 0x123456 });
	let c2, err2;
	try { c2 = eu2.getColor('user-2'); } catch (e) { err2 = e; }
	check(!err2 && c2 === '#123456', `getColor after init uses the api colour (${err2 ? 'threw ' + err2.message : c2})`);
}

/* ---- 2. comments are not set up in the chart-data editor ---- */
{
	const text = src('apps/spreadsheeteditor/main/app/controller/Main.js');
	const at = text.search(/applyModeEditorElements\s*:\s*function\s*\(/);
	assert(at > 0, 'applyModeEditorElements not found');
	const start = text.indexOf('{', at) + 1;
	const end = text.indexOf('/** coauthoring end **/', start);
	assert(end > start, 'coauthoring block not found');
	const part = new Function('prevmode', text.slice(start, end));
	for (const isEditDiagram of [true, false]) {
		const calls = [];
		const comments = { setMode() { calls.push('setMode'); }, setConfig() { calls.push('setConfig'); } };
		const self = {
			appOptions: { isEditDiagram },
			editorConfig: {},
			api: {},
			getApplication: () => ({ getController: name => (name === 'Common.Controllers.Comments' ? comments : null) }),
		};
		part.call(self);
		if (isEditDiagram) check(calls.length === 0, `chart-data editor: Comments controller not set up (${calls.join(',') || 'none'})`);
		else check(calls.includes('setMode') && calls.includes('setConfig'), `normal spreadsheet: Comments controller set up (${calls.join(',')})`);
	}
}

if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log('PASS');
