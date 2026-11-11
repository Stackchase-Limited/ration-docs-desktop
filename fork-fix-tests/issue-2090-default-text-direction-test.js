/*
 * #2090 - "Add option to set RTL layout as default": people writing Arabic,
 * Hebrew or Persian with a left-to-right interface had to switch every new
 * document to right-to-left by hand.
 *
 * What existed: the desktop takes a new blank document from
 * <converter>/empty/<lang>/new.docx; only the ar-SA, he-IL and ur-PK blanks
 * carry <w:bidi/> in styles.xml docDefaults, so only those interface languages
 * got RTL paragraphs. There was no setting, nothing in sdkjs could change the
 * document's default paragraph direction, and the editor could not tell a new
 * blank document from a template, a recovered or an opened file.
 *
 * The fix, across three repos:
 *  - desktop-sdk CCefViewEditor::CreateLocalFile adds "&blank=true" to the
 *    editor URL for a blank (non-template) new file;
 *  - web-apps index.html.desktop passes it on as editorConfig.newBlank; the
 *    document editor has Advanced settings > "Default text direction"
 *    (de-settings-def-text-rtl; unset = the interface language's direction,
 *    i.e. what the blank already gives) and, for a new blank document only,
 *    calls api.asc_setDefaultRtlTextDirection(value);
 *  - sdkjs asc_setDefaultRtlTextDirection -> CDocument.SetDefaultParagraphBidi
 *    records the existing CChangesStylesChangeDefaultParaPr (so the desktop
 *    save, which replays changes in x2t, writes docDefaults w:bidi), and
 *    CStyles.Refresh_RecalcData now re-lays out all paragraphs for that change.
 *
 * This extracts by brace matching the REAL sdkjs functions (api, CDocument,
 * CStyles.Refresh_RecalcData, the change class), the REAL web-apps
 * getEditorConfig of index.html.desktop and the REAL settings block of the
 * document editor's onDocumentContentReady, and runs them on stubs. For
 * desktop-sdk it only checks the source of CreateLocalFile (C++, not compiled
 * here): the parameter is added only when no template URL is set, before load.
 *
 * Claimed: a new blank document gets the chosen direction recorded as a
 * replayable docDefaults change; nothing is recorded when the direction is
 * already right (LTR user, LTR blank); unset follows the interface language;
 * opened documents/templates (no newBlank) are never changed.
 * NOT claimed: layout/rendering and the x2t round trip (done headless with the
 * real sdk-all build for the commit: en-US blank -> RTL gives
 * <w:pPrDefault><w:pPr><w:bidi w:val="true"/>... in the saved styles.xml), the
 * settings panel UI, and that the desktop really sends blank=true (needs the
 * rebuilt desktop-sdk and a GUI check). Undo right after creation reverts the
 * direction (it is an ordinary history point).
 *
 * RD_REPO=<sdkjs> (default ../sdkjs next to fork-fix-tests),
 * RD_WEBAPPS=<web-apps>, RD_DESKTOP_SDK=<desktop-sdk>. BASELINE=1 reads the
 * sources with git show at BASE_REF / WEBAPPS_BASE_REF / DESKTOP_SDK_BASE_REF,
 * where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
const DSDK = process.env.RD_DESKTOP_SDK || path.join(ROOT, 'desktop-sdk');
// Pinned to the parents of the commits that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'd295746b42^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '03aad1a7fe^';
const DESKTOP_SDK_BASE_REF = process.env.DESKTOP_SDK_BASE_REF || '7281e56a^';

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

function extract(text, marker, after) {
	const at = text.indexOf(marker, after ? text.indexOf(after) : 0);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}

/* ---------------- sdkjs ---------------- */
const apiJs = src(SDKJS, BASE_REF, 'word/api.js');
const docJs = src(SDKJS, BASE_REF, 'word/Editor/Document.js');
const stylesJs = src(SDKJS, BASE_REF, 'word/Editor/Styles.js');
const changesJs = src(SDKJS, BASE_REF, 'word/Editor/StylesChanges.js');

