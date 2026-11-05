/*
 * #2508 - with cursor blinking turned off in the OS, the caret still blinked
 * while editing a spreadsheet cell.
 *
 * Every caret the editors draw themselves was a DOM element toggled on a fixed
 * 500 ms timer and nothing read the OS setting: the cell editor
 * (CellEditorView.js _showCursor, defaults.blinkInterval) and the document
 * target of the word, slide, pdf and sheet-drawing DrawingDocuments
 * (TargetStart / DrawTarget). The report says the document editor respects the
 * setting; in this tree it did not either - only the native inputs Chromium
 * draws did. The fix: the desktop shell passes the OS setting as
 * RendererProcessVariable.caretBlinkTime (ms per phase, 0 = off; desktop-apps
 * utils.cpp / ASCEditorJSVariables.mm), AscCommon.getCaretBlinkInterval reads
 * it, the cell editor does not start its blink timer at 0, and each DrawTarget
 * shows the target instead of toggling it.
 *
 * This extracts the real helpers (common/editorscommon.js), the real
 * CellEditor.prototype._showCursor, and the real TargetStart / DrawTarget of the
 * four DrawingDocuments by brace matching, runs them against stubs with a fake
 * timer, and watches the caret over a number of ticks.
 *
 * Claimed: with caretBlinkTime 0 the caret stays visible in all five; with a
 * period the timers use it; without the variable they blink at 500 ms as before.
 * NOT claimed here: that the shell reads the OS setting correctly (desktop-apps,
 * C++/ObjC - checked separately per OS), nor painting in a real browser.
 *
 * RD_REPO overrides the sdkjs checkout; BASELINE=1 reads the sources from
 * BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD: once the
// fix is committed HEAD carries it and the baseline would test nothing.
const BASE_REF = process.env.BASE_REF || 'e4f39b0651^';

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

function extract(text, marker, from) {
	const at = text.indexOf(marker, from || 0);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

/* --- fake timers --- */
let timers = [];
const timerApi = {
	setInterval(fn, ms) { timers.push({ fn, ms }); return timers.length; },
	clearInterval(id) { if (id && timers[id - 1]) timers[id - 1].fn = null; },
};
function tick(n) { for (let k = 0; k < n; k++) for (const t of timers) if (t.fn) t.fn(); }
function liveTimers() { return timers.filter(t => t.fn); }

/* --- the shell's variable and the real helpers --- */
const win = { RendererProcessVariable: undefined };
const common = src('common/editorscommon.js');
const AscCommon = {};
if (common.indexOf('function getCaretBlinkInterval(') !== -1) {
	Object.assign(AscCommon, new Function('window',
		extract(common, 'function getCaretBlinkInterval(') + '\n' +
		extract(common, 'function isCaretBlinkEnabled(') +
		'\nreturn {getCaretBlinkInterval, isCaretBlinkEnabled};')(win));
} else {
	// Baseline: the helpers do not exist. Stand in for the contract the shell relies on,
	// so what fails below is the caret code ignoring the setting, not a missing function.
	AscCommon.getCaretBlinkInterval = () => {
		const v = win.RendererProcessVariable;
		return v && typeof v.caretBlinkTime === 'number' ? v.caretBlinkTime : 500;
	};
	AscCommon.isCaretBlinkEnabled = () => AscCommon.getCaretBlinkInterval() > 0;
}

const settings = [
	{ name: 'blinking off (caretBlinkTime 0)', vars: { caretBlinkTime: 0 }, period: 0 },
	{ name: 'macOS-style off (99999999)', vars: { caretBlinkTime: 99999999 }, period: 0 },
	{ name: 'OS period 250 ms', vars: { caretBlinkTime: 250 }, period: 250 },
	{ name: 'no variable (web, old shell)', vars: undefined, period: 500 },
];

/* Count visible->hidden changes of `visible()` over 12 ticks after `start()`. */
function watch(start, visible) {
	timers = [];
	start();
	const seq = [visible()];
	for (let i = 0; i < 12; i++) { tick(1); seq.push(visible()); }
	return { seq: seq.map(v => (v ? '|' : '_')).join(''), toggles: seq.filter((v, i) => i && v !== seq[i - 1]).length };
}

function check(editor, s, r, intervals) {
	const want = s.period > 0;
	const ok = want ? r.toggles > 0 : (r.toggles === 0 && r.seq[r.seq.length - 1] === '|');
	console.log(`  ${editor.padEnd(14)} ${s.name.padEnd(30)} caret ${r.seq} timers ${JSON.stringify(intervals)}  ${ok ? 'ok' : 'FAILED'}`);
	assert.ok(ok, `${editor}: ${s.name}: caret ${want ? 'must blink' : 'must stay on'}, got ${r.seq}`);
	if (want) assert.ok(intervals.every(ms => ms === s.period), `${editor}: blink period must be ${s.period}, got ${intervals}`);
}

