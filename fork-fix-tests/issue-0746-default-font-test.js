/*
 * #746 - "Option to use Default Font": a new blank document always starts in
 * the blank template's font (converter/empty/<lang>/new.docx: docDefaults
 * rFonts minorHAnsi -> theme Arial, sz 22 = 11 pt); changing it meant editing
 * the installed templates by hand.
 *
 * Fix, following #2090 / #143 (new blank documents are told apart by the
 * desktop's blank=true -> editorConfig.newBlank):
 *  - sdkjs: CDocument.SetDefaultTextFont(fontName, fontSize) sets the Latin font
 *    (ascii/hAnsi, theme refs dropped) and size (sz/szCs) of docDefaults
 *    rPrDefault, recorded as the existing CChangesStylesChangeDefaultTextPr
 *    (replayed by x2t on the desktop save); nothing recorded when unchanged.
 *    api.asc_setDefaultTextFont loads the font first.
 *  - web-apps (document editor, desktop offline): Advanced settings > "Default
 *    font" (font + size, each "Same as the template" = unset = today's
 *    behaviour), stored as de-settings-def-font-name/-size; Main.js calls the
 *    api only for a new blank document.
 *
 * This test brace-extracts and runs
 *  1. the real CDocument.SetDefaultTextFont / GetDefaultTextFont on a stub
 *     document/styles (plain objects with Copy/IsEqual): font+size -> a change
 *     with the new ascii/hAnsi and sizes, East Asian / CS theme fonts kept;
 *     same values again -> no change; size only -> font kept;
 *  2. the real asc_setDefaultTextFont with a stub font loader, sync and async
 *     (the change waits for the font and the LoadFont action is ended);
 *  3. the real #746 block of the document editor's onDocumentContentReady:
 *     new blank + setting -> api called; opened document (no newBlank) or unset
 *     -> not called;
 *  4. the Advanced settings source: rows, combo boxes, both keys stored on Apply.
 *  Baseline: none of it exists -> FAILS.
 *
 * Checked separately (not by this test): headless docbuilder with the built
 * word sdk: en-US new.docx + asc_setDefaultTextFont("Courier New", 14) saves
 * <w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:eastAsiaTheme=
 * "minorHAnsi" w:cstheme="minorBidi"/><w:sz w:val="28"/><w:szCs w:val="28"/>.
 * NOT claimed: the settings panel in the running editor, the font list being
 * filled (needs the toolbar's fonts, GUI check), the desktop change replay.
 * Spreadsheets and presentations are not covered.
 *
 * Env: RD_REPO     sdkjs checkout    (default ../sdkjs)
 *      RD_WEBAPPS  web-apps checkout (default ../web-apps)
 *      BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || 'c951cbc881^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '2518219af3^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
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
function extract(text, marker, what) {
	const at = text.indexOf(marker);
	assert.ok(at !== -1, `${what}: not found - no default font for new documents`);
	return block(text, at);
}

/* ---- 1. CDocument ---- */
const doc = src(SDKJS, BASE_REF, 'word/Editor/Document.js');
const setFn = extract(doc, 'CDocument.prototype.SetDefaultTextFont = function', 'CDocument.SetDefaultTextFont');
const getFn = extract(doc, 'CDocument.prototype.GetDefaultTextFont = function', 'CDocument.GetDefaultTextFont');

const STUBS = `
function TextPr(o) { Object.assign(this, o); }
TextPr.prototype.Copy = function () { return new TextPr({ RFonts: Object.assign({}, this.RFonts), FontSize: this.FontSize, FontSizeCS: this.FontSizeCS }); };
TextPr.prototype.IsEqual = function (o) { return JSON.stringify(this) === JSON.stringify(o); };
function CChangesStylesChangeDefaultTextPr(cls, oldV, newV) { this.Old = oldV; this.New = newV; }
function CDocument() {}
var blank = function () { return new TextPr({ RFonts: { AsciiTheme: 'minorHAnsi', HAnsiTheme: 'minorHAnsi', EastAsiaTheme: 'minorHAnsi', CSTheme: 'minorBidi' }, FontSize: 11, FontSizeCS: 11 }); };
`;
const ctx = {};
vm.createContext(ctx);
vm.runInContext(STUBS + setFn + ';' + getFn + `;
this.make = function () {
	var d = new CDocument(), log = [];
	var styles = { Default: { TextPr: blank() }, Get_DefaultTextPr: function () { return this.Default.TextPr; }, OnChangeDefaultTextPr: function () { log.push('onchange'); } };
	d.GetStyles = function () { return styles; };
	d.History = { Add: function (c) { log.push(c); } };
	d.Recalculate = function () { log.push('recalc'); };
	d.UpdateInterface = function () {};
	return { d: d, styles: styles, log: log };
};`, ctx);

let t = ctx.make();
t.d.SetDefaultTextFont('Courier New', 14);
const ch = t.log.find(x => x && x.New);
assert.ok(ch, 'no change recorded for a new default font');
const f = t.styles.Default.TextPr;
console.log(`set Courier New 14: rFonts ${JSON.stringify(f.RFonts)} size ${f.FontSize}/${f.FontSizeCS}; log ${t.log.map(x => x.New ? 'change' : x).join(',')}`);
assert.strictEqual(f.RFonts.Ascii.Name, 'Courier New');
assert.strictEqual(f.RFonts.HAnsi.Name, 'Courier New');
assert.strictEqual(f.RFonts.AsciiTheme, undefined, 'theme font still overrides the chosen one');
assert.strictEqual(f.RFonts.HAnsiTheme, undefined);
assert.strictEqual(f.RFonts.EastAsiaTheme, 'minorHAnsi', 'East Asian font must be kept');
assert.strictEqual(f.RFonts.CSTheme, 'minorBidi', 'complex script font must be kept');
assert.strictEqual(f.FontSize, 14);
assert.strictEqual(f.FontSizeCS, 14);
assert.strictEqual(ch.Old.FontSize, 11, 'the change must carry the old value for undo');
assert.ok(t.log.includes('recalc'), 'the document is not laid out again');
assert.deepStrictEqual(JSON.parse(JSON.stringify(t.d.GetDefaultTextFont())), { Name: 'Courier New', Size: 14 });

