/*
 * #1664 (security hardening) - JavaScript inside a PDF form could reach the
 * editor's own globals and the native AscDesktopEditor bridge.
 *
 * PDF form/annotation scripts (calculate, format, keystroke, validate, mouse-up)
 * ran through EvalScript (pdf/src/forms/formActions.js) as
 * `Function.apply(null, [...names, script])` in the editor realm. Shadowing
 * `window` with a parameter is no barrier: `this.constructor.constructor` is
 * the editor's Function, a sloppy-mode `(function(){return this})()` is the
 * global object, and bare names (AscDesktopEditor, AscPDF, editor) resolve to
 * globals. A PDF could therefore call the native bridge as soon as the user
 * typed into a field.
 *
 * Now the scripts run in QuickJS compiled to WebAssembly
 * (pdf/src/engine/pdfscripting.js, built from pdf/src/scripting/sandbox.js),
 * a separate realm that holds no editor object at all. Only JSON crosses into
 * it; editor objects appear as handles whose property reads, writes and calls
 * go through the allowlist in formActions.js (event properties, API accessors
 * and prototype methods, AF* functions, console).
 *
 * This loads the REAL apiFunctions.js, apiGlogalObjects.js, apiPDF.js and
 * formActions.js (and, after the fix, the real engine bundle) into a node vm
 * with stub internal fields, takes the real CPDFDoc.prototype.CreateEvent from
 * document.js by brace matching, and runs scripts through the real
 * CActionRunScript.RunScript -> EvalScript path:
 *   - escape attempts (the bs-tmp/pdfjs-escape-demo.js set and more) must not
 *     reach the stub AscDesktopEditor, the global object or internal objects;
 *   - legitimate scripts (custom calculate, AFSimple_Calculate, AFRange_Validate,
 *     keystroke filter, show/hide, color, state kept on `this`) must give the
 *     results they give on baseline (expected values are written out below
 *     and are the same on both);
 *   - after the fix, an endless loop is interrupted (skipped under BASELINE,
 *     where it would hang the test).
 * NOT claimed here: AFNumber/AFDate/AFPercent format/keystroke output (they need
 * the real text layout) - that was compared in the real PDF editor in headless
 * Chromium (bw-tmp/h), identical on baseline and fix.
 *
 *   RD_REPO=<sdkjs checkout>   (default ../sdkjs)
 *   BASELINE=1                 read sources at BASE_REF; must FAIL
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit (the integrator re-pins it after cherry-picking).
const BASE_REF = process.env.BASE_REF || '1e4933c865^';

function read(rel) {
	if (process.env.BASELINE) {
		try {
			return execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'] });
		} catch (e) {
			return null;
		}
	}
	const p = path.join(SDKJS, rel);
	return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
}

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* ---------------- a minimal world for the real sources ---------------- */
const bridge = { calls: [] };
const ctx = {
	console: { log: () => {}, error: () => {}, warn: () => {}, clear: () => {} },
	AscDesktopEditor: { RemoveFile: (p) => { bridge.calls.push(p); return 'native bridge reached'; } },
	Asc: { editor: { documentTitle: 'form.pdf' } },
	AscCommon: {},
	AscPDF: {},
	setTimeout, clearTimeout, WebAssembly, TextDecoder, TextEncoder, URL, atob, btoa,
};
ctx.window = ctx;
ctx.globalThis = ctx;
ctx.self = ctx;
vm.createContext(ctx);

const load = (rel) => {
	const src = read(rel);
	if (src === null) throw new Error(rel + ' not found');
	vm.runInContext(src, ctx, { filename: rel });
};
load('pdf/src/forms/apiFunctions.js');
load('pdf/src/forms/apiGlogalObjects.js');
load('pdf/src/apiPDF.js');
load('pdf/src/forms/formActions.js');
const engine = read('pdf/src/engine/pdfscripting.js');
if (engine !== null) vm.runInContext(engine, ctx, { filename: 'pdfscripting.js' });

const docSrc = read('pdf/src/document.js');
const ceAt = docSrc.indexOf('CPDFDoc.prototype.CreateEvent = function');
if (ceAt < 0) throw new Error('CreateEvent not found');
const createEvent = vm.runInContext('(' + matched(docSrc, docSrc.indexOf('function', ceAt)) + ')', ctx);

