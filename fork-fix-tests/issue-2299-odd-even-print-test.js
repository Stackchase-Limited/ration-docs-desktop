/*
 * #2299 - print only the odd or only the even pages.
 *
 * What there was: the document and PDF print panels (web-apps PrintWithPreview) had
 * "Print range" (all / current / custom "1,3,5-9") and nothing else; for odd or even
 * pages the user typed every page number by hand.
 * What now (an option; the default "All pages in range" is today's behaviour): a combo
 * under "Print range" with "Only odd pages" / "Only even pages". The controllers'
 * onBtnPrint expand the range with Common.Utils.getPrintPagesByParity and send an
 * explicit list ("1,3,5") as nativeOptions.pages. A range with no page of that kind
 * warns and prints nothing. "Print using the system dialog" ignores the option.
 *
 * This test runs the REAL code, extracted by brace matching:
 *   - Common.Utils.getPrintPagesByParity (web-apps common utils.js);
 *   - DE and PDFE Print controllers' onBtnPrint, against stubs of the panel widgets
 *     and the api that record the native options handed to asc_Print/asc_DownloadAs;
 * and then feeds the produced pages string to the real consumers, unchanged by this fix:
 *   - sdkjs AscCommon.getNativePrintRanges (editorscommon.js) - "Save as PDF" / renderer;
 *   - desktop-apps cprintdata.cpp parsePageRanges - the Windows/Linux print job - compiled
 *     with clang++ against Homebrew Qt5 (QtCore);
 *   - core x2t getPrintPages (X2tConverter/src/lib/pdf_image.h) - compiled with clang++;
 * checking each one selects exactly the odd/even pages.
 * BASELINE=1 reads web-apps from BASE_REF: no helper and onBtnPrint sends the range
 * unchanged ('all' / '2-7') -> FAILS.
 *
 * NOT claimed: how the combo looks in the panel; a real printer run (Windows/Linux GUI
 * check); macOS - its Print button always goes through the macOS print panel, which
 * ignores the in-app range (it has its own Odd/Even under Paper Handling); the system
 * dialog path.
 *
 * Env: RD_REPO web-apps checkout (default ../web-apps), RD_SDKJS (../sdkjs),
 *      RD_DESKTOPAPPS (../desktop-apps), RD_CORE (../core), QT5 (/opt/homebrew/opt/qt@5),
 *      BASELINE=1 with BASE_REF.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const WEBAPPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const SDKJS = path.resolve(process.env.RD_SDKJS || path.join(__dirname, '..', 'sdkjs'));
const DAPPS = path.resolve(process.env.RD_DESKTOPAPPS || path.join(__dirname, '..', 'desktop-apps'));
const CORE = path.resolve(process.env.RD_CORE || path.join(__dirname, '..', 'core'));
const QT5 = process.env.QT5 || '/opt/homebrew/opt/qt@5';
const BASE_REF = process.env.BASE_REF || '55387961da^';

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

/* ---- web-apps: the helper and both controllers' onBtnPrint ---- */
const utils = src('apps/common/main/lib/util/utils.js');
const helperSrc = fn(utils, 'Common.Utils.getPrintPagesByParity = function', true);
const _ = {
	each(list, cb) { list.forEach(cb); },
};
const Common = { Utils: {}, UI: { warnings: [], warning(o) { this.warnings.push(o.msg); } } };
if (helperSrc) new Function('Common', '_', helperSrc + ';')(Common, _);

function controllerMethod(rel) {
	const text = src(rel);
	const body = fn(text, 'onBtnPrint: function(print, useSystemDialog)');
	return new Function('Common', 'Asc', '_', 'return {' + body + '}.onBtnPrint;');
}
const Asc = {
	asc_CDownloadOptions: function (type) { this.type = type; this.asc_setAdvancedOptions = (a) => { this.adv = a; }; },
	c_oAscFileType: { PDF: 513 },
};

