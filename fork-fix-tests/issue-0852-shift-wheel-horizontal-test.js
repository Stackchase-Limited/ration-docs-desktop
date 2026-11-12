/*
 * #852 - "Horizontal scrolling with mouse and keyboard": Shift+wheel scrolls
 * sideways in the spreadsheet editor (cell/view/EventsController.js swaps the
 * delta on Windows/Linux) but scrolled up/down in documents, presentations and
 * PDFs, so a page wider than the window could only be moved sideways with the
 * scroll bar, a tilt wheel or a touchpad.
 *
 * Fix (opt-in; today's wheel unchanged by default):
 *  - sdkjs: AscCommon.checkMouseWhell option isShiftHorizontal - with the
 *    horizontal bar shown, shiftKey set, no horizontal delta of its own and not
 *    macOS (which already turns Shift+wheel into a horizontal delta), the
 *    vertical delta goes to the horizontal axis. word/slide HtmlPage and the PDF
 *    viewer pass api.isShiftWheelHorizontal, set by the new
 *    baseEditorsApi asc_setShiftWheelHorizontal(bool).
 *  - web-apps: DE/PE/PDF Advanced settings "Shift + mouse wheel scrolls
 *    horizontally" (app-settings-shift-wheel-hor, hidden on macOS), handed to the
 *    api on document ready and on Apply.
 *
 * This test
 *  1. brace-extracts the real checkMouseWhell and asc_setShiftWheelHorizontal
 *     and runs them: a Shift+wheel notch (wheelDelta -120, Windows/Linux) with
 *     the option on -> {x: 45, y: 0}; option off -> {x: 0, y: 45} (as today);
 *     no horizontal bar -> vertical; macOS -> vertical delta untouched (the OS
 *     sends deltaX itself, and a real horizontal delta is kept); no Shift ->
 *     vertical;
 *  2. checks the three editors' wheel handlers pass the api flag, and the web-apps
 *     wiring (checkbox, storage key, Main + LeftMenu hand-off) in DE/PE/PDF.
 *  Baseline: no option -> Shift+wheel stays vertical -> FAILS.
 *
 * NOT claimed: a real wheel in the running editors (GUI check on Windows/Linux:
 * zoom 300%, tick the setting, Shift+wheel); the closure-compiled build was not
 * made here.
 *
 * Env: RD_REPO       sdkjs checkout    (default ../sdkjs)
 *      RD_WEBAPPS    web-apps checkout (default ../web-apps)
 *      BASELINE=1 reads sources from BASE_REF (sdkjs) / WEBAPPS_BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '6eddf61a54^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '8604aeacb2^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
const sdk = (rel) => src(SDKJS, BASE_REF, rel);
const web = (rel) => src(WEBAPPS, WEBAPPS_BASE_REF, rel);
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* ---- 1. checkMouseWhell ---- */
const we = sdk('common/Drawings/WorkEvents.js');
const at = we.indexOf('function checkMouseWhell(e, options)');
assert.ok(at !== -1, 'checkMouseWhell not found');
const fn = block(we, at);
function run(isMacOs, e, opts) {
	const ctx = { AscBrowser: { isMacOs } };
	vm.createContext(ctx);
	vm.runInContext(fn + '; this.check = checkMouseWhell;', ctx);
	const r = ctx.check(e, Object.assign({ isSupportBidirectional: false, isUseMaximumDelta: true, remainder: { x: 0, y: 0 } }, opts));
	return { x: r.x, y: r.y };
}
// one notch down of a mouse wheel as Chromium on Windows/Linux reports it with Shift held
const notch = () => ({ wheelDelta: -120, wheelDeltaY: -120, wheelDeltaX: 0, shiftKey: true });
const cases = [
	['Win/Linux, Shift, option on', run(false, notch(), { isAllowHorizontal: true, isShiftHorizontal: true }), { x: 45, y: 0 }],
	['Win/Linux, Shift, option off', run(false, notch(), { isAllowHorizontal: true }), { x: 0, y: 45 }],
	['Win/Linux, Shift, option on, no horizontal bar', run(false, notch(), { isAllowHorizontal: false, isShiftHorizontal: true }), { x: 0, y: 45 }],
	['Win/Linux, no Shift, option on', run(false, Object.assign(notch(), { shiftKey: false }), { isAllowHorizontal: true, isShiftHorizontal: true }), { x: 0, y: 45 }],
	['macOS, Shift, option on (vertical delta)', run(true, notch(), { isAllowHorizontal: true, isShiftHorizontal: true }), { x: 0, y: 45 }],
	['macOS, Shift (OS sent a horizontal delta)', run(true, { wheelDelta: -120, wheelDeltaY: 0, wheelDeltaX: -120, shiftKey: true }, { isAllowHorizontal: true, isShiftHorizontal: true }), { x: 45, y: 0 }],
];
for (const [what, got, want] of cases) {
	console.log(`${what}: ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
	assert.deepStrictEqual(got, want, `${what}: wrong scroll`);
}

const apiBase = sdk('common/apiBase.js');
const setAt = apiBase.indexOf('baseEditorsApi.prototype["asc_setShiftWheelHorizontal"] = function');
assert.ok(setAt !== -1, 'asc_setShiftWheelHorizontal not found');
const ctx = { baseEditorsApi: function () {} };
vm.createContext(ctx);
vm.runInContext(block(apiBase, setAt) + '; this.api = new baseEditorsApi(); this.api["asc_setShiftWheelHorizontal"](1);', ctx);
assert.strictEqual(ctx.api.isShiftWheelHorizontal, true, 'asc_setShiftWheelHorizontal does not set the flag');

for (const [file, flag] of [['word/Drawing/HtmlPage.js', 'oThis.m_oApi.isShiftWheelHorizontal'],
	['slide/Drawing/HtmlPage.js', 'oThis.m_oApi.isShiftWheelHorizontal'], ['pdf/src/viewer.js', 'oThis.Api.isShiftWheelHorizontal']]) {
	const t = sdk(file);
	const c = t.indexOf('AscCommon.checkMouseWhell(');
	const call = t.slice(c, t.indexOf('});', c));
	assert.ok(call.includes(`isShiftHorizontal : true === ${flag}`), `${file}: the wheel handler does not pass the setting`);
	console.log(`${file}: passes isShiftHorizontal from ${flag}`);
}

/* ---- 2. web-apps ---- */
for (const ed of ['documenteditor', 'presentationeditor', 'pdfeditor']) {
	const panels = web(`apps/${ed}/main/app/view/FileMenuPanels.js`);
	const main = web(`apps/${ed}/main/app/controller/Main.js`);
	const left = web(`apps/${ed}/main/app/controller/LeftMenu.js`);
	const en = JSON.parse(web(`apps/${ed}/main/locale/en.json`));
	assert.ok(panels.includes("id=\"fms-chb-shift-wheel\"") && panels.includes('this.chShiftWheel = new Common.UI.CheckBox(')
		&& /setBool\("app-settings-shift-wheel-hor", this\.chShiftWheel\.isChecked\(\)\)/.test(panels), `${ed}: no Shift+wheel switch in Advanced settings`);
	assert.ok(/asc_setShiftWheelHorizontal\(Common\.Utils\.InternalSettings\.get\("app-settings-shift-wheel-hor"\)\)/.test(main), `${ed}: Main does not hand the setting to the api`);
	const apply = block(left, left.indexOf('applySettings: function(menu)'));
	assert.ok(apply.includes('asc_setShiftWheelHorizontal'), `${ed}: Apply does not hand the setting to the api`);
	assert.ok(Object.keys(en).some(k => k.endsWith('FileMenuPanels.Settings.txtShiftWheel')), `${ed}: string missing in en.json`);
	console.log(`${ed}: setting stored as app-settings-shift-wheel-hor, applied on load and on Apply`);
}
console.log('PASS #852: with the setting on, Shift+wheel scrolls documents, presentations and PDFs sideways (Windows/Linux)');