/* 1. The cell editor - the reported case. */
const cellEditorSrc = src('cell/view/CellEditorView.js');
function CellEditor() {
	this.cursorStyle = { display: 'none' };
	this.cursorTID = undefined;
	this.defaults = { blinkInterval: 500 };   // what the constructor sets on the baseline
}
new Function('CellEditor', 'AscCommon', 'window',
	extract(cellEditorSrc, 'CellEditor.prototype._showCursor = function') + ';\n' +
	extract(cellEditorSrc, 'CellEditor.prototype._hideCursor = function') + ';')(CellEditor, AscCommon, timerApi);

/* 2. The DrawingDocuments: run `this.TargetStart = ...` / `this.DrawTarget = ...` with this = oThis. */
function bind(file, names, oThis, extra) {
	const text = src(file);
	const body = names.map(n => {
		const m = new RegExp('this\\.' + n + '\\s*=\\s*function').exec(text);
		assert.ok(m, file + ': ' + n + ' not found');
		return block(text, m.index) + ';';
	}).join('\n');
	const env = Object.assign({ AscCommon, setInterval: timerApi.setInterval, clearInterval: timerApi.clearInterval, oThis }, extra || {});
	new Function(...Object.keys(env), '(function(){' + body + '}).call(oThis);')(...Object.values(env));
}
const api = { isBlurEditor: false, isViewMode: false, isRestrictionView: () => false, isRestrictionForms: () => false };

function visibilityDoc() {
	const d = { m_lTimerTargetId: -1, NeedTarget: true, TargetHtmlElement: { style: { visibility: 'visible' } },
		m_oWordControl: { IsFocus: true, m_oApi: api } };
	d.showTarget = v => { d.TargetHtmlElement.style.visibility = v ? 'visible' : 'hidden'; };
	d.isShowTarget = () => d.TargetHtmlElement.style.visibility === 'visible';
	return d;
}
const docs = {
	word: () => { const d = visibilityDoc(); bind('word/Drawing/DrawingDocument.js', ['TargetStart', 'DrawTarget'], d); return d; },
	pdf: () => {
		const d = visibilityDoc();
		const Asc = { editor: { getPDFDoc: () => ({ GetActiveObject: () => null }) } };
		bind('pdf/src/DrawingDocument.js', ['TargetStart', 'DrawTarget'], d, { Asc });
		return d;
	},
	slide: () => {
		const d = { m_lTimerTargetId: -1, NeedTarget: true, TargetHtmlElement: { style: { display: 'block' } },
			GetSlidesCount: () => 1, TransitionSlide: { IsPlaying: () => false }, m_oWordControl: { m_oApi: api } };
		bind('slide/Drawing/DrawingDocument.js', ['TargetStart', 'DrawTarget'], d);
		d.isShowTarget = () => d.TargetHtmlElement.style.display === 'block';
		return d;
	},
	'cell drawing': () => {
		const d = { m_lTimerTargetId: -1, NeedTarget: true, TargetHtmlElement: { style: { display: 'block' } } };
		bind('cell/model/DrawingObjects/DrawingDocument.js', ['TargetStart', 'DrawTarget'], d);
		d.isShowTarget = () => d.TargetHtmlElement.style.display === 'block';
		return d;
	},
};

for (const s of settings) {
	win.RendererProcessVariable = s.vars;

	const ce = new CellEditor();
	const r = watch(() => ce._showCursor(), () => ce.cursorStyle.display === 'block');
	check('cell editor', s, r, liveTimers().map(t => t.ms));
	ce._hideCursor();
	assert.strictEqual(ce.cursorStyle.display, 'none', 'leaving the cell still hides the caret');
	assert.strictEqual(liveTimers().length, 0, 'leaving the cell stops its timer');

	for (const name of Object.keys(docs)) {
		const d = docs[name]();
		// (pdf's TargetStart takes bShowHide; its callers pass true, the others ignore it)
		const rr = watch(() => { d.TargetStart(true); d.m_lTimerTargetId = timers.length; }, () => d.isShowTarget());
		// the target timer keeps running even with blinking off: other code reads it as "target active"
		assert.strictEqual(liveTimers().length, 1, name + ': TargetStart must still start the target timer');
		check(name, s, rr, liveTimers().map(t => t.ms));
	}
}

console.log('PASS #2508: the editors\' carets follow the OS blink setting' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
