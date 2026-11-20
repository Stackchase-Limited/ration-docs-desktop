/*
 * Upstream dbc71b0951 (online / WOPI only): the WOPI editor page
 * apps/api/wopi/editor-wopi.ejs ignored the CheckFileInfo flags DisableCopy
 * and DisableExport, so a WOPI host that forbade copying or downloading a
 * file still got "copy" and "download" permissions in the editor.
 *
 * This test evaluates the real permission code of editor-wopi.ejs (from
 * "let customizationFormSubmit" to "sessionId", plus the "permissions" object)
 * for several CheckFileInfo answers: DisableCopy -> copy false, DisableExport
 * -> download false (baseline: both stay allowed -> FAILS);
 * CopyPasteRestrictions still works; no flags -> copy and download allowed.
 *
 * NOT claimed: the editors' handling of the permissions, or a WOPI server.
 * The desktop app does not use this page.
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

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

/* ---- 1. WOPI permissions ---- */
{
	const ejs = src('apps/api/wopi/editor-wopi.ejs');
	const a = ejs.indexOf('let customizationFormSubmit');
	const b = ejs.indexOf('sessionId = userAuth.userSessionId', a);
	assert(a > 0 && b > a, 'permission code not found in editor-wopi.ejs');
	const p = ejs.indexOf('"permissions"', b);
	const perms = block(ejs, p);
	const permissions = new Function('fileInfo', 'queryParams', 'userAuth', ejs.slice(a, b) + '\nreturn ' + perms + ';');
	const base = { UserCanWrite: true };
	const q = {}, u = {};
	const run = extra => permissions(Object.assign({}, base, extra), q, u);

	let r = run({});
	check(r.copy === true && r.download !== false, `no flags: copy and download allowed (copy=${r.copy}, download=${r.download})`);
	r = run({ DisableCopy: true });
	check(r.copy === false, `DisableCopy: copy=${r.copy}`);
	r = run({ DisableExport: true });
	check(r.download === false, `DisableExport: download=${r.download}`);
	r = run({ CopyPasteRestrictions: 'BlockAll' });
	check(r.copy === false, `CopyPasteRestrictions=BlockAll: copy=${r.copy}`);
}

if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log('PASS');
