/*
 * #2467 - in a multi-line cell edited in the formula bar, Home (or End) then
 * Alt+Enter put the line break at the caret's PREVIOUS place - with the caret
 * moved from the end of line 1 to its start, the new line appeared after
 * line 1 instead of before it.
 *
 * While the formula bar textarea has focus, text_input2.js turns the editor's
 * key events off (asc_enableKeyEvents(false) for any focused TEXTAREA), so the
 * textarea moves its own caret and CellEditor has to read it back. The arrow
 * cases in _onWindowKeyDown do that with _delayedUpdateCursorByTopLine(); the
 * Home and End cases just broke out, so cursorPos kept the old position while
 * the textarea showed the new one. Alt+Enter is handled by the cell editor
 * whatever enableKeyEvents is (_addNewLine -> _addChars at this.cursorPos), so
 * it used the stale position.
 *
 * This extracts the real CellEditor.prototype._onWindowKeyDown,
 * _delayedUpdateCursorByTopLine, _updateCursorByTopLine, _moveCursor and
 * _addNewLine plus the k* cursor constants (CellEditorView.js) and the
 * keydownresult_* flags (word/Editor/Document.js), and drives Home / End and
 * then Alt+Enter with a stub textarea whose caret moves the way the browser
 * moves it. _addChars is a stub that records where the text would go.
 *
 * NOT claimed: how a real browser orders the native caret move against the
 * setTimeout (the stub moves the caret right after keydown returns, as the
 * default action does); the canvas (in-cell) editing path, where Home is
 * handled by _moveCursor(kBeginOfLine) directly and is not touched by the fix.
 *
 *   node issue-2467-formula-bar-home-alt-enter-test.js       -> PASS
 *   BASELINE=1 node issue-2467-formula-bar-home-alt-enter-test.js -> FAIL
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs).
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '0c13033452^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const editorSrc = src('cell/view/CellEditorView.js');
const documentSrc = src('word/Editor/Document.js');

function method(name) {
	const head = `CellEditor.prototype.${name} = function`;
	const at = editorSrc.indexOf(head);
	assert.notStrictEqual(at, -1, `${name} not found`);
	return block(editorSrc, at + head.length - 'function'.length);
}

// module-level constants, taken from the sources rather than restated
const kConsts = editorSrc.match(/^\tvar k[A-Za-z]+ = -?\d+;$/mg);
assert.ok(kConsts && kConsts.some((l) => l.includes('kPosition')), 'k* constants not found');
const kdConsts = documentSrc.match(/^var keydownresult_\w+\s*=\s*0x[0-9A-F]+;$/mg);
assert.ok(kdConsts && kdConsts.length >= 5, 'keydownresult constants not found');

const names = ['_onWindowKeyDown', '_delayedUpdateCursorByTopLine', '_updateCursorByTopLine', '_moveCursor', '_addNewLine'];
const body = names.map((n) => `P.${n} = ${method(n)};`).join('\n');
assert.ok(/case 36:/.test(method('_onWindowKeyDown')), 'extracted the wrong _onWindowKeyDown');

// timers queued by setTimeout run when we say so, between "events"
const timers = [];
const fakeWindow = { Asc: { editor: { getShortcut: () => -1 } } };
const AscCommon = { AscBrowser: { isMacOs: false } };
const AscCommonExcel = { getFragmentsLength: (f) => f.text.length };
const install = new Function('P', 'window', 'AscCommon', 'AscCommonExcel', 'setTimeout',
	'"use strict";\n' + kConsts.join('\n') + '\n' + kdConsts.join('\n') + '\n' + body);
const P = {};
install(P, fakeWindow, AscCommon, AscCommonExcel, (fn) => timers.push(fn));
function runTimers() { while (timers.length) timers.shift()(); }

const TEXT = 'CellA1-Line01\nCellA1-Line02\nCellA1-Line03\nCellA1-Line04';
const END_OF_LINE1 = TEXT.indexOf('\n');

function makeEditor() {
	const ed = Object.create(P);
	Object.assign(ed, {
		isOpened: true, hasFocus: true, isTopLineActive: true,
		enableKeyEvents: false, // text_input2.js turns them off while the textarea has focus
		selectionBegin: -1, selectionEnd: -1, isSelectMode: false,
		cursorPos: END_OF_LINE1, inserts: [],
		options: { fragments: { text: TEXT } },
		input: { value: TEXT, selectionStart: END_OF_LINE1, selectionEnd: END_OF_LINE1 },
		handlers: { trigger: () => false },
		textRender: {}, textFlags: {},
		executeShortcut: () => null,
		getMenuEditorMode: () => false,
		_setSkipKeyPress() {}, _updateCursorPosition() {}, _updateCursor() {},
		_cleanSelection() {}, _selectChars() {}, _wrapText() {},
		_addChars(str) { this.inserts.push({ str, pos: this.cursorPos }); },
	});
	return ed;
}

function key(code, opts) {
	opts = opts || {};
	return {
		GetKeyCode: () => code, IsAlt: () => !!opts.alt, IsShift: () => !!opts.shift,
		CtrlKey: !!opts.ctrl, IsCtrl: () => !!opts.ctrl,
	};
}

// a keydown in the textarea: the editor's handler, then the browser's default
// action moving the caret (unless prevented), then queued timeouts
function press(ed, code, opts, nativeCaret) {
	const r = ed._onWindowKeyDown(key(code, opts));
	if (nativeCaret !== undefined && !(r & 0x0001)) {
		ed.input.selectionStart = ed.input.selectionEnd = nativeCaret;
	}
	runTimers();
	return r;
}

let failures = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failures++; console.log('FAIL ' + label + '\n     ' + e.message); }
}

check('Home then Alt+Enter in the formula bar breaks the line at the start', () => {
	const ed = makeEditor();
	press(ed, 36, {}, 0);               // Home: textarea caret -> start of line 1
	press(ed, 13, { alt: true });       // Alt+Enter
	assert.strictEqual(ed.inserts.length, 1, 'no newline inserted');
	assert.strictEqual(ed.inserts[0].str, '\n');
	assert.strictEqual(ed.inserts[0].pos, 0,
		`newline went in at ${ed.inserts[0].pos} (end of line 1 is ${END_OF_LINE1}), not at the caret`);
});

check('End then Alt+Enter in the formula bar breaks the line at the end', () => {
	const ed = makeEditor();
	ed.cursorPos = 0;
	ed.input.selectionStart = ed.input.selectionEnd = 0;
	press(ed, 35, {}, END_OF_LINE1);    // End: textarea caret -> end of line 1
	press(ed, 13, { alt: true });
	assert.strictEqual(ed.inserts.length, 1, 'no newline inserted');
	assert.strictEqual(ed.inserts[0].pos, END_OF_LINE1,
		`newline went in at ${ed.inserts[0].pos}, not at the caret (${END_OF_LINE1})`);
});

check('arrows (unchanged) already resync the same way', () => {
	const ed = makeEditor();
	press(ed, 37, {}, END_OF_LINE1 - 1); // Left
	press(ed, 13, { alt: true });
	assert.strictEqual(ed.inserts[0].pos, END_OF_LINE1 - 1);
});

if (failures) {
	console.log(`FAIL #2467: ${failures} check(s) failed` + (process.env.BASELINE ? ' (baseline, expected)' : ''));
	process.exit(1);
}
console.log('PASS #2467: Home/End in the formula bar keep the editor caret in step' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
