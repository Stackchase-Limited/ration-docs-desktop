/*
 * #1664 (security round) - document macros: the warning ran them on Enter, and
 * the JS "sandbox" let them out.
 *
 * 1. web-apps: opening a file with autostart macros showed "Do you want to run
 *    macros?" with buttons ['yes', 'no'], primary 'yes'. The alert focuses the
 *    primary button and its Enter handler (Window.js Common.UI.alert onKeyDown)
 *    clicks the FIRST footer button, so a reflexive Enter ran the document's
 *    code. Now the document, spreadsheet and presentation editors show
 *    ['no', 'yes'] with primary 'no' (the house pattern of the "open this
 *    link?" warning), the message says macros can read and change files on
 *    this computer (textMacrosTrust), and "Enable all" no longer auto-runs a
 *    local file opened from a downloads / mail-attachment / temp folder
 *    (Common.Controllers.Desktop.isLocalFileFromUntrustedPlace): that file
 *    gets the warning. "Remember my choice" still stores 1 (yes) / 2 (no).
 *
 * 2. sdkjs common/macros.js _safePluginEval stubbed only
 *    Function.prototype.constructor, so (async function(){}).constructor
 *    (and the AsyncGeneratorFunction one) compiled code in the global scope
 *    - window, AscDesktopEditor. import/**\/("...") slipped past the import()
 *    check. And a rejected macro (import, failing Api.GetDocument) left the
 *    stubs installed for the rest of the session. All four constructors are
 *    now stubbed with defineProperty right before the try that restores them.
 *
 * This extracts by brace matching the REAL onRunAutostartMacroses of the
 * three editors, the REAL alert onBtnClick/onKeyDown of Window.js, the REAL
 * isLocalFileFromUntrustedPlace of Desktop.js and the REAL _safePluginEval,
 * and runs them against stubs.
 *
 * Claimed: Enter on the macros warning does not run macros (each editor);
 * Yes still runs them; modes 1 (enable all) / 2 (disable) / remember still
 * work; a Downloads file with "enable all" asks first; the listed escape
 * routes are contained; legitimate Api-calling macro code (incl. arrow/class/
 * async syntax) still runs; intrinsics are intact after a rejected macro.
 * NOT claimed: that _safePluginEval is a security boundary - it is not. Code
 * a macro defers (promise continuation, timer) runs after the restore, and
 * Api's own objects lead back to window (word: Api.GetDocument().Document
 * .DrawingDocument.m_oWordControl.m_oApi.HtmlElement.ownerDocument
 * .defaultView); this test asserts the deferred routes stay OPEN so nobody
 * mistakes it for a sandbox test. Rendering/focus in a real browser and the
 * real editors running legitimate macros (insert/iterate paragraphs, search
 * and replace, cell values, formula, chart) were checked headless in
 * Chromium during the fix (.rd-work/wt/by-tmp/dlg/dialog.js,
 * .rd-work/wt/by-tmp/macros_real.js), not here. The GUI desktop is not.
 *
 * RD_REPO=<sdkjs> (default ../sdkjs next to fork-fix-tests),
 * RD_WEBAPPS=<web-apps> (default ../web-apps). BASELINE=1 reads the sources
 * with git show at BASE_REF (sdkjs) / WEBAPPS_BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
// Pinned to the parents of the commits that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'c1d45eb060^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '573d311c86^';

function read(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}

/* Brace-match forward from the first '{' at or after `from`; returns text from `from`. */
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function fnAfter(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return matched(text, text.indexOf('function', at));
}

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}

/* ------------------------------ web-apps ------------------------------ */
const windowSrc = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/common/main/lib/component/Window.js');
const alertSrc = fnAfter(windowSrc, 'Common.UI.alert = function');
const onBtnClick = fnAfter(alertSrc, 'function onBtnClick(');
const onKeyDown = fnAfter(alertSrc, 'function onKeyDown(');
const desktopSrc = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/common/main/lib/controller/Desktop.js');
const untrustedSrc = desktopSrc.includes('isLocalFileFromUntrustedPlace:')
	? fnAfter(desktopSrc, 'isLocalFileFromUntrustedPlace:') : null;

/* The real alert keyboard/click handlers over a footer built from options.buttons
 * in order (Window.js initialize keeps the order; primary only adds a class). */
function fakeWarning(log) {
	return function (options) {
		const footer = options.buttons.map(b => ({ attributes: { result: { value: b } } }));
		const win = { getChild: () => footer, close() {} };
		let checked = false;
		const chDontShow = { getValue: () => (checked ? 'checked' : 'unchecked') };
		const h = new Function('options', 'win', 'chDontShow',
			'"use strict";' + onBtnClick + '\n' + onKeyDown + '\nreturn {onBtnClick: onBtnClick, onKeyDown: onKeyDown};')(options, win, chDontShow);
		log.dialog = { buttons: options.buttons.slice(), primary: options.primary, msg: options.msg,
			enter() { h.onKeyDown({}); },
			click(v) { h.onBtnClick({ currentTarget: footer.find(b => b.attributes.result.value === v) }); },
			remember() { checked = true; } };
	};
}

