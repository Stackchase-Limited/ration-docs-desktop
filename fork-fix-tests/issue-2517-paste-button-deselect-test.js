/*
 * #2517 - after pasting shapes/pictures on a slide, the floating paste-options
 * "(Ctrl)" button stayed on screen until the next undo point, a slide change
 * or Ctrl+C, even after clicking elsewhere or selecting another object.
 *
 * Cause: for a drawing paste the button is anchored at a fixed slide position
 * (buttonInfo.fixPosition, shapeId null). asc_UpdateSpecialPasteButton
 * (slide/api.js), which Document_UpdateInterfaceState runs on every selection
 * change, re-showed it there whenever that slide was current; only text
 * pasted into a shape had a "same target?" check. Reproduced headless in
 * docbuilder with the real PasteProcessor._setSpecialPasteShowOptionsPresentation
 * + SpecialPasteButton_Update_Position: after deselecting, the button was
 * re-shown at its old coordinates instead of (-1,-1).
 *
 * Fix: _setSpecialPasteShowOptionsPresentation (common/wordcopypaste.js)
 * records the pasted drawings' ids in fixPosition, and the update moves the
 * button off-screen (-1,-1: web-apps hides it) once the selection is no
 * longer exactly those drawings.
 *
 * This extracts both real functions (+ private_IsPastedDrawingsSelected) and
 * drives them with stubs. NOT claimed: the web-apps side (unchanged; it hides
 * the container for negative coordinates) and on-screen behaviour in the GUI.
 *
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs). BASELINE=1 reads the
 * sources at BASE_REF (default: parent of the fix) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '07f0989ffd^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return '';
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const api = src('slide/api.js');
const paste = src('common/wordcopypaste.js');

/* --- stubs --- */
function Rect(x, y, w, h) { this._x = x; this._y = y; this._w = w; this._h = h; }
let selected = [];
const drawing = id => ({ Get_Id: () => id });
const pic = drawing('pic'), other = drawing('other');
const presentation = {
	CurPage: 0,
	IsMasterMode: () => false,
	GetSelectionState: () => ({ CurPage: 0 }),
	GetTargetPosition: () => null,                 // drawings selected, no text cursor
	GetSelectedBounds: () => ({ x: 10, y: 20, w: 30, h: 40 }),
	IsFocusOnThumbnails: () => false,
	GetSelectedSlides: () => [0],
	Get_TargetDocContent: () => null,
	IsFocusOnNotes: () => false,
	GetCurrentController: () => ({ selectedObjects: selected }),
	DrawingDocument: { ConvertCoordsToCursorWR: (x, y) => ({ X: x * 2, Y: y * 2 }) },
};
const buttonInfo = {
	options: null, cellCoord: null, shapeId: null, fixPosition: null,
	asc_setOptions(v) { this.options = v; },
	asc_setLastSelectedPasteProperty() {},
	setShapeId(v) { this.shapeId = v; },
	asc_setCellCoord(v) { this.cellCoord = v; },
	asc_getCellCoord() { return this.cellCoord; },
	setFixPosition(v) { this.fixPosition = v; },
};
const AscCommon = { asc_CRect: Rect, g_specialPasteHelper: { buttonInfo, isPasteOptions: false, specialPasteProps: null } };
const editor = { WordControl: { m_oLogicDocument: presentation, Thumbnails: null } };
const Asc = { c_oSpecialPasteProps: { sourceformatting: 1, keepTextOnly: 2 } };
const window = { AscCommon, NATIVE_EDITOR_ENJINE: false };

const PasteProcessor = new Function('editor', 'window', 'AscCommon', 'Asc',
	'return {' + extract(paste, '_setSpecialPasteShowOptionsPresentation: function') + '};')(editor, window, AscCommon, Asc);

function asc_docs_api() { this.WordControl = editor.WordControl; }
new Function('asc_docs_api', 'AscCommon', 'window', 'editor',
	extract(api, 'asc_docs_api.prototype.asc_UpdateSpecialPasteButton = function') + ';\n' +
	extract(api, 'asc_docs_api.prototype.private_IsPastedDrawingsSelected = function', true) + ';')(
	asc_docs_api, AscCommon, window, editor);
const sdk = new asc_docs_api();
const shownAt = [];
sdk.asc_ShowSpecialPasteButton = props => shownAt.push([props.asc_getCellCoord()._x, props.asc_getCellCoord()._y]);

/* paste: the pasted picture is the selection */
selected = [pic];
PasteProcessor._setSpecialPasteShowOptionsPresentation();

const failures = [];
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures.push(name); console.log('FAIL ' + name + ': ' + e.message); }
}
function update() { shownAt.length = 0; sdk.asc_UpdateSpecialPasteButton(); return shownAt[0]; }

check('pasted picture still selected: button stays at the picture corner', () => {
	assert.deepStrictEqual(update(), [80, 120]);
});
check('clicked on empty slide area: button hidden (off-screen)', () => {
	selected = [];
	assert.deepStrictEqual(update(), [-1, -1], 'button is re-shown at its old place after the picture was deselected');
});
check('another shape selected: button hidden', () => {
	selected = [other];
	assert.deepStrictEqual(update(), [-1, -1]);
});
check('pasted picture plus another shape selected: button hidden', () => {
	selected = [pic, other];
	assert.deepStrictEqual(update(), [-1, -1]);
});
check('pasted picture reselected: button back at its corner', () => {
	selected = [pic];
	assert.deepStrictEqual(update(), [80, 120]);
});

if (failures.length) {
	console.log('FAIL #2517: ' + failures.length + ' check(s) failed' + (process.env.BASELINE ? ' (expected on BASELINE)' : ''));
	process.exit(1);
}
console.log('PASS #2517: paste-options button follows the pasted drawings\' selection' +
	(process.env.BASELINE ? ' (BASELINE?!)' : ''));
