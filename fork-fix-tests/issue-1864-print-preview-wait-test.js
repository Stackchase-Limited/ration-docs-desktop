/*
 * #1864 - "Progress Indicator / Notification When Generating Large Print
 * Previews": File > Print on a 35,000 x 50 spreadsheet built a 460-page preview
 * with nothing on screen for a long time; users took it for a hang.
 *
 * Cause: web-apps apps/spreadsheeteditor/main/app/controller/Print.js
 * onShowMainSettingsPrint called api.asc_initPrintPreview (sdkjs cell/api.js,
 * WorkbookView.calcPagesPrint over every page) and then updatePreview
 * synchronously in the panel's show handler, so no message could be painted.
 * Fix: sdkjs asc_getPrintPreviewCellsCount gives the used rows x columns over
 * the visible sheets; at or above LARGE_PREVIEW_CELLS the controller shows a
 * LoadMask "Creating the print preview, please wait..." and builds the preview
 * (old body, now _showMainSettingsPrint) after a timer; small workbooks keep
 * the synchronous path; closing the panel first cancels the build.
 *
 * This test extracts the REAL controller methods (onShowMainSettingsPrint,
 * _showMainSettingsPrint, onHidePrintMenu, the two constants) and the REAL
 * asc_getPrintPreviewCellsCount, runs them on stubs with virtual timers and
 * checks:
 *  1. the API count: visible sheets' rows x cols summed, hidden sheet skipped;
 *  2. large workbook: the mask is shown BEFORE asc_initPrintPreview runs, the
 *     init happens only after the timer, and the mask is then hidden
 *     (baseline: init runs inside the show handler with no mask -> FAILS);
 *  3. small workbook: init runs synchronously, no mask (unchanged);
 *  4. panel closed before the timer: no preview is built, mask hidden;
 *  5. the en.json string exists.
 *
 * NOT claimed: how long a real preview takes (threshold 500,000 cells is a
 * judgement, not measured) or that the mask looks right (not GUI-checked).
 *
 * Env: RD_REPO   web-apps checkout (default ../web-apps)
 *      RD_SDKJS  sdkjs checkout (default ../sdkjs)
 *      BASELINE=1 reads sources from BASE_REF / SDKJS_BASE_REF; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEB = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const SDKJS = path.resolve(process.env.RD_SDKJS || path.join(__dirname, '..', 'sdkjs'));
const BASE_REF = process.env.BASE_REF || '1ecc12124b^';
const SDKJS_BASE_REF = process.env.SDKJS_BASE_REF || '5f7ad1f89c^';

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
function method(text, name) {
	const at = text.indexOf('\n        ' + name + ': function');
	if (at === -1) return null;
	return block(text, at + 1).replace(/^\s*[\w$]+: /, '');
}

const ctl = src(WEB, BASE_REF, 'apps/spreadsheeteditor/main/app/controller/Print.js');
const api = src(SDKJS, SDKJS_BASE_REF, 'cell/api.js');
const en = src(WEB, BASE_REF, 'apps/spreadsheeteditor/main/locale/en.json');

let failed = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failed++; console.log('FAIL ' + label + ': ' + e.message); }
}

// virtual timers
let timers = [];
const setTimeout_ = (fn, ms) => { const t = { fn, ms, live: true }; timers.push(t); return t; };
const clearTimeout_ = (t) => { if (t) t.live = false; };
function runTimers() { const ts = timers; timers = []; ts.forEach(t => t.live && t.fn()); }

function makeController(cells) {
	const log = [];
	const Common = { UI: { LoadMask: function (o) {
		this.setTitle = (t) => log.push('mask:title ' + t);
		this.show = () => log.push('mask:show');
		this.hide = () => log.push('mask:hide');
	} } };
	const c = {
		printSettings: { $el: {}, visible: true, isVisible() { return this.visible; } },
		api: {
			asc_getPrintPreviewCellsCount: () => cells,
			asc_closePrintPreview: () => log.push('close'),
		},
		txtPreparingPreview: 'wait', LARGE_PREVIEW_CELLS: 500000,
	};
	const names = ['onShowMainSettingsPrint', '_showMainSettingsPrint', 'onHidePrintMenu'];
	for (const n of names) {
		const body = method(ctl, n);
		if (body) c[n] = new Function('Common', 'setTimeout', 'clearTimeout', 'return ' + body)(Common, setTimeout_, clearTimeout_);
	}
	const m = /LARGE_PREVIEW_CELLS:\s*(\d+)/.exec(ctl);
	if (m) c.LARGE_PREVIEW_CELLS = +m[1];
	// the preview build itself (the old body) is replaced by a probe: it is the real
	// method's job to call it; its own contents were not changed
	const build = () => { log.push('init'); c._isPreviewVisible = true; };
	if (c._showMainSettingsPrint) c._showMainSettingsPrint = build;
	else c.onShowMainSettingsPrint = build;   // baseline: the build is the show handler
	return { c, log };
}

check('API: used rows x cols over the visible sheets', () => {
	const at = api.indexOf('spreadsheet_api.prototype.asc_getPrintPreviewCellsCount = function');
	assert.ok(at !== -1, 'asc_getPrintPreviewCellsCount not found');
	const fn = new Function('return ' + block(api, at).replace(/^[^=]+=\s*/, ''))();
	const sheets = [{ nRowsCount: 35000, nColsCount: 50, getHidden: () => false },
		{ nRowsCount: 1000, nColsCount: 1000, getHidden: () => true },
		{ nRowsCount: 10, nColsCount: 5, getHidden: () => false }];
	const self = { wbModel: { getWorksheetCount: () => sheets.length, getWorksheet: (i) => sheets[i] } };
	assert.strictEqual(fn.call(self), 35000 * 50 + 50);
	assert.ok(/prot\["asc_getPrintPreviewCellsCount"\]/.test(api), 'not exported');
});

check('large workbook: wait message shown before the preview is built', () => {
	timers = [];
	const { c, log } = makeController(35000 * 50);
	c.onShowMainSettingsPrint();
	console.log('     during show handler: ' + JSON.stringify(log));
	assert.ok(log.includes('mask:show'), 'no wait message');
	assert.ok(!log.includes('init'), 'preview built inside the show handler, before anything can paint');
	runTimers();
	console.log('     after the timer:     ' + JSON.stringify(log));
	assert.deepStrictEqual(log.slice(log.indexOf('mask:show')), ['mask:show', 'init', 'mask:hide']);
});

check('small workbook: built synchronously, no mask (unchanged)', () => {
	timers = [];
	const { c, log } = makeController(200 * 20);
	c.onShowMainSettingsPrint();
	assert.deepStrictEqual(log, ['init']);
	assert.strictEqual(timers.length, 0);
});

check('panel closed before the timer: nothing built', () => {
	timers = [];
	const { c, log } = makeController(2e6);
	c.onShowMainSettingsPrint();
	c.printSettings.visible = false;
	c.onHidePrintMenu();
	runTimers();
	assert.ok(!log.includes('init'), 'preview built after the panel closed: ' + JSON.stringify(log));
	assert.strictEqual(log[log.length - 1], 'mask:hide');
});

check('en.json has the wait string', () => {
	assert.ok(/"SSE\.Controllers\.Print\.txtPreparingPreview":/.test(en), 'missing key');
	JSON.parse(en);
});

if (failed) { console.log(failed + ' check(s) failed'); process.exit(1); }
console.log('PASS #1864 large print previews show a wait message first');
