/*
 * #1925 - "Implement Smooth Scrolling like MS Office": scrolling a document
 * with a mouse wheel moves in visible steps where Word glides.
 *
 * Already done before this: #2375 (a scroll repaints on the next frame, not
 * every 40 ms) and #1194 (touchpad sub-pixel deltas are carried over), so a
 * touchpad scrolls smoothly. Left: sdkjs word/Drawing/HtmlPage.js onMouseWhell
 * passed each mouse-wheel notch (wheelDelta 120 -> 45 px) to
 * m_oScrollVerApi.scrollBy in one call, so the page jumped 45 px in one frame.
 * Fix (opt-in, api.asc_setSmoothWheelScroll, Advanced settings checkbox in the
 * document editor, off by default): a notch is handed to smoothWheelScroll,
 * which spreads it over the next animation frames (35% of the rest per frame,
 * ease-out); further notches add to it; a notch the other way drops the rest.
 *
 * This test extracts the REAL onMouseWhell, isMouseWheelNotch,
 * smoothWheelScroll and the smoothWheel/wheelRemainder initialisers from
 * HtmlPage.js, the REAL checkMouseWhell from common/Drawings/WorkEvents.js and
 * asc_setSmoothWheelScroll from common/apiBase.js, runs them with a stub
 * scroll object and virtual animation frames, and checks:
 *  1. option on, one notch: nothing jumps in the event itself, the 45 px are
 *     spread over >= 5 frames, decreasing, summing to exactly 45
 *     (baseline: one 45 px step -> FAILS);
 *  2. option on, three quick notches: 135 px in total, no single step > 45;
 *  3. option on, a notch down then up: the rest of the first is dropped;
 *  4. option on, touchpad deltas (wheelDeltaY -3): applied at once as before;
 *  5. option off (default): one 45 px step per notch, as before;
 *  6. web-apps: the DE Advanced settings checkbox is stored as
 *     de-settings-smooth-wheel and passed to asc_setSmoothWheelScroll on load
 *     and on apply (only when RD_WEBAPPS is given or ../web-apps exists).
 *
 * NOT claimed: how it feels (needs a GUI check with a real mouse on Windows/
 * Linux/macOS); presentation, spreadsheet and PDF editors are unchanged.
 *
 * Env: RD_REPO     sdkjs checkout (default ../sdkjs)
 *      RD_WEBAPPS  web-apps checkout (default ../web-apps)
 *      BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEB = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '61fae925c0^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || 'bcdb51112f^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
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
function extractOpt(text, marker) {
	const at = text.indexOf(marker);
	return at === -1 ? '' : block(text, at) + ';\n';
}

const events = src(SDKJS, BASE_REF, 'common/Drawings/WorkEvents.js');
const page = src(SDKJS, BASE_REF, 'word/Drawing/HtmlPage.js');
const apiBase = src(SDKJS, BASE_REF, 'common/apiBase.js');

const checkMouseWhell = new Function(block(events, events.indexOf('function checkMouseWhell(')) + '\nreturn checkMouseWhell;')();
const inits = ['wheelRemainder', 'smoothWheel']
	.map((n) => (new RegExp('^\\s*(this\\.' + n + '\\s*=[^;]*;)', 'm').exec(page) || [])[1] || '').join('\n');
const methods = extractOpt(page, 'this.onMouseWhell = function') +
	extractOpt(page, 'this.isMouseWheelNotch = function') +
	extractOpt(page, 'this.smoothWheelScroll = function');

function makeEditor(smooth) {
	const steps = [];   // [frame, px]
	let frames = [], frameNo = 0;
	const win = { requestAnimationFrame(f) { frames.push(f); return frames.length; } };
	const api = { bInit_word_control: true };
	const setter = extractOpt(apiBase, 'baseEditorsApi.prototype["asc_setSmoothWheelScroll"] = function');
	if (setter) {
		const proto = {};
		new Function('baseEditorsApi', setter)({ prototype: proto });
		proto['asc_setSmoothWheelScroll'].call(api, smooth);
	} else {
		api.isSmoothWheelScroll = smooth;   // baseline: no setter; the flag alone changes nothing
	}
	const wc = {
		m_oApi: api,
		MouseHandObject: null,
		m_bIsHorScrollVisible: false,
		m_oScrollVerApi: { scrollBy(x, y) { steps.push([frameNo, y]); } },
		m_oScrollHorApi: { scrollBy() {} },
		onMouseMove() {},
	};
	new Function(inits).call(wc);
	new Function('oThis', 'AscCommon', 'window', 'global_mouseEvent', methods)
		.call(wc, wc, { checkMouseWhell }, win, { X: 0, Y: 0 });
	return {
		steps,
		wheel(wd) { wc.onMouseWhell({ wheelDelta: wd, wheelDeltaY: wd, wheelDeltaX: 0, preventDefault() {} }); },
		frame() { frameNo++; const fs_ = frames; frames = []; fs_.forEach((f) => f(frameNo * 16)); },
		run() { for (let i = 0; i < 200 && frames.length; i++) this.frame(); },
	};
}
const sum = (a) => a.reduce((s, v) => s + v[1], 0);

let failed = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failed++; console.log('FAIL ' + label + ': ' + e.message); }
}

check('smooth on: one notch spread over frames, 45 px in total', () => {
	const ed = makeEditor(true);
	ed.wheel(-120);
	const inEvent = ed.steps.filter((s) => s[0] === 0).map((s) => s[1]);
	ed.run();
	console.log('     steps (frame:px): ' + ed.steps.map((s) => s[0] + ':' + s[1]).join(' '));
	assert.deepStrictEqual(inEvent, [], 'the notch jumped inside the wheel event: ' + inEvent.join(','));
	assert.strictEqual(sum(ed.steps), 45);
	assert.ok(ed.steps.length >= 5, 'only ' + ed.steps.length + ' steps');
	for (let i = 1; i < ed.steps.length; i++) assert.ok(ed.steps[i][1] <= ed.steps[i - 1][1], 'steps not decreasing');
});

check('smooth on: three quick notches add up, no step above 45 px', () => {
	const ed = makeEditor(true);
	ed.wheel(-120); ed.frame(); ed.wheel(-120); ed.wheel(-120);
	ed.run();
	assert.strictEqual(sum(ed.steps), 135);
	assert.ok(ed.steps.every((s) => Math.abs(s[1]) <= 45), 'a step above one notch');
});

check('smooth on: reversing drops what was left', () => {
	const ed = makeEditor(true);
	ed.wheel(-120); ed.frame();
	const done = sum(ed.steps);
	ed.wheel(120);
	ed.run();
	assert.ok(done > 0 && done < 45, 'first frame moved ' + done);
	assert.strictEqual(sum(ed.steps), done - 45, 'reverse notch did not start afresh');
});

check('smooth on: touchpad deltas applied at once (unchanged)', () => {
	const ed = makeEditor(true);
	for (let i = 0; i < 8; i++) ed.wheel(-8);
	assert.strictEqual(sum(ed.steps), 24);
	assert.ok(ed.steps.every((s) => s[0] === 0), 'touchpad deltas were deferred');
});

check('smooth off (default): one 45 px jump per notch (unchanged)', () => {
	const ed = makeEditor(false);
	ed.wheel(-120); ed.run();
	assert.deepStrictEqual(ed.steps, [[0, 45]]);
});

if (fs.existsSync(path.join(WEB, 'apps/documenteditor'))) {
	check('web-apps: DE Advanced settings checkbox wired to asc_setSmoothWheelScroll', () => {
		const panels = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/view/FileMenuPanels.js');
		const main = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/controller/Main.js');
		const left = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/controller/LeftMenu.js');
		const en = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/locale/en.json');
		assert.ok(/fms-chb-smooth-wheel/.test(panels) && /setBool\("de-settings-smooth-wheel"/.test(panels), 'no checkbox / storage');
		assert.ok(/getBool\("de-settings-smooth-wheel"\)/.test(main) && /asc_setSmoothWheelScroll\(/.test(main), 'not applied on load');
		assert.ok(/asc_setSmoothWheelScroll\(/.test(left), 'not applied on settings apply');
		assert.ok(/"DE\.Views\.FileMenuPanels\.Settings\.txtSmoothWheel":/.test(en), 'no en.json string');
	});
}

if (failed) { console.log(failed + ' check(s) failed'); process.exit(1); }
console.log('PASS #1925 smooth mouse-wheel scrolling (opt-in)');