function runEditor(ed, pfx, mode, srcPath) {
	const src = read(WEBAPPS, WEBAPPS_BASE_REF, `apps/${ed}/main/app/controller/Main.js`);
	const fn = fnAfter(src, 'onRunAutostartMacroses: function');
	const settings = { [pfx + '-macros-mode']: mode }, stored = {};
	const log = { runs: 0 };
	const native = { LocalFileGetSourcePath: () => srcPath };
	const Desktop = {};
	if (untrustedSrc)
		Desktop.isLocalFileFromUntrustedPlace = new Function('native', '"use strict"; return ' + untrustedSrc)(native);
	const Common = {
		Utils: { InternalSettings: { get: k => settings[k], set: (k, v) => { settings[k] = v; } } },
		localStorage: { setItem: (k, v) => { stored[k] = v; } },
		UI: { warning: fakeWarning(log) },
		Controllers: { Desktop },
	};
	const ctx = { editorConfig: {}, api: { asc_runAutostartMacroses: () => log.runs++ },
		textHasMacros: 'The file contains automatic macros.', textMacrosTrust: 'TRUST', textRemember: 'Remember' };
	new Function('Common', 'setTimeout', '"use strict"; return ' + fn)(Common, cb => cb()).call(ctx);
	return { log, settings, stored };
}

for (const [ed, pfx] of [['documenteditor', 'de'], ['spreadsheeteditor', 'sse'], ['presentationeditor', 'pe']]) {
	check(`${pfx}: Enter on the macros warning does not run macros`, () => {
		const r = runEditor(ed, pfx, 0, '/Users/u/Documents/a.docx');
		assert.ok(r.log.dialog, 'no warning shown');
		assert.strictEqual(r.log.dialog.primary, 'no', 'primary (focused) button');
		r.log.dialog.enter();
		assert.strictEqual(r.log.runs, 0, 'Enter ran the macros');
	});
	check(`${pfx}: Yes still runs, remember stores 1/2, modes 1/2 unchanged`, () => {
		let r = runEditor(ed, pfx, 0, '/Users/u/Documents/a.docx');
		r.log.dialog.click('yes');
		assert.strictEqual(r.log.runs, 1);
		r = runEditor(ed, pfx, 0, '/Users/u/Documents/a.docx');
		r.log.dialog.remember(); r.log.dialog.click('yes');
		assert.strictEqual(r.stored[pfx + '-macros-mode'], 1);
		r = runEditor(ed, pfx, 0, '/Users/u/Documents/a.docx');
		r.log.dialog.remember(); r.log.dialog.enter();
		assert.strictEqual(r.stored[pfx + '-macros-mode'], 2);
		assert.strictEqual(r.log.runs, 0);
		r = runEditor(ed, pfx, 1, '/Users/u/Documents/a.docx');
		assert.ok(!r.log.dialog && r.log.runs === 1, 'enable all, trusted place: runs without asking');
		r = runEditor(ed, pfx, 2, '/Users/u/Downloads/a.docx');
		assert.ok(!r.log.dialog && r.log.runs === 0, 'disable all');
	});
	check(`${pfx}: the warning says macros can reach this computer`, () => {
		const r = runEditor(ed, pfx, 0, '');
		assert.ok(r.log.dialog.msg.includes('TRUST'), 'textMacrosTrust not in the message');
		const en = JSON.parse(read(WEBAPPS, WEBAPPS_BASE_REF, `apps/${ed}/main/locale/en.json`));
		const key = { de: 'DE', sse: 'SSE', pe: 'PE' }[pfx] + '.Controllers.Main.textMacrosTrust';
		assert.ok(/files on this computer/.test(en[key] || ''), key + ' missing in en.json');
	});
	check(`${pfx}: "enable all" still asks for a file from Downloads / mail / temp`, () => {
		for (const p of ['/Users/u/Downloads/a.docx', 'C:\\Users\\u\\Downloads\\a.xlsx',
			'/Users/u/Library/Containers/com.apple.mail/Data/Library/Mail Downloads/X/a.docx',
			'/private/var/folders/xy/T/a.pptx', 'C:\\Users\\u\\AppData\\Local\\Microsoft\\Windows\\INetCache\\Content.Outlook\\Q\\a.docx']) {
			const r = runEditor(ed, pfx, 1, p);
			assert.ok(r.log.dialog, 'no warning for ' + p);
			r.log.dialog.enter();
			assert.strictEqual(r.log.runs, 0, 'ran for ' + p);
		}
	});
}