const before = t.log.length;
t.d.SetDefaultTextFont('Courier New', 14);
assert.strictEqual(t.log.length, before, 'setting the same font again must record nothing');

t = ctx.make();
t.d.SetDefaultTextFont('', 12);
assert.strictEqual(t.styles.Default.TextPr.RFonts.AsciiTheme, 'minorHAnsi', 'size only must keep the font');
assert.strictEqual(t.styles.Default.TextPr.FontSize, 12);
console.log('same again -> nothing recorded; size only -> font kept');

/* ---- 2. the API ---- */
const api = src(SDKJS, BASE_REF, 'word/api.js');
const apiFn = extract(api, 'asc_docs_api.prototype.asc_setDefaultTextFont = function', 'asc_setDefaultTextFont');
for (const isAsync of [false, true]) {
	const c = { calls: [] };
	vm.createContext(c);
	vm.runInContext(`
		var c_oAscAsyncActionType = { Information: 'info' }, c_oAscAsyncAction = { LoadFont: 'loadfont' };
		var AscDFH = { historydescription_Document_SetTextFontName: 1 };
		var pending = null;
		var AscCommon = { changestype_Document_Styles: 's', g_font_loader: { LoadFont: function (info, cb, args) {
			calls.push('load ' + info.Name);
			if (${isAsync}) { pending = function () { cb.call(args, info); }; return true; }
			return false;
		} } };
		var g_fontApplication = { GetFontInfo: function (n) { return { Name: n }; } };
		function asc_docs_api() {}
		${apiFn};
		var a = new asc_docs_api();
		a.sync_EndAction = function (t, x) { calls.push('end ' + x); };
		a.private_GetLogicDocument = function () { return {
			IsSelectionLocked: function () { return false; },
			StartAction: function () { calls.push('start'); },
			SetDefaultTextFont: function (n, s) { calls.push('set ' + n + ' ' + s); },
			FinalizeAction: function () { calls.push('finalize'); } }; };
		a.asc_setDefaultTextFont('Courier New', '14');
		calls.push('|');
		pending && pending();
	`, c);
	console.log(`api (${isAsync ? 'font loads async' : 'font ready'}): ${c.calls.join(', ')}`);
	const want = isAsync
		? ['load Courier New', '|', 'end loadfont', 'start', 'set Courier New 14', 'finalize']
		: ['load Courier New', 'start', 'set Courier New 14', 'finalize', '|'];
	assert.deepStrictEqual(Array.from(c.calls), want);
}

/* ---- 3. web-apps: new blank documents only ---- */
const main = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/controller/Main.js');
const at = main.indexOf('// default font and size of a new blank desktop document (#746)');
assert.ok(at !== -1, 'Main.js: no #746 hand-off');
const end = main.indexOf('me.api.asc_setDefaultTextFont(defFont, defSize);', at);
assert.ok(end !== -1, 'Main.js: asc_setDefaultTextFont not called');
const snippet = main.slice(at, end + 'me.api.asc_setDefaultTextFont(defFont, defSize);'.length);
for (const [newBlank, stored, want] of [[true, { 'de-settings-def-font-name': 'Consolas', 'de-settings-def-font-size': '12' }, 'Consolas 12'],
	[true, { 'de-settings-def-font-size': '10.5' }, ' 10.5'], [false, { 'de-settings-def-font-name': 'Consolas' }, ''], [true, {}, '']]) {
	const c = { calls: [], internal: {} };
	vm.createContext(c);
	vm.runInContext(`
		var Common = { localStorage: { getItem: function (k) { return ${JSON.stringify(stored)}[k] || null; } },
			Utils: { InternalSettings: { set: function (k, v) { internal[k] = v; } } } };
		var me = { editorConfig: { newBlank: ${newBlank} }, api: { asc_setDefaultTextFont: function (n, s) { calls.push(n + ' ' + s); } } };
		${snippet}
	`, c);
	console.log(`newBlank=${newBlank} stored=${JSON.stringify(stored)} -> ${c.calls.join(',') || '(not called)'}`);
	assert.strictEqual(c.calls.join(','), want);
}

/* ---- 4. Advanced settings ---- */
const panels = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/view/FileMenuPanels.js');
assert.ok(/'<tr class="edit text-dir">',\s*'<td colspan="2"><div[^']*id="fms-cmb-def-font"/.test(panels), 'no Default font row (desktop offline rows)');
assert.ok(panels.includes('this.cmbDefFont = new Common.UI.ComboBox(') && panels.includes('this.cmbDefFontSize = new Common.UI.ComboBox('));
const apply = block(panels, panels.indexOf('applySettings: function()'));
assert.ok(apply.includes('setItem("de-settings-def-font-name"') && apply.includes('setItem("de-settings-def-font-size"'), 'Apply does not store the default font');
const en = JSON.parse(src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/documenteditor/main/locale/en.json'));
assert.ok(en['DE.Views.FileMenuPanels.Settings.txtDefFont'] && en['DE.Views.FileMenuPanels.Settings.txtDefFontTemplate']);
console.log('Advanced settings: Default font + size rows, stored on Apply');

console.log('PASS #746: a chosen default font and size are applied to new blank documents only');
