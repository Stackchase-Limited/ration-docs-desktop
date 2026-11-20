/*
 * Upstream 9c764ad966 (online): api.js created the editor iframe with
 * allow="... clipboard-write;", delegating clipboard write access to the
 * editor frame of any page that embeds the editors (flagged as a security
 * warning).
 *
 * Ours keeps clipboard-write for the desktop app: it opens the editors through
 * the same api.js (editors/web-apps/apps/api/documents/index.html, iframe
 * "frameEditor") and sdkjs copies with navigator.clipboard there (CEF >= 109),
 * so desktop copy/paste must not change.
 *
 * This test
 *  1. extracts the real api.js createIframe and runs it with a stub document:
 *     a web page (targetApp unset) must not grant clipboard-write (baseline:
 *     it does -> FAILS); the desktop app (targetApp 'desktop') keeps it; the
 *     other permissions are unchanged;
 *  2. checks api.js sets targetApp = 'desktop' (when window.AscDesktopEditor
 *     exists) before it calls createIframe.
 *
 * NOT claimed: copy/paste in a running browser or desktop app.
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

/* ---- 1. iframe permission policy ---- */
{
	const api = src('apps/api/documents/api.js');
	const at = api.indexOf('function createIframe(config)');
	assert(at > 0, 'createIframe not found');
	const body = block(api, at);
	const document = {
		body: { style: {} },
		createElement: () => ({ style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }),
	};
	const createIframe = new Function('document', 'getAppPath', 'getAppParameters', 'return function createIframe(config) ' + body)(
		document, () => 'https://docs.example/', () => '?x=1');
	const allow = cfg => createIframe(Object.assign({ width: '100%', height: '100%', type: 'desktop' }, cfg)).attrs.allow || '';

	let s = allow({ editorConfig: {} });
	check(!/clipboard-write/.test(s), `web page iframe does not grant clipboard-write ("${s}")`);
	s = allow({ editorConfig: { targetApp: 'desktop' } });
	check(/clipboard-write/.test(s), `desktop app iframe keeps clipboard-write ("${s}")`);
	check(/autoplay/.test(s) && /camera/.test(s) && /microphone/.test(s) && /display-capture/.test(s), 'other iframe permissions unchanged');

	/* ---- 2. targetApp is set before the iframe is created ---- */
	const t = api.search(/_config\.editorConfig\.targetApp\s*=\s*'desktop'/);
	const c = api.indexOf('iframe = createIframe(_config)');
	check(t > 0 && c > t && /if \(!!window\.AscDesktopEditor\)\s*\{\s*_config\.editorConfig\.targetApp/.test(api),
		'api.js marks the desktop app (window.AscDesktopEditor) before createIframe');
}

if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log('PASS');