function combo(value) { return { getValue: () => value, getSelectedRecord: () => (value == null ? null : { value }) }; }
function run(editor, o) {
	const method = controllerMethod(editor === 'DE'
		? 'apps/documenteditor/main/app/controller/Print.js'
		: 'apps/pdfeditor/main/app/controller/Print.js')(Common, Asc, _);
	const calls = [];
	const ctl = {
		_state: { firstPrintPage: 0 },
		_navigationPreview: { pageCount: o.count, currentPage: (o.current || 1) - 1 },
		mode: { isEdit: true },
		txtNoPagesOfParity: 'no pages of that kind',
		adjPrintParams: { asc_setNativeOptions(n) { this.native = n; } },
		findPagePreset: () => 'A4',
		getApplication: () => ({ getController: () => ({ onTryPrint: (cb) => cb() }) }),
		api: {
			asc_getPageSize: (i) => (i >= 0 && i < o.count ? { W: 210, H: 297 } : null),
			asc_Print: (opts) => calls.push(['print', opts.adv.native]),
			asc_DownloadAs: (opts) => calls.push(['pdf', opts.adv.native]),
		},
		printSettings: {
			cmbRange: combo(o.custom ? -1 : (o.range || 'all')),
			inputPages: { getValue: () => o.custom, checkValidate: () => true, focus() {} },
			cmbPagesParity: combo(o.parity || 'all'),
			cmbPrinter: combo('Printer'), cmbColorPrinting: combo('color'),
			cmbPaperOrientation: combo(0), cmbSides: combo('one'),
			spnCopies: { getNumberValue: () => 1 },
			menu: { hide() {} },
		},
	};
	Common.UI.warnings = [];
	method.call(ctl, o.print !== false, !!o.system);
	if (!calls.length) return { pages: null, warned: Common.UI.warnings.length > 0 };
	return { pages: calls[0][1].pages, kind: calls[0][0], warned: false };
}

/* ---- consumers ---- */
const ec = fs.readFileSync(path.join(SDKJS, 'common/editorscommon.js'), 'utf8');
const getNativePrintRanges = new Function(fn(ec, 'function getNativePrintRanges(sRanges, currentPageSrc, pagescount)') + '; return getNativePrintRanges;')();
function sdkjsPages(pages, count) {
	const arr = getNativePrintRanges(pages, undefined, count);
	if (arr === undefined) return Array.from({ length: count }, (v, i) => i + 1);
	const res = [];
	for (let i = 0; i < count; i++) if (arr[i]) res.push(i + 1);
	return res;
}

let nativeBin = null;
function buildNative() {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rd2299-'));
	const cp = fs.readFileSync(path.join(DAPPS, 'win-linux/src/cprintdata.cpp'), 'utf8');
	const parse = fn(cp, 'static QVector<PageRanges> parsePageRanges(const QString& input, int pages_count)');
	const pdf = fs.readFileSync(path.join(CORE, 'X2tConverter/src/lib/pdf_image.h'), 'utf8');
	const x2t = fn(pdf, 'std::vector<bool> getPrintPages(const std::string &sPages, int nPagesCount)');
	const cpp = `#include <QString>
#include <QStringList>
#include <QVector>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdio>
#if QT_VERSION >= QT_VERSION_CHECK(5, 14, 0)
# define SKIP_EMPTY Qt::SkipEmptyParts
#else
# define SKIP_EMPTY QString::SkipEmptyParts
#endif
struct PageRanges { PageRanges(int f = -1, int t = -1) : fromPage(f), toPage(t) {} int fromPage; int toPage; };
${parse}
${x2t}
int main(int argc, char **argv) {
	int count = atoi(argv[2]);
	// the Windows/Linux job prints fromPage..toPage of every range, in order (ceditortools.cpp print)
	for (const PageRanges &r : parsePageRanges(QString::fromUtf8(argv[1]), count))
		for (int p = r.fromPage; p <= r.toPage; ++p) printf("%d,", p);
	printf("|");
	std::vector<bool> x = getPrintPages(argv[1], count);
	for (int i = 0; i < (int)x.size(); ++i) if (x[i]) printf("%d,", i + 1);
	printf("\\n");
	return 0;
}
`;
	fs.writeFileSync(path.join(tmp, 'h.cpp'), cpp);
	const out = path.join(tmp, 'h');
	execFileSync('clang++', ['-std=c++17', '-fPIC', '-w', '-F' + QT5 + '/lib', '-I' + QT5 + '/lib/QtCore.framework/Headers',
		'-I' + QT5 + '/include', path.join(tmp, 'h.cpp'), '-o', out, '-F' + QT5 + '/lib', '-framework', 'QtCore',
		'-Wl,-rpath,' + QT5 + '/lib'], { stdio: 'inherit' });
	return out;
}
function nativePages(pages, count) {
	if (!nativeBin) nativeBin = buildNative();
	const [job, x2t] = execFileSync(nativeBin, [pages, String(count)], { encoding: 'utf8' }).trim().split('|');
	const list = (s) => s.split(',').filter(Boolean).map(Number);
	return { job: list(job), x2t: list(x2t) };
}

