/*
 * #1166 (second ask) - "change the default page margin": every new document starts
 * with the blank template's margins (converter/empty/<lang>/new.docx), so a user who
 * wants other margins has to set them on every new document, or edit the installed
 * template again after every update.
 *
 * Fix (web-apps, document editor, desktop offline only; option, default unchanged),
 * next to #143's "Default document language" and #746's "Default font":
 *  - Advanced settings > "Default page margins": "Same as the template" (unset -
 *    today's behaviour) or one of the toolbar's Margins presets (Normal, Narrow,
 *    Moderate, Wide, and Last custom when there is one), stored as
 *    de-settings-def-margins = "top,left,bottom,right" in mm;
 *  - Main.js, when the desktop opens a new blank document (editorConfig.newBlank),
 *    applies them with the existing api.asc_SetSectionProps (what the Margins menu
 *    calls), only if they leave the room for text the Margins menu requires.
 *    Opened documents and templates are never touched.
 *
 * This test brace-extracts and runs
 *  1. the real #1166 block of Main.js: new blank + setting -> asc_SetSectionProps
 *     with the stored margins; opened document, unset, malformed, or margins wider
 *     than the page -> not called;
 *  2. the real FileMenuPanels fillDefMargins against stub toolbar menu items: the
 *     presets are offered with their values, hidden items and the 'advanced' entry
 *     are not, and a stored value that is no preset is kept;
 *  3. the Advanced settings source: row, combo box, key stored on Apply, en.json.
 *  Baseline: none of it exists -> FAILS.
 *
 * NOT claimed: the settings panel in the running editor (GUI check: File > Advanced
 * settings shows "Default page margins"; pick Narrow, Apply, File > New document ->
 * Layout > Margins shows Narrow checked); the saved docx's w:pgMar (the api is the
 * one the Margins menu already uses). Spreadsheets and presentations not covered.
 *
 * Env: RD_REPO  web-apps checkout (default ../web-apps)
 *      BASELINE=1 reads sources at BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const WEBAPPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || 'b541e516bf^';
let _;
try { _ = require(path.join(WEBAPPS, 'vendor/underscore/underscore-min.js')); } catch (e) { _ = null; }
if (!_ || !_.map) {
	// underscore ships in web-apps' vendor dir; locate it if the path differs
	const cand = execFileSync('find', [path.join(WEBAPPS, 'vendor'), '-name', 'underscore*.js', '-not', '-path', '*/node_modules/*'], { encoding: 'utf8' }).trim().split('\n').filter(Boolean);
	_ = require(cand[0]);
}

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
}
function block(text, from, open = text.indexOf('{', from)) {
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* ---- 1. Main.js: new blank documents only ---- */
const main = src('apps/documenteditor/main/app/controller/Main.js');
const at = main.indexOf('// page margins of a new blank desktop document (#1166)');
assert.ok(at !== -1, 'Main.js: no default page margins for new documents');
const ifAt = main.indexOf('if (me.editorConfig.newBlank', at);
// the if's own brace is the one ending its line (the condition holds a function literal)
const snippet = main.slice(at, ifAt) + block(main, ifAt, main.indexOf('{\n', ifAt));