const AscPDF = ctx.AscPDF;
AscPDF.FIELD_TYPES = { text: 1, button: 2 };

/* stub internal text field (what the real API accessors call) */
function makeField(doc, name, value) {
	const f = {
		name, value, display: 0, warning: null,
		GetFullName: () => name, IsWidget: () => true, IsAllKidsWidgets: () => true, GetKid: () => f,
		GetDocument: () => doc, GetType: () => AscPDF.FIELD_TYPES.text,
		GetValue: () => f.value, GetParentValue: () => f.value, SetParentValue: (v) => { f.value = v; },
		IsCanCommit: () => true, SetValue: (v) => { f.value = v; }, Commit: () => {}, SetNeedCommit: () => {},
		GetDisplay: () => f.display, SetDisplay: (d) => { f.display = d; },
		GetTrigger: () => null,
	};
	f.api = new AscPDF.ApiTextField(f);
	f.GetFormApi = () => f.api;
	return f;
}
function makeDoc() {
	const doc = { eventsStack: [], fields: {}, isOnValidate: false };
	doc.CreateEvent = createEvent;
	doc.GetField = (n) => doc.fields[n] || null;
	doc.GetAllWidgets = (n) => doc.fields[n] ? [doc.fields[n]] : [];
	doc.GetCalculateInfo = () => ({ GetSourceField: () => null, IsInProgress: () => true, GetCurrentField: () => null });
	doc.IsNeedDoCalculate = () => false;
	doc.SetWarningInfo = (w) => { doc.warning = w; };
	doc.api = new AscPDF.ApiDocument(doc);
	doc.GetDocumentApi = () => doc.api;
	doc.GetActionsQueue = () => ({ SetCurAction() {}, Continue() {} });
	for (const [n, v] of [['A', '3.5'], ['B', '4'], ['Total', ''], ['Secret', ''], ['Small', '']]) doc.fields[n] = makeField(doc, n, v);
	return doc;
}
const doc = makeDoc();
ctx.editor = { getDocumentRenderer: () => ({ doc }) };

function run(script, fieldName, eventPr) {
	const field = doc.fields[fieldName];
	const action = new AscPDF.CActionRunScript(script);
	action.SetParent({ GetCallerFiled: () => field, GetType: () => 8 });
	const pr = Object.assign({ name: 'Calculate', target: field.GetFormApi(), rc: true }, eventPr || {});
	return action.RunScript(pr);
}

/* ---------------- checks ---------------- */
let failed = 0;
function check(label, ok, detail) {
	console.log((ok ? 'ok   ' : 'FAIL ') + label + (detail !== undefined ? '  -> ' + detail : ''));
	if (!ok) failed++;
}