/* ------------------------------ sdkjs ------------------------------ */
const macrosSrc = read(SDKJS, BASE_REF, 'common/macros.js');
const evalSrc = fnAfter(macrosSrc, 'function _safePluginEval(');
globalThis.window = globalThis;
globalThis.AscCommon = { c_oEditorId: { Word: 0, Spreadsheet: 1, Presentation: 2 }, parseJSDoc: () => [] };
globalThis.customXMLHttpRequest = function () {};
const doc = { paras: ['first', 'second'] };
const jsApi = {
	GetDocument() { return { GetElementsCount: () => doc.paras.length, GetElement: i => ({ GetText: () => doc.paras[i] }), Push: p => doc.paras.push(p.text) }; },
	CreateParagraph() { return { text: '', AddText(t) { this.text += t; } }; },
};
globalThis.g_asc_plugins = { api: { editorId: 0, getJsApi: () => jsApi } };
const safeEval = (0, eval)('"use strict";(' + evalSrc + ')');

const P = [function () {}, function* () {}, async function () {}, async function* () {}].map(Object.getPrototypeOf);
const saved = P.map(p => Object.getOwnPropertyDescriptor(p, 'constructor')), savedNext = P[1].prototype.next;
const reset = () => { P.forEach((p, i) => Object.defineProperty(p, 'constructor', saved[i])); P[1].prototype.next = savedNext; };
const intact = () => (function () {}).constructor === Function && (async function () {}).constructor.name === 'AsyncFunction' && [...(function* () { yield 1; })()].length === 1;
process.on('unhandledRejection', () => {});

const ESCAPES = {
	'Function ctor via a function': '(function(){}).constructor("globalThis.__esc = 1")()',
	'AsyncFunction ctor': '(async function(){}).constructor("globalThis.__esc = 1")()',
	'AsyncFunction via descriptor': 'Object.getOwnPropertyDescriptor(Object.getPrototypeOf(async()=>{}), "constructor").value("globalThis.__esc = 1")()',
	'AsyncFunction via Reflect.construct': 'Reflect.construct(Reflect.getPrototypeOf(async()=>{}).constructor, ["globalThis.__esc = 1"])()',
	'GeneratorFunction ctor': '[...(function*(){}).constructor("globalThis.__esc = 1; yield 1")()]',
	'AsyncGeneratorFunction ctor': '(async function*(){}).constructor("globalThis.__esc = 1")().next()',
	'indirect eval': '(0,eval)("globalThis.__esc = 1")',
	'dynamic import with a comment': 'import/**/("data:text/javascript,globalThis.__esc=1;//b")',
	'dynamic import with a line comment': 'import//x\n("data:text/javascript,globalThis.__esc=1;//c")',
};
const OPEN = {   // same-realm limits: documented, asserted to stay open
	'deferred promise continuation': 'Promise.resolve().then(function(){ (function(){}).constructor("globalThis.__esc = 1")(); })',
};
const settle = () => new Promise(r => setTimeout(r, 100));

(async () => {
	for (const [k, code] of Object.entries(ESCAPES)) {
		reset(); delete globalThis.__esc;
		try { safeEval(code); } catch (e) { /* contained by a throw is fine */ }
		await settle();
		check('sandbox contains: ' + k, () => assert.notStrictEqual(globalThis.__esc, 1, 'reached the global scope'));
	}
	for (const [k, code] of Object.entries(OPEN)) {
		reset(); delete globalThis.__esc;
		try { safeEval(code); } catch (e) {}
		await settle();
		console.log('info ' + k + ': ' + (globalThis.__esc === 1 ? 'still escapes (expected: not a boundary)' : 'contained'));
	}
	reset();
	check('legitimate macro code still runs (Api calls, iteration, arrow/class/async syntax)', () => {
		safeEval('var d = Api.GetDocument(), n = d.GetElementsCount(), t = [];' +
			'for (var i = 0; i < n; i++) t.push(d.GetElement(i).GetText());' +
			'const up = (s) => s.toUpperCase(); class K { m() { return t.map(up).join("+"); } }' +
			'const af = async () => 1; af();' +
			'var p = Api.CreateParagraph(); p.AddText(new K().m()); d.Push(p);');
		assert.deepStrictEqual(doc.paras, ['first', 'second', 'FIRST+SECOND']);
		assert.strictEqual(safeEval('[1, 2, 3].map(x => x * 2).reduce((a, b) => a + b)'), 12, 'return value');
	});
	check('intrinsics are restored after a run and after a rejected macro', () => {
		reset();
		safeEval('1 + 1');
		assert.ok(intact(), 'after a normal run');
		try { safeEval('import("x")'); } catch (e) {}
		assert.ok(intact(), 'Function/generator intrinsics left stubbed after a rejected macro');
	});
	reset();
	console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed');
	process.exit(failures ? 1 : 0);
})();