const AscDFH = {
	historyitem_Styles_Add: 1, historyitem_Styles_Remove: 2,
	historyitem_Styles_ChangeDefaultTextPr: 3, historyitem_Styles_ChangeDefaultParaPr: 4,
	historydescription_Document_SetParagraphBidi: 0x01c3,
	CChangesBaseObjectValue: function (Class, Old, New) { this.Class = Class; this.Old = Old; this.New = New; },
};
AscDFH.CChangesBaseObjectValue.prototype = {};

function ParaPr(bidi) { this.Bidi = bidi; this.Spacing = { After: 200 }; }
ParaPr.prototype.Copy = function () { const p = new ParaPr(this.Bidi); p.Spacing = { After: this.Spacing.After }; return p; };

function makeSdk() {
	const CChangesStylesChangeDefaultParaPr = new Function('AscDFH', 'CParaPr',
		extract(changesJs, 'function CChangesStylesChangeDefaultParaPr(') + '\n' +
		'CChangesStylesChangeDefaultParaPr.prototype = Object.create(AscDFH.CChangesBaseObjectValue.prototype);\n' +
		'CChangesStylesChangeDefaultParaPr.prototype.Type = AscDFH.historyitem_Styles_ChangeDefaultParaPr;\n' +
		extract(changesJs, 'CChangesStylesChangeDefaultParaPr.prototype.private_SetValue') + ';\n' +
		'return CChangesStylesChangeDefaultParaPr;')(AscDFH, ParaPr);

	function CStyles() { this.Default = { ParaPr: new ParaPr(undefined), Paragraph: 'Normal' }; this.refreshed = []; }
	CStyles.prototype.Get_DefaultParaPr = function () { return this.Default.ParaPr; };
	CStyles.prototype.Refresh_RecalcData2 = function (id) { this.refreshed.push(id); };
	const refresh = extract(stylesJs, 'Refresh_RecalcData : function(Data)', 'CStyles.prototype =');
	CStyles.prototype.Refresh_RecalcData = new Function('AscDFH', 'private_GetWordLogicDocument',
		'return function' + refresh.slice(refresh.indexOf('(')))(AscDFH, () => null);

	const log = [];
	function CDocument() {
		this.Styles = new CStyles();
		this.History = { Add: c => log.push(['change', c]) };
	}
	CDocument.prototype.GetStyles = function () { return this.Styles; };
	CDocument.prototype.Recalculate = function () { log.push(['recalc']); };
	CDocument.prototype.UpdateInterface = function () {};
	CDocument.prototype.IsSelectionLocked = function () { return false; };
	CDocument.prototype.StartAction = function (d) { log.push(['start', d]); };
	CDocument.prototype.FinalizeAction = function () { log.push(['finalize']); };
	new Function('CDocument', 'CChangesStylesChangeDefaultParaPr',
		extract(docJs, 'CDocument.prototype.SetDefaultParagraphBidi = function') + ';\n' +
		extract(docJs, 'CDocument.prototype.GetDefaultParagraphBidi = function') + ';')(CDocument, CChangesStylesChangeDefaultParaPr);

	function asc_docs_api(doc) { this.doc = doc; }
	asc_docs_api.prototype.private_GetLogicDocument = function () { return this.doc; };
	new Function('asc_docs_api', 'AscCommon', 'AscDFH',
		extract(apiJs, 'asc_docs_api.prototype.asc_setDefaultRtlTextDirection = function') + ';')(
		asc_docs_api, { changestype_Document_Styles: 13 }, AscDFH);
	return { asc_docs_api, CDocument, CChangesStylesChangeDefaultParaPr, log };
}

