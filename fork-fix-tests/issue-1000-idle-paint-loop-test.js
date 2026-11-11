/*
 * #1000 - an idle document (and an idle presentation) costs far more CPU than an
 * idle spreadsheet, per open document.
 *
 * Cause: the paint loop of the word, slide and visio editors
 * (AscCommon.PaintMessageLoop in common/Drawings/WorkEvents.js) asks for
 * requestAnimationFrame on every frame, forever, only to check whether 40ms
 * have passed since the engine last ran. An idle document therefore woke the
 * renderer 60-120 times a second (72/s measured on a Mac) and kept the
 * compositor producing frames; the engine itself ran 25 times a second and
 * costs well under 1ms. The spreadsheet editor has no such loop.
 * Measured in the macOS test app (blank docx, 40s windows, renderer process):
 * 3.2-3.6% idle; with the per-frame request gone 0.3-0.4%, GPU process
 * 0.6-1.3% -> 0%.
 *
 * Fix: between two runs of the engine the loop sleeps on a timer that runs the
 * engine itself; a frame is requested only when the word editor's scroll wakes
 * it (#2375 keeps a scroll painted on the next frame) or the view is hidden
 * (requestAnimationFrame then does not fire until the tab is shown again).
 *
 * This extracts the real PaintMessageLoop (constructor, Start, Stop,
 * _animation and, when present, _sleepEnd and wake) and the real
 * CEditorPage.verticalScroll, OnScroll, onTimerScroll_internal and the
 * isNeedImmediate hook from word/Drawing/HtmlPage.js, and runs them on a
 * virtual 120Hz clock with virtual timers. It counts, per idle second, how often
 * the renderer is woken (frames + timers) and how often the engine runs:
 *   1. idle, visible: at most 26 wakeups a second (was 120), engine still ~25/s;
 *   2. idle, hidden tab: nothing runs (no timer keeps a background tab busy);
 *   3. trackpad scroll (5px per frame): still painted on every frame (#2375);
 *   4. mouse wheel: each notch painted once, same distance;
 *   5. after a scroll the loop goes back to sleep.
 * NOT claimed: the CPU percentages above (they come from the GUI app, not from
 * this test), Linux/Windows numbers, or the cost of the caret blink timer.
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
const BASE_REF = process.env.BASE_REF || '0bd49ef617^';

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

function run(scenario, opts) {
	opts = opts || {};
	/* virtual clock, 120Hz requestAnimationFrame, timers */
	let now = 1000000;
	let rafCb = null;
	let timers = [];
	let timerSeq = 0;
	const stats = { frames: 0, timers: 0, engine: 0, paints: [] };
	const document = { hidden: !!opts.hidden };
	const window = {
		document: document,
		requestAnimationFrame(cb) { rafCb = cb; return 1; },
		cancelAnimationFrame() { rafCb = null; },
		setTimeout(cb, ms) { const id = ++timerSeq; timers.push({ id: id, at: now + Math.max(0, ms || 0), cb: cb }); return id; },
		clearTimeout(id) { timers = timers.filter((t) => t.id !== id); },
	};
	const FakeDate = { now: () => Math.floor(now) };
	const AscCommon = { AscBrowser: { isChrome: true, isSafari: false } };

	const PaintMessageLoop = new Function('window', 'AscCommon', 'Date', 'setTimeout', 'clearTimeout', 'document',
		extract(events, 'function PaintMessageLoop(') + '\n' +
		extract(events, 'PaintMessageLoop.prototype.Start = function') + ';\n' +
		extract(events, 'PaintMessageLoop.prototype.Stop = function') + ';\n' +
		extract(events, 'PaintMessageLoop.prototype._animation = function') + ';\n' +
		extract(events, 'PaintMessageLoop.prototype._sleepEnd = function', true) + ';\n' +
		extract(events, 'PaintMessageLoop.prototype.wake = function', true) + ';\n' +
		'return PaintMessageLoop;')(window, AscCommon, FakeDate, window.setTimeout, window.clearTimeout, document);

	const api = { isMobileVersion: false, bInit_word_control: true, isLockTargetUpdate: true,
		isLongAction: () => false, sendEvent(name) { if (name === 'asc_onPaintTimer') stats.engine++; } };
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
	const perFrame = [];
	for (let f = 1; f <= 120; f++) {
		const frameAt = start + f * FRAME;
		/* timers due before this frame, in order */
		for (;;) {
			const due = timers.filter((t) => t.at <= frameAt).sort((a, b) => a.at - b.at || a.id - b.id)[0];
			if (!due) break;
			timers = timers.filter((t) => t !== due);
			now = due.at;
			stats.timers++;
			due.cb();
		}
		now = frameAt;
		scenario(wc, f);
		const engineBefore = stats.engine;
		if (rafCb && !document.hidden) {
			const cb = rafCb; rafCb = null;
			stats.frames++;
			cb();
		}
		perFrame.push(stats.engine - engineBefore);
	}
	stats.wakeups = stats.frames + stats.timers;
	stats.loop = wc.paintMessageLoop;
	return stats;
}

