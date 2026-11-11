/*
 * #73 - macOS text navigation keys. In the 9.4 app Cmd+Left/Right (start/end of the line)
 * and Option+Left/Right (word), with Shift to select, already follow macOS; Cmd+Up/Down -
 * start/end of the document on macOS - did not: in a document, a slide text box and
 * spreadsheet shape text they moved one line (CtrlKey went to MoveCursorUp/Down, which only
 * uses it to nudge a selected drawing), and the cell editor's "up"/"down" cases always moved
 * a line.
 *
 * This extracts the real Up/Down branches of the four key handlers by brace matching -
 * CDocument.OnKeyDown (word/Editor/Document.js), CPresentation.OnKeyDown
 * (slide/Editor/Format/Presentation.js), the shape-text handler in
 * common/Drawings/CommonController.js and CellEditor's keydown cases
 * (cell/view/CellEditorView.js) - and runs them against recording stubs.
 *
 * Claimed: on macOS Cmd(+Shift)+Up/Down in text calls what Ctrl(+Shift)+Home/End calls;
 * a selected drawing that is not being text-edited still gets MoveCursorUp/Down (its nudge);
 * off macOS nothing changes. NOT claimed: real key delivery (checked by hand in the app via
 * CDP), the PDF editor, the cursor positions the move functions compute.
 *
 *   node issue-0073-mac-cmd-up-down-test.js              (RD_REPO=<sdkjs tree>, default ../sdkjs)
 *   BASELINE=1 node issue-0073-mac-cmd-up-down-test.js   (sources of BASE_REF; must fail)
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
// Pinned to the parent of the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '33475b76ae^';

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
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	assert.strictEqual(text.indexOf(marker, at + 1), -1, marker + ' is not unique');
	return block(text, at);
}

/* records every method called on it (any name), returning undefined */
function recorder(extra) {
	const calls = [];
	const target = Object.assign({ calls }, extra || {});
	return new Proxy(target, {
		get(t, name) {
			if (name in t) return t[name];
			return (...args) => { calls.push([name, ...args]); };
		},
	});
}

function ev(mods) {
	return { CtrlKey: mods.includes('cmd'), ShiftKey: mods.includes('shift'), AltKey: false,
		IsShift() { return this.ShiftKey; } };
}

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

/* --- word: CDocument.OnKeyDown --- */
const word = src('word/Editor/Document.js');
const wordBranch = {
	38: extract(word, 'else if (e.KeyCode === 38) // Top Arrow'),
	40: extract(word, 'else if (e.KeyCode === 40) // Bottom Arrow'),
};
function runWord(key, mods, mac, drawingSelected) {
	const doc = recorder({
		IsFillingFormMode: () => false,
		DrawingDocument: { TargetStart() {}, UpdateTargetFromPaint: false },
		DrawingObjects: { selectedObjects: drawingSelected ? [{}] : [] },
		private_CheckCursorPosInFillingFormMode() {}, CheckComplexFieldsInSelection() {},
		Document_UpdateInterfaceState() {}, Document_UpdateRulersState() {},
	});
	const AscFormat = { getTargetTextObject: () => null };
	new Function('e', 'bIsMacOs', 'AscFormat', 'AscWord', 'keydownresult_PreventAll',
		'let bRetValue;' + wordBranch[key]).call(doc, ev(mods), mac, AscFormat, { Direction: {} }, 1);
	return doc.calls;
}

check('word: Cmd+Up on macOS goes to the start of the document', () =>
	assert.deepStrictEqual(runWord(38, ['cmd'], true), [['MoveCursorToStartPos', false]]));
check('word: Cmd+Shift+Down on macOS selects to the end of the document', () =>
	assert.deepStrictEqual(runWord(40, ['cmd', 'shift'], true), [['MoveCursorToEndPos', true]]));
check('word: Cmd+Up with a drawing selected still nudges it', () =>
	assert.deepStrictEqual(runWord(38, ['cmd'], true, true), [['MoveCursorUp', false, true]]));
check('word: Ctrl+Up off macOS is unchanged', () =>
	assert.deepStrictEqual(runWord(38, ['cmd'], false), [['MoveCursorUp', false, true]]));
check('word: plain Down on macOS is unchanged', () =>
	assert.deepStrictEqual(runWord(40, [], true), [['MoveCursorDown', false, false]]));