check('sdkjs: RTL on an LTR blank records a docDefaults change and re-lays out', () => {
	const { asc_docs_api, CDocument, log } = makeSdk();
	const doc = new CDocument(), api = new asc_docs_api(doc);
	const before = doc.Styles.Default.ParaPr;
	api.asc_setDefaultRtlTextDirection(true);
	const changes = log.filter(e => e[0] === 'change').map(e => e[1]);
	assert.strictEqual(changes.length, 1, 'one history change');
	assert.strictEqual(changes[0].Type, AscDFH.historyitem_Styles_ChangeDefaultParaPr);
	assert.strictEqual(changes[0].Old, before, 'old value is the previous object (undo restores it)');
	assert.strictEqual(changes[0].New.Bidi, true);
	assert.strictEqual(changes[0].New.Spacing.After, 200, 'other default paragraph properties kept');
	assert.strictEqual(doc.Styles.Default.ParaPr.Bidi, true);
	assert.strictEqual(doc.GetDefaultParagraphBidi(), true);
	assert.strictEqual(before.Bidi, undefined, 'old object not mutated');
	assert.ok(log.some(e => e[0] === 'recalc'), 'recalculated');
	assert.deepStrictEqual(log[0], ['start', AscDFH.historydescription_Document_SetParagraphBidi]);
	assert.deepStrictEqual(log[log.length - 1], ['finalize']);

	// replay (what x2t does with the saved change, or a co-author receiving it)
	const fresh = new CDocument();
	changes[0].Class = fresh.Styles;
	changes[0].private_SetValue(changes[0].New);
	assert.strictEqual(fresh.Styles.Default.ParaPr.Bidi, true, 'replayed change sets docDefaults bidi');
});

check('sdkjs: no history point when the direction is already the requested one', () => {
	const { asc_docs_api, CDocument, log } = makeSdk();
	const doc = new CDocument(), api = new asc_docs_api(doc);
	api.asc_setDefaultRtlTextDirection(false);
	assert.strictEqual(log.length, 0, 'LTR on an LTR blank: nothing recorded');
	doc.Styles.Default.ParaPr.Bidi = true;
	api.asc_setDefaultRtlTextDirection(true);
	assert.strictEqual(log.length, 0, 'RTL on an RTL (he-IL) blank: nothing recorded');
	api.asc_setDefaultRtlTextDirection(false);
	assert.strictEqual(log.filter(e => e[0] === 'change').length, 1, 'LTR on an RTL blank is recorded');
	assert.strictEqual(doc.Styles.Default.ParaPr.Bidi, false);
});

check('sdkjs: CStyles.Refresh_RecalcData re-lays out all paragraphs for a default ParaPr change', () => {
	const { CDocument } = makeSdk();
	const styles = new CDocument().Styles;
	styles.Refresh_RecalcData({ Type: AscDFH.historyitem_Styles_ChangeDefaultParaPr });
	assert.deepStrictEqual(styles.refreshed, ['Normal'], 'Refresh_RecalcData2(default paragraph style)');
});

check('sdkjs: asc_setDefaultRtlTextDirection is exported', () => {
	assert.ok(/asc_docs_api\.prototype\['asc_setDefaultRtlTextDirection'\]\s*=\s*asc_docs_api\.prototype\.asc_setDefaultRtlTextDirection;/.test(apiJs));
});

/* ---------------- web-apps ---------------- */
const indexDesktop = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/api/documents/index.html.desktop');
const mainJs = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/controller/Main.js');
const panelsJs = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/view/FileMenuPanels.js');

check('web-apps: index.html.desktop turns blank=true into editorConfig.newBlank', () => {
	const getEditorConfig = new Function(extract(indexDesktop, 'function getEditorConfig(') + '\nreturn getEditorConfig;')();
	assert.strictEqual(getEditorConfig({ blank: 'true', lang: 'en' }).newBlank, true);
	assert.strictEqual(getEditorConfig({ lang: 'en' }).newBlank, false);
});

/* the settings lines of onDocumentContentReady, from the read of de-settings-def-text-rtl
   through the statement that calls asc_setDefaultRtlTextDirection */
