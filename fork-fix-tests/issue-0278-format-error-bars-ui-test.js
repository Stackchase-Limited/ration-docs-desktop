/*
 * DesktopEditors #278 - custom error bars from sheet ranges: the web-apps UI.
 * (sdkjs API and x2t round trip: issue-0278-custom-error-bars/.)
 *
 * Before: the spreadsheet editor's Error Bars submenu offered None / Standard
 * Error / Percentage / Standard Deviation only; there was no way to point the
 * bars at cells holding the error values.
 * Now: "More options..." at the end of that submenu (Chart tab menu and the
 * chart's "+" menu) opens SSE.Views.FormatErrorBarsDialog - direction, end
 * style, and range pickers for the positive and negative values - which
 * validates with asc_ChartSettings.isValidCustomErrorBars and applies with
 * setCustomErrorBars.
 *
 * What runs: the REAL FormatErrorBarsDialog.js (define() factory run with stub
 * Common.UI classes): render, setSettings prefill from getCustomErrorBars,
 * direction switching, getSettings, OK validation; the REAL
 * DocumentHolderExt controller's onFormatErrorBars and its onChartElement
 * case; plus the menu items in both views, the build lists and en.json.
 * NOT claimed: the dialog's look and the range picking in the sheet (GUI
 * check needed).
 *
 *   RD_WEBAPPS=<web-apps> (default ../web-apps)
 *   BASELINE=1 reads web-apps at WEBAPPS_BASE_REF; it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '5fdc08a71f^';

function wsrc(rel) {
	try {
		return process.env.BASELINE
			? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'] })
			: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
	} catch (e) { return ''; }
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

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

const SSE = 'apps/spreadsheeteditor/main/';
const AscFormat = { st_errbartypeBOTH: 0, st_errbartypeMINUS: 1, st_errbartypePLUS: 2, st_errvaltypeCUST: 0 };
const Asc = { c_oAscError: { ID: { No: 0, NoValues: 1, ErrorInFormula: 2, NoSingleRowCol: 3 } }, c_oAscSelectionDialogType: { Chart: 5 } };

function loadDialog() {
	const text = wsrc(SSE + 'app/view/FormatErrorBarsDialog.js');
	assert(text, 'no app/view/FormatErrorBarsDialog.js');
	let proto = null;
	const warnings = [];
	const Common = { UI: { warning: (o) => warnings.push(o.msg) }, Utils: {} };
	Common.UI.Window = { extend: (p) => { proto = Object.setPrototypeOf(p, Common.UI.Window.prototype); return p; }, prototype: { initialize() {}, render() {}, close() { this.closed = true; } } };
	const radios = {};
	Common.UI.RadioBox = function (o) {
		this.name = o.name; this.value = !!o.checked; this.handlers = [];
		radios[o.name] = radios[o.name] || []; radios[o.name].push(this);
		this.on = (ev, f) => { this.handlers.push(f); return this; };
		this.getValue = () => this.value;
		this.setValue = (v, suspend) => {
			if (v) radios[this.name].forEach(r => { r.value = false; });
			this.value = !!v;
			if (!suspend) this.handlers.forEach(f => f(this, v));
		};
	};
	Common.UI.InputFieldBtn = function () {
		this.v = ''; this.disabled = false;
		this.on = () => this; this.getValue = () => this.v; this.setValue = (v) => { this.v = v; };
		this.setDisabled = (d) => { this.disabled = d; }; this.focus = () => {};
	};
	const _ = { extend: Object.assign, bind: (f, t) => f.bind(t), template: () => () => '', isEmpty: (s) => !s, delay: (f) => f() };
	const SSEns = { Views: {} };
	new Function('define', 'Common', '_', 'SSE', 'AscFormat', 'Asc', '$', text)((deps, f) => f(), Common, _, SSEns, AscFormat, Asc, () => ({ find: () => ({ on() {} }) }));
	assert(proto && SSEns.Views.FormatErrorBarsDialog, 'dialog not defined');
	return { proto, warnings };
}

check('FormatErrorBarsDialog: prefills from the chart, follows the direction, returns the ranges', () => {
	const { proto } = loadDialog();
	const dlg = Object.assign(Object.create(proto), { getChild: () => ({ find: () => ({ on() {} }) }), getFooterButtons: () => [] });
	proto.render.call(dlg);
	const chartSettings = {
		getCustomErrorBars: () => ({ plus: '=Sheet1!$C$2:$C$5', minus: '=Sheet1!$D$2:$D$5', barType: 2, endCap: false, errValType: 0 }),
	};
	dlg.setSettings({ api: {}, chartSettings });
	assert.strictEqual(dlg.inputPlus.getValue(), '=Sheet1!$C$2:$C$5');
	assert.strictEqual(dlg.radioPlus.getValue(), true, 'direction not prefilled');
	assert.strictEqual(dlg.radioNoCap.getValue(), true, 'end style not prefilled');
	assert.strictEqual(dlg.inputMinus.disabled, true, 'minus range enabled for Plus bars');
	assert.deepStrictEqual(dlg.getSettings(), { plus: '=Sheet1!$C$2:$C$5', minus: '', barType: 2, endCap: false });
	dlg.radioBoth.setValue(true);
	assert.strictEqual(dlg.inputMinus.disabled, false, 'minus range still disabled for Both');
	dlg.radioCap.setValue(true);
	assert.deepStrictEqual(dlg.getSettings(), { plus: '=Sheet1!$C$2:$C$5', minus: '=Sheet1!$D$2:$D$5', barType: 0, endCap: true });
});

check('FormatErrorBarsDialog: OK validates through the api and keeps the dialog open on bad input', () => {
	const { proto, warnings } = loadDialog();
	const dlg = Object.assign(Object.create(proto), { getChild: () => ({ find: () => ({ on() {} }) }), getFooterButtons: () => [] });
	proto.render.call(dlg);
	let valid = Asc.c_oAscError.ID.ErrorInFormula;
	const results = [];
	dlg.options = { handler: (d, r) => { results.push(r); } };
	dlg.setSettings({ api: {}, chartSettings: { getCustomErrorBars: () => null, isValidCustomErrorBars: () => valid } });
	dlg.inputPlus.setValue('nonsense');
	dlg._handleInput('ok');
	assert.deepStrictEqual(results, [], 'handler called with an invalid range');
	assert.strictEqual(warnings.length, 1, 'no warning shown');
	valid = Asc.c_oAscError.ID.No;
	dlg._handleInput('ok');
	assert.deepStrictEqual(results, ['ok']);
	assert.strictEqual(dlg.closed, true);
});

check('DocumentHolder controller: "errorBarsMore" opens the dialog and applies setCustomErrorBars', () => {
	const ctl = wsrc(SSE + 'app/controller/DocumentHolderExt.js');
	assert(/case 'errorBarsMore':\s*this\.onFormatErrorBars\(chartProps\);/.test(ctl), 'onChartElement has no errorBarsMore case');
	const at = ctl.indexOf('dh.onFormatErrorBars = function');
	assert.notStrictEqual(at, -1, 'no onFormatErrorBars');
	let made = null;
	const SSEns = { Views: { FormatErrorBarsDialog: function (o) { made = this; this.o = o; this.show = () => { this.shown = true; }; this.setSettings = (s) => { this.settings = s; }; } } };
	const Common = { NotificationCenter: { trigger() {} } };
	const dh = {};
	new Function('dh', 'SSE', 'Common', block(ctl, at) + ';')(dh, SSEns, Common);
	const applied = [];
	const chartProps = { setCustomErrorBars: function () { applied.push(Array.from(arguments)); } };
	const me = { api: { id: 1 }, getCurrentChartProps: () => chartProps };
	dh.onFormatErrorBars.call(me, chartProps);
	assert(made && made.shown && made.settings.chartSettings === chartProps && made.settings.api === me.api, 'dialog not opened with the chart settings');
	made.o.handler({ getSettings: () => ({ plus: 'Sheet1!$C$1:$C$4', minus: '', barType: 2, endCap: true }) }, 'ok');
	assert.deepStrictEqual(applied, [['Sheet1!$C$1:$C$4', '', 2, true]]);
	made.o.handler({ getSettings: () => { throw new Error('read on cancel'); } }, 'cancel');
	assert.strictEqual(applied.length, 1);
});

check('both Error Bars submenus end with "More options..." (errorBarsMore); build lists and en.json', () => {
	for (const v of ['app/view/ChartTab.js', 'app/view/DocumentHolderExt.js']) {
		const t = wsrc(SSE + v);
		const sd = t.indexOf("value: 'standardDeviation'");
		assert.notStrictEqual(sd, -1, v + ': no standardDeviation item');
		assert(/^[\s\S]{0,600}\{caption: '--'\},\s*\{\s*caption: me\.textErrorBarsMore \|\| 'More options\.\.\.',\s*value: 'errorBarsMore'/.test(t.slice(sd)), v + ': no More options... after Standard Deviation');
	}
	for (const f of ['app_dev.js', 'app_pack.js'])
		assert(wsrc(SSE + f).includes("'spreadsheeteditor/main/app/view/FormatErrorBarsDialog'"), f + ' lacks the dialog');
	const en = wsrc(SSE + 'locale/en.json');
	for (const k of ['SSE.Views.ChartTab.textErrorBarsMore', 'SSE.Views.DocumentHolder.textErrorBarsMore', 'SSE.Views.FormatErrorBarsDialog.txtTitle'])
		assert(en.includes(`"${k}"`), 'en.json lacks ' + k);
	JSON.parse(en);
});

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
