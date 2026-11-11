/*
 * #1194 - touchpad scrolling in a document is not smooth: it moves in jerks,
 * while the scrollbar (and the help pages) scroll smoothly.
 *
 * Two causes. The paint side - a scroll was repainted at most every 40ms - was
 * fixed by #2375 (see issue-2375-scroll-paint-rate-test.js). This test covers the
 * input side: the word editor turns each wheel event into a scroll distance in
 * AscCommon.checkMouseWhell (common/Drawings/WorkEvents.js) as
 * -45 * wheelDeltaY / 120 and then cuts it to whole pixels (deltaY >>= 0),
 * event by event. A mouse notch (wheelDelta 120) gives exactly 45px, but a
 * touchpad sends many small events - Chromium's wheelDeltaY is the touchpad's
 * pixel delta times 120/40 on macOS (and roughly the pixel delta on Linux and
 * Windows precision touchpads), as an integer - so each event lost up to a
 * pixel: a slow drag or the end of a momentum fling did not move the page at
 * all, and the rest moved in uneven 0/1/2px steps.
 *
 * Fix: the word editor keeps the cut-off fraction (CEditorPage.wheelRemainder)
 * and checkMouseWhell carries it into the next event (reset when the direction
 * changes or the axis is not scrolled). Other editors do not pass a remainder
 * and are unchanged; a mouse notch still scrolls exactly 45px.
 *
 * This extracts the real checkMouseWhell, the real CEditorPage.onMouseWhell and
 * the wheelRemainder initialiser from word/Drawing/HtmlPage.js, and feeds them
 * wheel events (only wheelDeltaY matters to this code):
 *   1. slow touchpad drag: 40 events of wheelDeltaY -3 (1px on a Mac) -> the
 *      page must move 45 * 3 * 40 / 120 = 45px (baseline: 40px; with -2: 0px);
 *   2. momentum fling decaying 60 -> 1 -> total within 1px of the exact sum and
 *      no event of the moving tail scrolls 0px while the sum says it should
 *      have moved by then;
 *   3. mouse wheel: 5 notches of 120 -> exactly 225px, 45px each;
 *   4. reversing direction does not carry the old fraction over.
 * NOT claimed: the wheelDeltaY values a real touchpad produces (modelled from
 * Chromium's conversion, not captured: CDP's synthetic wheel events carry no
 * wheelDelta at all), nor how the result feels - that needs a GUI check with a
 * real touchpad on macOS/Linux/Windows.
 *
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs). BASELINE=1 reads the
 * sources from BASE_REF (default: parent of the fix commit) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || 'aa8e849c33^';

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

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const events = src('common/Drawings/WorkEvents.js');
const page = src('word/Drawing/HtmlPage.js');

const checkMouseWhell = new Function(extract(events, 'function checkMouseWhell(') + '\nreturn checkMouseWhell;')();
const remainderInit = (/^\s*(this\.wheelRemainder\s*=[^;]*;)/m.exec(page) || [])[1] || '';

function makeEditor() {
	const scrolled = [];
	const wc = {
		m_oApi: { bInit_word_control: true },
		MouseHandObject: null,
		m_bIsHorScrollVisible: false,
		m_oScrollVerApi: { scrollBy(x, y) { scrolled.push(y); } },
		m_oScrollHorApi: { scrollBy(x) { scrolled.push('h' + x); } },
		onMouseMove() {},
	};
	new Function(remainderInit).call(wc);
	const global_mouseEvent = { X: 0, Y: 0 };
	new Function('oThis', 'AscCommon', 'window', 'global_mouseEvent',
		extract(page, 'this.onMouseWhell = function') + ';'
	).call(wc, wc, { checkMouseWhell: checkMouseWhell }, {}, global_mouseEvent);
	return {
		wheel(wheelDeltaY) {
			const before = scrolled.length;
			wc.onMouseWhell({ wheelDelta: wheelDeltaY, wheelDeltaY: wheelDeltaY, wheelDeltaX: 0, preventDefault() {} });
			return scrolled.length > before ? scrolled[scrolled.length - 1] : 0;
		},
	};
}

const sum = (a) => a.reduce((s, v) => s + v, 0);
const failed = [];
function check(cond, msg) { if (!cond) failed.push(msg); }

/* 1. slow drag */
for (const wd of [-3, -2]) {
	const ed = makeEditor();
	const steps = [];
	for (let i = 0; i < 40; i++) steps.push(ed.wheel(wd));
	const exact = -45 * wd * 40 / 120;
	console.log(`slow drag, 40 x wheelDeltaY ${wd}: scrolled ${sum(steps)}px (exact ${exact}px), steps ${[...new Set(steps)].join('/')}`);
	check(Math.abs(sum(steps) - exact) < 1, `slow drag ${wd}: scrolled ${sum(steps)}px instead of ${exact}px`);
}

/* 2. momentum fling: wheelDeltaY decays from -60 to -1 */
{
	const ed = makeEditor();
	const deltas = [];
	for (let v = 60; v >= 1; v = Math.floor(v * 0.9)) deltas.push(-v);
	for (let i = 0; i < 12; i++) deltas.push(-1);
	const steps = deltas.map((d) => ed.wheel(d));
	const exact = sum(deltas.map((d) => -45 * d / 120));
	let stalls = 0, acc = 0, done = 0;
	steps.forEach((s, i) => { acc += -45 * deltas[i] / 120; done += s; if (s === 0 && acc - done >= 1) stalls++; });
	console.log(`fling, ${deltas.length} events: scrolled ${sum(steps)}px (exact ${exact.toFixed(2)}px), events that should have moved but did not: ${stalls}`);
	check(Math.abs(sum(steps) - exact) < 1, `fling scrolled ${sum(steps)}px instead of ${exact.toFixed(2)}px`);
	check(stalls === 0, `${stalls} events of the fling did not move although a whole pixel was due`);
}

/* 3. mouse wheel notches */
{
	const ed = makeEditor();
	const steps = [];
	for (let i = 0; i < 5; i++) steps.push(ed.wheel(-120));
	console.log(`mouse wheel 5 notches: ${steps.join(' ')}`);
	check(steps.every((s) => s === 45), 'a mouse notch must scroll exactly 45px');
}

/* 4. reverse direction */
{
	const ed = makeEditor();
	ed.wheel(-3); ed.wheel(-3); ed.wheel(-3);       // 1.125px each, fraction kept
	const back = ed.wheel(120);                      // one notch up
	console.log(`reverse after a drag: ${back}px`);
	check(back === -45, `reversing carried the old fraction: ${back}px instead of -45px`);
}

if (failed.length) {
	failed.forEach((m) => console.log('FAIL: ' + m));
	process.exit(1);
}
console.log('PASS #1194: touchpad deltas are applied in full, no sub-pixel loss per event' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
