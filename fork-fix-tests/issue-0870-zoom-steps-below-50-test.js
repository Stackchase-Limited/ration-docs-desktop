/*
 * #870 - "Allow zoom level below 50%". The editors accept 10% (typed into the
 * View tab's zoom box: applyZoom clamps to Math.max(10, ...) in every editor) and
 * Fit to page goes down to 5%, but in the document, presentation and PDF editors
 * the zoom-out steps (Ctrl+-, Ctrl+wheel, the status bar's minus button) stopped at
 * 50%, and zooming IN from 20% jumped straight to 50% - the report's "as soon as I
 * zoom in, the next level is already 50%". The spreadsheet editor (10% steps down
 * to 10%) and the diagram editor already stepped below 50%.
 *
 * Cause: zoom_In/zoom_Out walk this.zoom_values, which in word/Drawing/HtmlPage.js
 * (document and PDF editors) and slide/Drawing/HtmlPage.js began at 50. The fix
 * starts both lists at 10, 20, 30, 40 - the list visio/Drawing/HtmlPage.js has.
 *
 * This extracts the real zoom_values arrays and the real zoom_In/zoom_Out of word
 * and slide by brace/bracket matching, and drives them on a stub control (zoom_Fire
 * records the value). It also reads the clamp in each editor's ViewTab applyZoom
 * from web-apps, so the lowest step and the lowest typed zoom must agree.
 *
 * Claimed: Ctrl+- from 100% reaches 10% in both editors; Ctrl++ from a typed 20%
 * goes to 30%, not 50%; steps above 50% are unchanged. NOT claimed: how a 10% page
 * looks (Fit to page already drew down to 5%); the status bar's preset menu still
 * lists 50%..500% only (presets, not a limit).
 *
 *   RD_REPO      sdkjs checkout (default ../sdkjs from this file's dir's parent)
 *   RD_WEBAPPS   web-apps checkout (default ../web-apps)
 *   BASELINE=1   sdkjs sources from BASE_REF via git show -> must FAIL
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '34252d945d^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function matched(text, from, open) {
	const close = open === '{' ? '}' : ']';
	const start = text.indexOf(open, from);
	let depth = 0;
	for (let i = start; i < text.length; i++) {
		if (text[i] === open) depth++;
		else if (text[i] === close && --depth === 0) return text.slice(start, i + 1);
	}
	throw new Error('unbalanced ' + open);
}

function extract(text, marker, open) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return matched(text, at + marker.length, open);
}

function control(file, values, outMarker, inMarker) {
	const text = src(file);
	const ctl = {
		zoom_values: new Function('return ' + extract(text, values, '['))(),
		m_nZoomValue: 100, m_nZoomType: 0, m_nZoomValueMin: -1, m_nZoomValueMax: -1,
		m_oApi: { bInit_word_control: true },
		zoom_Fire() { this.fired = this.m_nZoomValue; },
	};
	const fn = (marker) => new Function('oThis', 'return function()' + extract(text, marker, '{') + ';')(ctl);
	ctl.zoom_Out = fn(outMarker);
	ctl.zoom_In = fn(inMarker);
	return ctl;
}

const editors = [
	['document/PDF (word/Drawing/HtmlPage.js)',
		control('word/Drawing/HtmlPage.js', 'this.zoom_values =', 'this.zoom_Out = function()', 'this.zoom_In = function()')],
	['presentation (slide/Drawing/HtmlPage.js)',
		control('slide/Drawing/HtmlPage.js', 'this.zoom_values =', 'CEditorPage.prototype.zoom_Out = function ()', 'CEditorPage.prototype.zoom_In = function ()')],
];

/* the lowest zoom the View tab's box accepts, per editor */
const typedMin = {};
for (const ed of ['documenteditor', 'presentationeditor', 'pdfeditor']) {
	const m = fs.readFileSync(path.join(WEBAPPS, 'apps', ed, 'main/app/controller/ViewTab.js'), 'utf8')
		.match(/applyZoom: function \(value\) \{[^}]*?var val = Math\.max\((\d+), Math\.min\((\d+), value\)\)/);
	assert.ok(m, 'applyZoom clamp not found in ' + ed);
	typedMin[ed] = +m[1];
}
const minTyped = Math.min(...Object.values(typedMin));

let failures = 0;
function check(what, got, want) {
	const ok = got === want;
	failures += !ok;
	console.log(`  ${what.padEnd(66)} ${String(got).padStart(4)}%  ${ok ? 'ok' : 'FAILED (want ' + want + '%)'}`);
}

for (const [name, ctl] of editors) {
	console.log(name + ':');
	ctl.m_nZoomValue = 100;
	const path = [];
	for (let i = 0; i < 20; i++) {
		const before = ctl.m_nZoomValue;
		ctl.zoom_Out();
		if (ctl.m_nZoomValue === before) break;
		path.push(ctl.m_nZoomValue);
	}
	console.log('    Ctrl+- from 100%: ' + path.join(', '));
	check('lowest zoom reached with Ctrl+- (View tab box accepts ' + minTyped + '%)', ctl.m_nZoomValue, minTyped);

	ctl.m_nZoomValue = 20; ctl.zoom_In();
	check('Ctrl++ from a typed 20%', ctl.m_nZoomValue, 30);
	ctl.m_nZoomValue = 50; ctl.zoom_Out();
	check('Ctrl+- from 50%', ctl.m_nZoomValue, 40);
	ctl.m_nZoomValue = 100; ctl.zoom_In();
	check('Ctrl++ from 100% (unchanged)', ctl.m_nZoomValue, 110);
	ctl.m_nZoomValue = 500; ctl.zoom_In();
	check('Ctrl++ at 500% (unchanged)', ctl.m_nZoomValue, 500);
}

console.log(failures ? '\nFAILED' : '\nok - zoom steps go down to the lowest zoom the editors accept');
process.exit(failures ? 1 : 0);