/* ---- scenarios ---- */
const odd = (a, b) => { const r = []; for (let i = a; i <= b; i++) if (i % 2) r.push(i); return r; };
const even = (a, b) => { const r = []; for (let i = a; i <= b; i++) if (!(i % 2)) r.push(i); return r; };
const cases = [
	['DE  all pages, default (unchanged)', 'DE', { count: 7 }, 'all', null],
	['DE  all pages, odd only', 'DE', { count: 7, parity: 'odd' }, '1,3,5,7', odd(1, 7)],
	['DE  all pages, even only', 'DE', { count: 7, parity: 'even' }, '2,4,6', even(1, 7)],
	['DE  custom "2-7", odd only', 'DE', { count: 9, custom: '2-7', parity: 'odd' }, '3,5,7', odd(2, 7)],
	['DE  custom "9-4,1,-2", even', 'DE', { count: 9, custom: '9-4,1,-2', parity: 'even' }, '4,6,8,2', [2, 4, 6, 8]],
	['DE  custom "5-", odd, Save as PDF', 'DE', { count: 8, custom: '5-', parity: 'odd', print: false }, '5,7', odd(5, 8)],
	['DE  current page 3, even -> warning', 'DE', { count: 7, range: 'current', current: 3, parity: 'even' }, 'warn', null],
	['DE  system dialog ignores the option', 'DE', { count: 7, parity: 'odd', system: true }, 'all', null],
	['PDF all pages, even only', 'PDF', { count: 5, parity: 'even' }, '2,4', even(1, 5)],
	['PDF custom "1-5", odd, Save as PDF', 'PDF', { count: 12, custom: '1-5', parity: 'odd', print: false }, '1,3,5', odd(1, 5)],
];
let failures = 0;
console.log('#2299 odd / even pages:');
for (const [what, ed, o, want, sel] of cases) {
	let got;
	try {
		const r = run(ed, o);
		got = r.warned ? 'warn' : String(r.pages);
	} catch (e) {
		got = 'threw ' + e.message;
	}
	let ok = got === want;
	let consumers = '';
	if (ok && sel) {
		const s = sdkjsPages(got, o.count);
		const n = nativePages(got, o.count);
		const sorted = sel.slice().sort((a, b) => a - b);
		const same = (a, b) => a.join() === b.join();
		const okS = same(s, sorted), okJ = same(n.job.slice().sort((a, b) => a - b), sorted), okX = same(n.x2t, sorted);
		consumers = ` sdkjs ${okS ? 'ok' : 'BAD ' + s} / win-linux job ${okJ ? 'ok' : 'BAD ' + n.job} / x2t ${okX ? 'ok' : 'BAD ' + n.x2t}`;
		ok = okS && okJ && okX;
	}
	failures += !ok;
	console.log(`  ${what.padEnd(40)} -> ${got.padEnd(10)} ${ok ? 'ok' : 'FAILED, want ' + want}${consumers}`);
}

const wiring = [
	['DE panel has the combo', /cmbPagesParity = new Common\.UI\.ComboBox/.test(src('apps/documenteditor/main/app/view/FileMenuPanels.js'))],
	['PDF panel has the combo', /cmbPagesParity = new Common\.UI\.ComboBox/.test(src('apps/pdfeditor/main/app/view/FileMenuPanels.js'))],
	['DE English strings', !!JSON.parse(src('apps/documenteditor/main/locale/en.json'))['DE.Views.PrintWithPreview.txtOddPages']],
	['PDF English strings', !!JSON.parse(src('apps/pdfeditor/main/locale/en.json'))['PDFE.Views.PrintWithPreview.txtEvenPages']],
];
for (const [what, ok] of wiring) {
	failures += !ok;
	console.log(`  web-apps: ${what.padEnd(36)} ${ok ? 'ok' : 'FAILED'}`);
}
if (failures) {
	console.log('FAIL');
	process.exit(1);
}
console.log('PASS #2299: odd/even pages are sent as an explicit list that sdkjs, the Windows/Linux print job and x2t all select exactly');