function runDocReady({ stored, lang, newBlank }) {
	const a = mainJs.indexOf('value = Common.localStorage.getBool("de-settings-def-text-rtl"');
	assert.notStrictEqual(a, -1, 'de-settings-def-text-rtl not read in Main.js');
	const b = mainJs.indexOf('\n', mainJs.indexOf('asc_setDefaultRtlTextDirection', a));
	const calls = [], internal = {};
	const Common = {
		localStorage: { getBool: (k, def) => (k in stored ? stored[k] : def) },
		Locale: { isCurrentLanguageRtl: () => /^(ar|he|ur)$/i.test(lang) && lang },
		Utils: { InternalSettings: { set: (k, v) => { internal[k] = v; } } },
	};
	const me = { editorConfig: { newBlank }, api: { asc_setDefaultRtlTextDirection: v => calls.push(v) } };
	new Function('me', 'Common', 'var value;\n' + mainJs.slice(a, b))(me, Common);
	return { calls, internal };
}

check('web-apps: a new blank document gets the chosen direction', () => {
	assert.deepStrictEqual(runDocReady({ stored: { 'de-settings-def-text-rtl': true }, lang: 'en', newBlank: true }).calls, [true]);
	assert.deepStrictEqual(runDocReady({ stored: { 'de-settings-def-text-rtl': false }, lang: 'he', newBlank: true }).calls, [false]);
});

check('web-apps: unset follows the interface language (what the blank template already has)', () => {
	assert.deepStrictEqual(runDocReady({ stored: {}, lang: 'he', newBlank: true }).calls, [true]);
	assert.deepStrictEqual(runDocReady({ stored: {}, lang: 'en', newBlank: true }).calls, [false]);
	assert.strictEqual(runDocReady({ stored: {}, lang: 'ar', newBlank: false }).internal['de-settings-def-text-rtl'], true);
});

check('web-apps: opened documents and templates are never changed', () => {
	assert.deepStrictEqual(runDocReady({ stored: { 'de-settings-def-text-rtl': true }, lang: 'en', newBlank: false }).calls, []);
	assert.deepStrictEqual(runDocReady({ stored: { 'de-settings-def-text-rtl': true }, lang: 'en', newBlank: undefined }).calls, []);
});

check('web-apps: Advanced settings saves the choice under de-settings-def-text-rtl (desktop only)', () => {
	assert.ok(/Common\.localStorage\.setBool\("de-settings-def-text-rtl", this\.rbTextRtl\.getValue\(\)\)/.test(panelsJs), 'applySettings stores it');
	assert.ok(/\$\('tr\.text-dir', this\.el\)\[mode\.isEdit && mode\.isDesktopApp && mode\.isOffline/.test(panelsJs), 'shown in the desktop editor only');
});

/* ---------------- desktop-sdk (source check, C++ not compiled) ---------------- */
check('desktop-sdk: CreateLocalFile marks blank (non-template) new files with blank=true', () => {
	const cef = src(DSDK, DESKTOP_SDK_BASE_REF, 'ChromiumBasedEditors/lib/src/cefview.cpp');
	const body = extract(cef, 'void CCefViewEditor::CreateLocalFile(const AscEditorType& nFileFormatSrc, const std::wstring& sName, const std::wstring& sTemplatePath)');
	const m = body.match(/if \(m_pInternal->m_sTemplateUrl\.empty\(\)\)\s*sParams \+= L"&blank=true";/);
	assert.ok(m, 'blank=true guarded by an empty template URL');
	assert.ok(body.indexOf(m[0]) < body.indexOf('this->load(sUrl + sParams)'), 'added before the editor URL is loaded');
	assert.ok(body.indexOf('m_sTemplateUrl = sTemplatePath') < body.indexOf(m[0]), 'template URL is set before the check');
});

if (failures) {
	console.log(`FAIL #2090: ${failures} check(s) failed` + (process.env.BASELINE ? ' (BASELINE, expected)' : ''));
	process.exit(1);
}
console.log('PASS #2090: new blank documents take the default text direction' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