const MAX_Y = 100000;
const steps = (ps) => ps.slice(1).map((y, i) => Math.abs(y - ps[i]));
let failed = [];
function check(cond, msg) { if (!cond) failed.push(msg); }

/* 1. idle, visible */
const idle = run(() => {});
console.log(`idle 1s (visible): wakeups=${idle.wakeups} (frames=${idle.frames}, timers=${idle.timers}), engine runs=${idle.engine}`);
check(idle.wakeups <= 26, `idle document woke the renderer ${idle.wakeups} times in 1s (one frame request per frame)`);
check(idle.engine >= 23 && idle.engine <= 26, `idle housekeeping must keep the 40ms cadence, ran ${idle.engine}`);

/* 2. idle, hidden tab */
const hidden = run(() => {}, { hidden: true });
console.log(`idle 1s (hidden tab): wakeups=${hidden.wakeups} (frames=${hidden.frames}, timers=${hidden.timers}), engine runs=${hidden.engine}`);
check(hidden.wakeups <= 1 && hidden.engine <= 1, `a hidden tab kept running (${hidden.wakeups} wakeups, ${hidden.engine} engine runs)`);

/* 3. trackpad: 5px per 120Hz frame */
let y = 0;
const tp = run((wc) => { y += 5; wc.verticalScroll(null, y, MAX_Y); });
const tpScroll = tp.paints.filter((p, i) => i === 0 || p !== tp.paints[i - 1]);
const tpMaxStep = Math.max(...steps(tpScroll));
console.log(`trackpad 120Hz, 1s: scroll paints=${tpScroll.length}, max px per paint=${tpMaxStep}`);
check(tpScroll.length >= 115, `trackpad scroll painted only ${tpScroll.length} of 120 frames`);
check(tpMaxStep <= 5, `trackpad scroll jumps ${tpMaxStep}px between paints`);

/* 4. mouse wheel: 45px notch every 100ms (12 frames) */
y = 0;
const mw = run((wc, f) => { if (f % 12 === 0) { y += 45; wc.verticalScroll(null, y, MAX_Y); } });
console.log(`mouse wheel 10 notches: paints=${mw.paints.length}, final y=${mw.paints[mw.paints.length - 1]}, wakeups=${mw.wakeups}`);
check(mw.paints.length === 10, 'each wheel notch is painted once');
check(mw.paints[mw.paints.length - 1] === 450, 'wheel distance unchanged');
check(mw.wakeups <= 40, `wheel scrolling 10 notches woke the renderer ${mw.wakeups} times`);

/* 5. after a burst of scrolling the loop sleeps again */
y = 0;
const burst = run((wc, f) => { if (f <= 30) { y += 5; wc.verticalScroll(null, y, MAX_Y); } });
console.log(`30-frame scroll then idle: frames=${burst.frames}, timers=${burst.timers}`);
check(burst.frames <= 32, `after the scroll stopped the loop still asked for ${burst.frames - 30} more frames`);

if (failed.length) {
	failed.forEach((m) => console.log('FAIL: ' + m));
	process.exit(1);
}
console.log('PASS #1000: an idle document no longer asks for every animation frame' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