(async () => {
	const sandbox = ctx.AscPDFScriptSandbox;
	if (sandbox) await sandbox.load();
	console.log(process.env.BASELINE ? `BASELINE (${BASE_REF})` : 'sources: ' + SDKJS, '| scripting engine:', sandbox ? 'QuickJS' : 'none');

	// 1. escape attempts: the value each one writes, and whether the bridge was called
	const escapes = {
		'globalThis': 'event.value = typeof globalThis.AscDesktopEditor',
		'bare AscDesktopEditor': 'event.value = AscDesktopEditor.RemoveFile("/x1")',
		'Function ctor via this': 'event.value = this.constructor.constructor("return AscDesktopEditor")().RemoveFile("/x2")',
		'sloppy this': 'event.value = (function(){ return this; })().AscDesktopEditor.RemoveFile("/x3")',
		'Function ctor via event': 'event.value = event.constructor.constructor("return AscDesktopEditor")().RemoveFile("/x4")',
		'Function ctor via AF*': 'event.value = AFSimple_Calculate.constructor("return AscDesktopEditor")().RemoveFile("/x5")',
		'Function ctor via field': 'event.value = this.getField("A").constructor.constructor("return AscDesktopEditor")().RemoveFile("/x6")',
		'Function ctor via method': 'event.value = this.getField.constructor("return AscDesktopEditor")().RemoveFile("/x7")',
		'internal field object': 'event.value = typeof event.target.field.GetDocument',
		'internal doc object': 'event.value = typeof this.doc.GetField',
		'__proto__ walk': 'event.value = typeof this.__proto__.constructor',
		'editor global': 'event.value = typeof editor + "/" + typeof AscPDF',
	};
	for (const [label, code] of Object.entries(escapes)) {
		doc.fields.Total.value = 'unset';
		const before = bridge.calls.length;
		try { run(code, 'Total'); } catch (e) { /* RunScript logs and swallows */ }
		const v = doc.fields.Total.value;
		const reached = bridge.calls.length > before || /native bridge|object|function/.test(String(v));
		check('escape blocked: ' + label, !reached, JSON.stringify(v));
	}

	// 2. legitimate scripts keep their results
	doc.fields.Total.value = '';
	run('event.value = this.getField("A").value * 2;', 'Total');
	check('custom calculate (A * 2)', doc.fields.Total.value === '7', doc.fields.Total.value);

	run('AFSimple_Calculate("SUM", new Array("A", "B"));', 'Total');
	check('AFSimple_Calculate SUM', doc.fields.Total.value === '7.5', doc.fields.Total.value);

	let ev = run('AFRange_Validate(true, 0, true, 100);', 'Small', { name: 'Validate', value: '150' });
	check('AFRange_Validate rejects 150', ev.rc === false && doc.warning && doc.warning.less === 100, 'rc=' + ev.rc);
	ev = run('AFRange_Validate(true, 0, true, 100);', 'Small', { name: 'Validate', value: '50' });
	check('AFRange_Validate accepts 50', ev.rc === true, 'rc=' + ev.rc);

	ev = run('event.rc = /^[0-9]*$/.test(event.change); if (!event.rc) event.change = "";', 'Small', { name: 'Keystroke', change: 'x', value: '' });
	check('keystroke filter rejects a letter', ev.rc === false && ev.change === '', 'rc=' + ev.rc);
	ev = run('event.rc = /^[0-9]*$/.test(event.change);', 'Small', { name: 'Keystroke', change: '7', value: '' });
	check('keystroke filter accepts a digit', ev.rc === true, 'rc=' + ev.rc);

	run('this.getField("Secret").hidden = Number(this.getField("A").value) > 3;', 'Total');
	check('show/hide a field (hidden = true)', doc.fields.Secret.display === AscPDF.Api.Types.display.hidden, doc.fields.Secret.display);
	run('this.getField("Secret").hidden = false; event.value = this.getField("Secret").hidden ? "h" : "v";', 'Total');
	check('show/hide a field (hidden = false, read back)', doc.fields.Secret.display === 0 && doc.fields.Total.value === 'v', doc.fields.Total.value);

	run('event.value = event.target.name + ":" + this.getField("B").name + ":" + this.documentFileName;', 'Total');
	check('names and documentFileName', doc.fields.Total.value === 'Total:B:form.pdf', doc.fields.Total.value);

	run('var c = color.red; event.value = c.join(",") + "|" + (typeof AFNumber_Format);', 'Total');
	check('color constants and AF* present', doc.fields.Total.value === 'RGB,1,0,0|function', doc.fields.Total.value);

	run('event.value = String(this.getField("NoSuchField"));', 'Total');
	check('getField of a missing field is null', doc.fields.Total.value === 'null', doc.fields.Total.value);

	// 3. only with the sandbox: an endless loop is interrupted instead of freezing the editor
	if (!process.env.BASELINE) {
		const t0 = Date.now();
		doc.fields.Total.value = 'before';
		run('while (true) {}', 'Total');
		const ms = Date.now() - t0;
		check('endless loop interrupted', ms < 10000 && doc.fields.Total.value === 'before', ms + ' ms');
		run('event.value = "after";', 'Total');
		check('realm usable after an interrupted script', doc.fields.Total.value === 'after', doc.fields.Total.value);
	}

	check('native bridge never called', bridge.calls.length === 0, JSON.stringify(bridge.calls));
	console.log(failed ? `${failed} check(s) FAILED` : 'all checks passed');
	process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
