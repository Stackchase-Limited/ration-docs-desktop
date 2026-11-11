/*
 * #2375 - scrolling a document on macOS lags: the page is redrawn at 20-25fps
 * while the trackpad delivers 120 scroll events a second, so the text moves
 * in 20-30px steps (ONLYOFFICE measured 25-30fps in the reporter's video).
 *
 * Cause: the word paint loop (AscCommon.PaintMessageLoop in
 * common/Drawings/WorkEvents.js) runs on requestAnimationFrame but only calls
 * its engine when 40ms have passed since the last call. A scroll only sets
 * m_bIsScroll (CEditorPage.verticalScroll -> OnScroll), so it waits for the
 * next 40ms slot: every 5th frame at 120Hz (24fps), every 3rd at 60Hz.
 *
 * This extracts the real PaintMessageLoop (constructor, Start, _animation),
 * the real CEditorPage.verticalScroll, OnScroll, onTimerScroll_internal and,
 * when present, the paintMessageLoop.isNeedImmediate hook from
 * word/Drawing/HtmlPage.js, and drives them with a virtual 120Hz
 * requestAnimationFrame and clock:
 *   1. trackpad: one 5px scroll per frame for 1s -> a scroll paint every frame
 *      (fails on the parent: 24 paints, 25-30px per paint);
 *   2. mouse wheel: 45px notches every 100ms -> same distance, one paint each;
 *   3. idle: the engine's housekeeping still runs every 40ms (25/s), not 120/s;
 *   4. non-scroll repaints (OnScroll without a position change, e.g. typing or
 *      recalculation) keep the 40ms cadence.
 * NOT claimed: how fast a real page draws (measured separately in headless
 * Chromium: <1ms per paint for a 400-paragraph document) or how it feels on a
 * ProMotion display - that needs the Mac app with a real trackpad.
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
const BASE_REF = process.env.BASE_REF || 'd275009164^';

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

function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return '';
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const events = src('common/Drawings/WorkEvents.js');
const page = src('word/Drawing/HtmlPage.js');

const intervalMatch = /this\.paintMessageLoop = new AscCommon\.PaintMessageLoop\((\d+), api\)/.exec(page);
assert(intervalMatch, 'word paint loop construction not found');
const INTERVAL = +intervalMatch[1];

const FRAME = 1000 / 120;

function run(scenario) {
	/* virtual clock + requestAnimationFrame */
	let now = 1000000;
	let rafCb = null;
	// timers: since #1000 the loop sleeps on a timer between engine runs
	let timers = [];
	let timerSeq = 0;
	const window = {
		requestAnimationFrame(cb) { rafCb = cb; return 1; },
		cancelAnimationFrame() { rafCb = null; },
		setTimeout(cb, ms) { const id = ++timerSeq; timers.push({ id: id, at: now + Math.max(0, ms || 0), cb: cb }); return id; },
		clearTimeout(id) { timers = timers.filter((t) => t.id !== id); },
	};
	const FakeDate = { now: () => Math.floor(now) };
	const AscCommon = { AscBrowser: { isChrome: true, isSafari: false } };

	const PaintMessageLoop = new Function('window', 'AscCommon', 'Date',
		extract(events, 'function PaintMessageLoop(') + '\n' +
		extract(events, 'PaintMessageLoop.prototype.Start = function') + ';\n' +
		extract(events, 'PaintMessageLoop.prototype._animation = function') + ';\n' +
		extract(events, 'PaintMessageLoop.prototype._sleepEnd = function', true) + ';\n' +
		extract(events, 'PaintMessageLoop.prototype.wake = function', true) + ';\n' +
		'return PaintMessageLoop;')(window, AscCommon, FakeDate);

	const api = { isMobileVersion: false, bInit_word_control: true, isLockTargetUpdate: true,
		isLongAction: () => false, sendEvent(name) { if (name === 'asc_onPaintTimer') stats.engine++; } };
	const stats = { engine: 0, paints: [] };
	const wc = {
		m_oApi: api, m_bIsScroll: false, m_bIsRePaintOnScroll: true, m_dScrollY: 0, m_oLogicDocument: null,
		m_oDrawingDocument: { Collaborative_TargetsUpdate() {} },
		OnCalculatePagesPlace() {},
		OnPaint() { stats.paints.push(this.m_dScrollY); },
		paintMessageLoop: new PaintMessageLoop(INTERVAL, api),
	};
	new Function('oThis', 'AscCommon',
		extract(page, 'this.paintMessageLoop.isNeedImmediate = function', true) + ';\n' +
		extract(page, 'this.verticalScroll = function') + ';\n' +
		extract(page, 'this.OnScroll       = function') + ';\n' +
		extract(page, 'this.onTimerScroll_internal = function') + ';\n'
	).call(wc, wc, AscCommon);

	wc.paintMessageLoop.Start(wc.onTimerScroll_internal.bind(wc));
	const start = now;
	for (let f = 1; f <= 120; f++) {
		const frameAt = start + f * FRAME;
		for (;;) {
			const due = timers.filter((t) => t.at <= frameAt).sort((x, z) => x.at - z.at || x.id - z.id)[0];
			if (!due) break;
			timers = timers.filter((t) => t !== due);
			now = due.at;
			due.cb();
		}
		now = frameAt;
		scenario(wc, f);
		if (rafCb) { const cb = rafCb; rafCb = null; cb(); }
	}
	return stats;
}

const MAX_Y = 100000;
const steps = ps => ps.slice(1).map((y, i) => Math.abs(y - ps[i]));

/* 1. trackpad: 5px per 120Hz frame */
let y = 0;
const tp = run((wc) => { y += 5; wc.verticalScroll(null, y, MAX_Y); });
const tpScroll = tp.paints.filter((p, i) => i === 0 || p !== tp.paints[i - 1]);
const tpMaxStep = Math.max(...steps(tpScroll));
console.log(`trackpad 120Hz, 1s: scroll paints=${tpScroll.length}, max px per paint=${tpMaxStep}, engine runs=${tp.engine}`);

/* 2. mouse wheel: 45px notch every 100ms (12 frames) */
y = 0;
const mw = run((wc, f) => { if (f % 12 === 0) { y += 45; wc.verticalScroll(null, y, MAX_Y); } });
console.log(`mouse wheel 10 notches: paints=${mw.paints.length}, final y=${mw.paints[mw.paints.length - 1]}`);

/* 3. idle */
const idle = run(() => {});
console.log(`idle 1s: engine runs=${idle.engine}`);

/* 4. repaint request without a scroll (typing, recalculation) every frame */
const other = run((wc) => { wc.OnScroll(); });
console.log(`non-scroll repaint each frame: paints=${other.paints.length}`);

assert.strictEqual(mw.paints.length, 10, 'each wheel notch is painted once');
assert.strictEqual(mw.paints[mw.paints.length - 1], 450, 'wheel distance unchanged');
assert(idle.engine <= 26, 'idle housekeeping must keep the 40ms cadence, ran ' + idle.engine);
assert(other.paints.length <= 26, 'non-scroll repaints must keep the 40ms cadence, painted ' + other.paints.length);
assert(tpScroll.length >= 115, `trackpad scroll painted only ${tpScroll.length} of 120 frames (40ms gate)`);
assert(tpMaxStep <= 5, `trackpad scroll jumps ${tpMaxStep}px between paints`);

console.log('PASS #2375: a scroll is repainted on the next animation frame' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
