/*
 * #2422 - a guided "manual duplex" print.
 *
 * What there was: "Print sides" offered one-sided and the two automatic duplex modes
 * (the latter only when the printer reports duplex). Without a duplex printer the
 * user had to print odd and even pages by hand.
 * What now (an option; "Print one sided" stays the default): on the Windows/Linux app
 * the document and PDF print panels offer "Print on both sides manually". Print then
 * sends the odd pages of the range as a one-sided job, shows "turn the printed stack
 * over ... click OK", and on OK sends the even pages (ascending) as a second one-sided
 * job; Cancel stops. Only odd or only even pages in the range -> one plain job. The PDF
 * button and the system dialog treat the choice as one-sided. Not offered on macOS
 * (its Print goes through the macOS panel, which ignores the in-app range) or in a
 * browser.
 *
 * This test runs the REAL code, extracted by brace matching: Common.Utils.
 * getPrintPagesByParity, both controllers' onBtnPrint and both views'
 * getManualDuplexItems, against stubs that record every asc_Print/asc_DownloadAs with
 * its native options and the warning dialog (whose callback the test presses). That
 * the "1,3,5" lists reach the Windows/Linux job, sdkjs and x2t intact is shown by
 * issue-2299-odd-even-print-test.js.
 * BASELINE=1 reads web-apps from BASE_REF (#2299 applied, #2422 not): no manual item,
 * and 'manual' would go out as a single job of every page -> FAILS.
 *
 * NOT claimed: a real printer run and how a given printer stacks its sheets (GUI
 * check on Windows/Linux); that the first job has left the app before the user
 * presses OK (there is no print-finished event to JS; the dialog asks the user to wait).
 *
 * Env: RD_REPO web-apps checkout (default ../web-apps), BASELINE=1 with BASE_REF.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const WEBAPPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '720bbc9976^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
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
function fn(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return null;
		throw new Error(marker + ' not found');
	}
	return block(text, at);
}

const _ = { each(list, cb) { list.forEach(cb); }, extend: Object.assign };
const Common = {
	Utils: { isMac: false },
	Controllers: { Desktop: { active: true, isActive() { return this.active; } } },
	UI: { dialogs: [], warning(o) { this.dialogs.push(o); } },
};
new Function('Common', '_', fn(src('apps/common/main/lib/util/utils.js'), 'Common.Utils.getPrintPagesByParity = function') + ';')(Common, _);
const Asc = {
	asc_CDownloadOptions: function (type) { this.type = type; this.asc_setAdvancedOptions = (a) => { this.native = a.native; }; },
	c_oAscFileType: { PDF: 513 },
};
const FILES = {
	DE: ['apps/documenteditor/main/app/controller/Print.js', 'apps/documenteditor/main/app/view/FileMenuPanels.js'],
	PDF: ['apps/pdfeditor/main/app/controller/Print.js', 'apps/pdfeditor/main/app/view/FileMenuPanels.js'],
};

function combo(value) { return { getValue: () => value, getSelectedRecord: () => ({ value }) }; }
function run(editor, o) {
	const onBtnPrint = new Function('Common', 'Asc', '_', 'return {' + fn(src(FILES[editor][0]), 'onBtnPrint: function(print, useSystemDialog)') + '}.onBtnPrint;')(Common, Asc, _);
	const jobs = [];
	const ctl = {
		_state: { firstPrintPage: 0 },
		_navigationPreview: { pageCount: o.count, currentPage: 0 },
		txtManualDuplexTurnOver: 'turn over', txtNoPagesOfParity: 'none',
		adjPrintParams: { asc_setNativeOptions(n) { this.native = n; } },
		findPagePreset: () => 'A4',
		getApplication: () => ({ getController: () => ({ onTryPrint: (cb) => cb() }) }),
		api: {
			asc_getPageSize: () => ({ W: 210, H: 297 }),
			asc_Print: (opts) => jobs.push(`print[${opts.native.pages}|${opts.native.sides}]`),
			asc_DownloadAs: (opts) => jobs.push(`pdf[${opts.native.pages}|${opts.native.sides}]`),
		},
		printSettings: {
			cmbRange: combo(o.custom ? -1 : 'all'),
			inputPages: { getValue: () => o.custom, checkValidate: () => true, focus() {} },
			cmbPagesParity: combo('all'),
			cmbPrinter: combo('Printer'), cmbColorPrinting: combo('color'), cmbPaperOrientation: combo(0),
			cmbSides: combo(o.sides),
			spnCopies: { getNumberValue: () => 1 },
			menu: { hide() {} },
		},
	};
	Common.UI.dialogs = [];
	onBtnPrint.call(ctl, o.print !== false, !!o.system);
	if (Common.UI.dialogs.length) {
		const d = Common.UI.dialogs[0];
		jobs.push(`ask[${d.buttons}]`);
		d.callback(o.answer);
	}
	return jobs.join(' ');
}
function offered(editor, mac, desktop) {
	const items = fn(src(FILES[editor][1]), 'getManualDuplexItems: function()', true);
	if (!items) return 'no';
	Common.Utils.isMac = mac;
	Common.Controllers.Desktop.active = desktop;
	const r = new Function('Common', 'return {' + items + '}.getManualDuplexItems;')(Common).call({ txtManualDuplex: 'm', txtManualDuplexDesc: 'd' });
	Common.Utils.isMac = false;
	Common.Controllers.Desktop.active = true;
	return r.length && r[0].value === 'manual' ? 'yes' : 'no';
}

const cases = [
	['DE  one-sided (default, unchanged)', () => run('DE', { count: 5, sides: 'one' }), 'print[all|one]'],
	['DE  manual, 5 pages, OK', () => run('DE', { count: 5, sides: 'manual', answer: 'ok' }), 'print[1,3,5|one] ask[ok,cancel] print[2,4|one]'],
	['DE  manual, 5 pages, Cancel', () => run('DE', { count: 5, sides: 'manual', answer: 'cancel' }), 'print[1,3,5|one] ask[ok,cancel]'],
	['DE  manual, range "4-9"', () => run('DE', { count: 12, custom: '4-9', sides: 'manual', answer: 'ok' }), 'print[5,7,9|one] ask[ok,cancel] print[4,6,8|one]'],
	['DE  manual, one page', () => run('DE', { count: 1, sides: 'manual' }), 'print[all|one]'],
	['DE  manual, Save as PDF', () => run('DE', { count: 5, sides: 'manual', print: false }), 'pdf[all|one]'],
	['DE  manual, system dialog', () => run('DE', { count: 5, sides: 'manual', system: true }), 'print[all|one]'],
	['PDF manual, 4 pages, OK', () => run('PDF', { count: 4, sides: 'manual', answer: 'ok' }), 'print[1,3|one] ask[ok,cancel] print[2,4|one]'],
	['DE  offered on Windows/Linux app', () => offered('DE', false, true), 'yes'],
	['DE  not offered on macOS app', () => offered('DE', true, true), 'no'],
	['DE  not offered in a browser', () => offered('DE', false, false), 'no'],
	['PDF offered on Windows/Linux app', () => offered('PDF', false, true), 'yes'],
];
let failures = 0;
console.log('#2422 manual duplex:');
for (const [what, f, want] of cases) {
	let got;
	try { got = f(); } catch (e) { got = 'threw ' + e.message; }
	const ok = got === want;
	failures += !ok;
	console.log(`  ${what.padEnd(36)} -> ${got.padEnd(50)} ${ok ? 'ok' : 'FAILED, want ' + want}`);
}
for (const [what, rel, key] of [['DE', 'apps/documenteditor/main/locale/en.json', 'DE.Views.PrintWithPreview.txtManualDuplex'],
	['PDF', 'apps/pdfeditor/main/locale/en.json', 'PDFE.Controllers.Print.txtManualDuplexTurnOver']]) {
	const ok = !!JSON.parse(src(rel))[key];
	failures += !ok;
	console.log(`  web-apps: ${what} English strings ${ok ? 'ok' : 'FAILED'}`);
}
if (failures) {
	console.log('FAIL');
	process.exit(1);
}
console.log('PASS #2422: manual duplex prints the odd pages, asks, then the even pages; one-sided stays the default');