function runMain(newBlank, stored, page) {
	const c = { calls: [], _ };
	vm.createContext(c);
	vm.runInContext(`
		var value;
		var Common = { localStorage: { getItem: function (k) { return ${JSON.stringify(stored)}[k] || null; } },
			Utils: { InternalSettings: { set: function () {} } } };
		function CDocumentSectionProps() { this.m = {}; }
		['Top', 'Left', 'Bottom', 'Right'].forEach(function (n) {
			CDocumentSectionProps.prototype['put_' + n + 'Margin'] = function (v) { this.m[n] = v; };
		});
		var Asc = { CDocumentSectionProps: CDocumentSectionProps };
		var me = { editorConfig: { newBlank: ${newBlank} }, api: {
			asc_GetSectionProps: function () { return { get_W: function () { return ${page[0]}; }, get_H: function () { return ${page[1]}; } }; },
			asc_SetSectionProps: function (p) { calls.push([p.m.Top, p.m.Left, p.m.Bottom, p.m.Right].join(',')); } } };
		${snippet}
	`, c);
	return c.calls.join(';');
}
const A4 = [210, 297];
for (const [newBlank, stored, page, want] of [
	[true, { 'de-settings-def-margins': '12.7,12.7,12.7,12.7' }, A4, '12.7,12.7,12.7,12.7'],
	[true, { 'de-settings-def-margins': '25.4,50.8,25.4,50.8' }, [215.9, 279.4], '25.4,50.8,25.4,50.8'],
	[false, { 'de-settings-def-margins': '12.7,12.7,12.7,12.7' }, A4, ''],
	[true, {}, A4, ''],
	[true, { 'de-settings-def-margins': '12.7,abc,12.7' }, A4, ''],
	[true, { 'de-settings-def-margins': '20,100,20,100' }, A4, ''],
]) {
	const got = runMain(newBlank, stored, page);
	console.log(`newBlank=${newBlank} stored=${JSON.stringify(stored)} page=${page} -> ${got || '(not called)'}`);
	assert.strictEqual(got, want);
}

/* ---- 2. FileMenuPanels.fillDefMargins ---- */
const panels = src('apps/documenteditor/main/app/view/FileMenuPanels.js');
const fAt = panels.indexOf('fillDefMargins: function(stored)');
assert.ok(fAt !== -1, 'FileMenuPanels: no fillDefMargins');
const fill = 'var fillDefMargins = ' + block(panels, fAt).slice('fillDefMargins: '.length);
const item = (caption, value, visible = true) => ({ caption, value, isVisible: () => visible });
const ctx = {
	_,
	Common: { Utils: { Metric: { fnRecalcFromMM: (v) => v / 10, getCurrentMetricName: () => 'cm' } } },
	DE: { getController: () => ({ toolbar: { btnPageMargins: { menu: { items: [
		item('Last Custom', undefined, false), item('Normal', [20, 30, 20, 15]), item('Narrow', [12.7, 12.7, 12.7, 12.7]),
		item('--'), item('Custom margins', 'advanced')] } } } }) },
};
vm.createContext(ctx);
vm.runInContext(fill, ctx);
let data;
const self = { txtDefFontTemplate: 'Same as the template', cmbDefMargins: { setData: (d) => { data = d; } } };
ctx.fillDefMargins.call(self, '');
console.log('offered:', data.map((d) => `${d.value || "''"}=${d.displayValue}`).join(' | '));
assert.strictEqual(JSON.stringify(data.map((d) => d.value)), JSON.stringify(['', '20,30,20,15', '12.7,12.7,12.7,12.7']));
assert.strictEqual(data[2].displayValue, 'Narrow: 1.27 cm, 1.27 cm, 1.27 cm, 1.27 cm');
ctx.fillDefMargins.call(self, '30,30,30,30');
assert.strictEqual(data[data.length - 1].value, '30,30,30,30', 'a stored non-preset value is not offered');

/* ---- 3. Advanced settings ---- */
assert.ok(/'<td colspan="2"><span id="fms-cmb-def-margins"><\/span><\/td>'/.test(panels), 'no Default page margins row');
assert.ok(panels.includes('this.cmbDefMargins = new Common.UI.ComboBox('));
const apply = block(panels, panels.indexOf('applySettings: function()'));
assert.ok(apply.includes('setItem("de-settings-def-margins"'), 'Apply does not store the default margins');
const en = JSON.parse(src('apps/documenteditor/main/locale/en.json'));
assert.ok(en['DE.Views.FileMenuPanels.Settings.txtDefMargins']);
console.log('Advanced settings: Default page margins row, stored on Apply');

console.log('PASS #1166: chosen default page margins are applied to new blank documents only');