/* --- slide: CPresentation.OnKeyDown --- */
const slide = src('slide/Editor/Format/Presentation.js');
const slideBranch = {
	38: extract(slide, '} else if (e.KeyCode === 38) // Top Arrow'),
	40: extract(slide, '} else if (e.KeyCode === 40) // Bottom Arrow'),
};
function runSlide(key, mods, mac, inText) {
	const pres = recorder({ Slides: [{}], IsFocusOnNotes: () => false, DrawingDocument: { SlideCurrent: 0 } });
	const oController = { getTargetDocContent: () => (inText ? {} : null) };
	new Function('e', 'bIsMacOs', 'oController', 'keydownresult_PreventAll',
		'let bRetValue;' + slideBranch[key]).call(pres, ev(mods), mac, oController, 1);
	return pres.calls;
}
check('slide: Cmd+Up in a text box on macOS goes to the start of the text', () =>
	assert.deepStrictEqual(runSlide(38, ['cmd'], true, true), [['MoveCursorToStartPos', false]]));
check('slide: Cmd+Shift+Down in a text box on macOS selects to the end', () =>
	assert.deepStrictEqual(runSlide(40, ['cmd', 'shift'], true, true), [['MoveCursorToEndPos', true]]));
check('slide: Cmd+Up on a selected shape (no text editing) still nudges it', () =>
	assert.deepStrictEqual(runSlide(38, ['cmd'], true, false), [['MoveCursorUp', false, true]]));
check('slide: Ctrl+Down off macOS is unchanged', () =>
	assert.deepStrictEqual(runSlide(40, ['cmd'], false, true), [['MoveCursorDown', false, true]]));

/* --- spreadsheet shapes: CommonController key handler --- */
const ctl = src('common/Drawings/CommonController.js');
const ctlBranch = {
	38: extract(ctl, '} else if (oEvent.KeyCode === 38) // Top Arrow'),
	40: extract(ctl, '} else if (oEvent.KeyCode === 40) // Bottom Arrow'),
};
function runCtl(key, mods, mac, inText) {
	const content = recorder();
	const c = recorder({ getTargetDocContent: () => (inText ? content : null),
		updateSelectionState() {}, updateOverlay() {}, drawingObjects: { sendGraphicObjectProps() {} } });
	const e = ev(mods);
	new Function('oEvent', 'bIsMacOs', 'bIsCtrl', 'keydownresult_PreventDefault',
		'let nRetValue;' + ctlBranch[key]).call(c, e, mac, e.CtrlKey, 1);
	return { controller: c.calls, content: content.calls };
}
check('shape text: Cmd+Up on macOS goes to the start of the text', () =>
	assert.deepStrictEqual(runCtl(38, ['cmd'], true, true), { controller: [], content: [['MoveCursorToStartPos', false]] }));
check('shape text: Cmd+Shift+Down on macOS selects to the end', () =>
	assert.deepStrictEqual(runCtl(40, ['cmd', 'shift'], true, true), { controller: [], content: [['MoveCursorToEndPos', true]] }));
check('shape text: Cmd+Up on a selected shape still nudges it', () =>
	assert.deepStrictEqual(runCtl(38, ['cmd'], true, false), { controller: [['cursorMoveUp', false, true]], content: [] }));
check('shape text: Ctrl+Up off macOS is unchanged', () =>
	assert.deepStrictEqual(runCtl(38, ['cmd'], false, true), { controller: [['cursorMoveUp', false, true]], content: [] }));

/* --- cell editor --- */
const cell = src('cell/view/CellEditorView.js');
const consts = {};
for (const m of cell.matchAll(/var (k[A-Z]\w+) = (-?\d+);/g)) consts[m[1]] = +m[2];
const cellCase = {
	38: extract(cell, 'case 38: {// "up"'),
	40: extract(cell, 'case 40: { // "down"'),
};
const name = (v) => Object.keys(consts).find((k) => consts[k] === v) || v;
function runCell(key, mods, mac) {
	const ce = recorder({ enableKeyEvents: true, hasFocus: true });
	new Function('oEvent', 'bIsMacOs', 'oThis', 'bHieroglyph', 'keydownresult_PreventAll', ...Object.keys(consts),
		'let nRetValue; do ' + cellCase[key] + ' while (false);')
		.call(ce, ev(mods), mac, ce, false, 1, ...Object.values(consts));
	return ce.calls.map(([f, k]) => [f, name(k)]);
}
check('cell editor: Cmd+Up on macOS goes to the start of the text', () =>
	assert.deepStrictEqual(runCell(38, ['cmd'], true), [['_moveCursor', 'kBeginOfText']]));
check('cell editor: Cmd+Shift+Down on macOS selects to the end of the text', () =>
	assert.deepStrictEqual(runCell(40, ['cmd', 'shift'], true), [['_selectChars', 'kEndOfText']]));
check('cell editor: plain Up on macOS still moves a line', () =>
	assert.deepStrictEqual(runCell(38, [], true), [['_moveCursor', 'kPrevLine']]));
check('cell editor: Ctrl+Down off macOS is unchanged', () =>
	assert.deepStrictEqual(runCell(40, ['cmd'], false), [['_moveCursor', 'kNextLine']]));

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
