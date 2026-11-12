/*
 * #167 - "Missing shortcut to quickly check Word Count / Document Info": the
 * word count was reachable only with the mouse (File > Document Info, or the
 * status bar's Word count button).
 *
 * Cause: web-apps apps/documenteditor/main/app/controller/LeftMenu.js - the
 * editor's UI keymap (Alt+F file menu, Ctrl+Shift+H comments, ...) had no
 * entry for document info. Fix: command+shift+g / ctrl+shift+g (Word's word
 * count shortcut; Ctrl+Shift+C asked for in the report is Copy Style here)
 * calls onShortcut('docinfo'), which opens File > Document Info (Statistics:
 * pages, paragraphs, words, characters).
 *
 * This test
 *  1. extracts the real keymap object from LeftMenu's initialize and checks a
 *     Ctrl+Shift+G / Cmd+Shift+G entry exists and calls onShortcut('docinfo')
 *     (baseline: no entry -> FAILS);
 *  2. extracts the real onShortcut and runs it for 'docinfo' against a stub
 *     left menu: it must open 'file:info' and swallow the key;
 *  3. runs sdkjs word/Editor/Shortcuts.js (the real default document-editor
 *     shortcut table, for macOS and for Windows/Linux) and checks no default
 *     shortcut already uses Ctrl/Cmd+Shift+G.
 *
 * NOT claimed: that keymaster receives the key in the running app (needs a
 * GUI check; the same keymap carries Ctrl+Shift+H, which works); counts for
 * the current selection only (Document Info counts the whole document); the
 * shortcut is not listed in the customisable shortcuts dialog.
 *
 * Env: RD_REPO   web-apps checkout (default ../web-apps)
 *      RD_SDKJS  sdkjs checkout    (default ../sdkjs)
 *      BASELINE=1 reads web-apps from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEB = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const SDKJS = path.resolve(process.env.RD_SDKJS || path.join(__dirname, '..', 'sdkjs'));
const BASE_REF = process.env.BASE_REF || '35bc28f2f3^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEB, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(WEB, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}

const lm = src('apps/documenteditor/main/app/controller/LeftMenu.js');

/* ---- 1. the keymap ---- */
const kmAt = lm.indexOf('var keymap = {');
assert.ok(kmAt !== -1, 'keymap not found - test is stale');
const calls = [];
const ctx = { onShortcut: (s) => calls.push(s) };
const _ = { bind: (fn, self, arg) => () => fn.call(self, arg) };
const keymap = new Function('_', 'Common', 'return ' + block(lm, kmAt) + ';').call(ctx, _, { Utils: {} });
assert.ok(keymap['command+shift+h,ctrl+shift+h'], 'stub harness broken: Ctrl+Shift+H entry missing');

const entry = Object.keys(keymap).find((k) => k.split(',').some((c) => /^(ctrl|command)\+shift\+g$/.test(c.trim())));
console.log('keymap entry for Ctrl/Cmd+Shift+G:', JSON.stringify(entry || null));
assert.ok(entry, 'no keyboard shortcut opens the word count / document info');
assert.ok(/ctrl\+shift\+g/.test(entry) && /command\+shift\+g/.test(entry), 'shortcut must exist for both Ctrl and Cmd');
keymap[entry]();
const action = calls.pop();
console.log('it calls onShortcut(' + JSON.stringify(action) + ')');

/* ---- 2. what the action does ---- */
const osAt = lm.indexOf('onShortcut: function(s, e)');
const onShortcut = new Function('Common', 'DE', 'return function(s, e) ' + block(lm, osAt) + ';')(
	{ UI: { Menu: { Manager: { hideAll: () => calls.push('hideAll') } } } }, {});
const shown = [];
const self = { mode: {}, leftMenu: { showMenu: (m) => shown.push(m), menuFile: { isVisible: () => false } } };
const ret = onShortcut.call(self, action, {});
console.log('onShortcut(' + action + ') opened', JSON.stringify(shown), 'returned', ret);
assert.deepStrictEqual(shown, ['file:info'], 'the shortcut must open File > Document Info');
assert.strictEqual(ret, false, 'the key must be swallowed');

/* ---- 3. no default sdkjs document shortcut already uses it ---- */
const tableSrc = fs.readFileSync(path.join(SDKJS, 'word/Editor/Shortcuts.js'), 'utf8');
for (const isMacOs of [false, true]) {
	const names = new Proxy({}, { get: (t, k) => k });
	const window = { Asc: { c_oAscDocumentShortcutType: names, c_oAscKeyCodes: names,
		CAscShortcut: function (type, key, ctrl, shift, alt, cmd) { Object.assign(this, { type, key, ctrl, shift, alt, cmd }); } },
		AscCommon: { AscBrowser: { isMacOs } } };
	new Function('window', 'Asc', 'AscCommon', tableSrc)(window, window.Asc, window.AscCommon);
	const all = [].concat(...Object.values(window.Asc.c_oAscDefaultShortcuts));
	assert.ok(all.length > 50, 'stub harness broken: shortcut table empty');
	const clash = all.filter((s) => s.key === 'KeyG' && s.shift && !s.alt && (s.ctrl || s.cmd));
	console.log(`sdkjs default shortcuts (${isMacOs ? 'macOS' : 'Windows/Linux'}): ${all.length}, on Ctrl/Cmd+Shift+G: ${clash.map((s) => s.type).join(',') || 'none'}`);
	assert.strictEqual(clash.length, 0, 'Ctrl/Cmd+Shift+G is already a document editor shortcut');
}

console.log('PASS #167: Ctrl+Shift+G / Cmd+Shift+G opens File > Document Info (word count)');
