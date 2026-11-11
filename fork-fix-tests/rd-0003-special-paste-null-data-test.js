/*
 * RD-0003 (found reading the code; no upstream issue) - special paste with no
 * clipboard data threw "TypeError: null is not an object".
 *
 * CClipboardBase.initSpecialPasteData (common/clipboard_base.js) reports empty
 * data through _callback() when Get_Clipboard_Data hands it null - no
 * navigator.clipboard, a refused or failed clipboard read - and then fell
 * through to paste_data[c_oAscClipboardDataFormat.Image], dereferencing null.
 * With no navigator.clipboard the callback is synchronous, so the TypeError
 * escaped into the word/cell/slide api that started the special paste.
 *
 * This extracts the REAL initSpecialPasteData by brace matching and runs it with
 * a Get_Clipboard_Data stub that answers null synchronously (what the real one
 * does without navigator.clipboard), and, as a control, with Text-only data.
 *
 * Claimed: null data -> the caller's callback runs exactly once, specialPasteData
 * is reset, nothing throws; Text data still reaches specialPasteData.
 * NOT claimed: the clipboard reading itself (navigator.clipboard), or the
 * Html/Internal branches.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the source at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '12e566a791^';
const REL = 'common/clipboard_base.js';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}
const marker = 'initSpecialPasteData: function (callback)';
const at = source.indexOf(marker);
assert.notStrictEqual(at, -1, marker + ' not found');
const body = block(source, at);

/* --- stubs: only what initSpecialPasteData touches --- */
const AscCommon = {
	c_oAscClipboardDataFormat: { Text: 1, Html: 2, Internal: 4, HtmlElement: 8, Image: 16 },
	g_specialPasteHelper: {
		specialPasteData: {},
		Clean_SpecialPasteObj() { this.specialPasteData = {}; },
	},
	g_clipboardBase: { CommonIframe_PasteStart() { throw new Error('unexpected Html branch'); } },
};
const initSpecialPasteData = new Function('AscCommon', 'return function (callback) ' + body)(AscCommon);

function run(data) {
	const clipboard = { Get_Clipboard_Data(cb) { cb(data); }, initSpecialPasteData };
	let calls = 0, error = null;
	try {
		clipboard.initSpecialPasteData(() => { calls++; });
	} catch (e) {
		error = e;
	}
	return { calls, error, spd: AscCommon.g_specialPasteHelper.specialPasteData };
}

let failed = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + ': ' + e.message); }
}

check('null clipboard data: no throw, callback once, nothing staged', () => {
	const r = run(null);
	assert.strictEqual(r.error, null, 'threw ' + (r.error && r.error.message));
	assert.strictEqual(r.calls, 1);
	assert.strictEqual(r.spd._format, undefined);
	assert.strictEqual(r.spd.data1, undefined);
});
check('control: text clipboard data is staged', () => {
	const r = run({ 1: 'hello' });
	assert.strictEqual(r.error, null, 'threw ' + (r.error && r.error.message));
	assert.strictEqual(r.calls, 1);
	assert.strictEqual(r.spd._format, 1);
	assert.strictEqual(r.spd.data1, 'hello');
});

console.log(failed ? `FAIL: ${failed} check(s)` : 'PASS: special paste handles empty clipboard data');
process.exit(failed ? 1 : 0);
