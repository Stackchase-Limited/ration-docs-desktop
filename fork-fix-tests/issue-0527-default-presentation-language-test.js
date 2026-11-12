/*
 * #527 "Not possible to define default language": a new document always got the language of
 * the blank template picked for the interface language (en-US for an English interface), and
 * there was no preference to change it. #143 (web-apps 869747e03c) added "Default document
 * language" to the DOCUMENT editor only; a new blank PRESENTATION still always started in the
 * interface language, so the language had to be set again in every new presentation.
 * (Spreadsheets already keep their spell-check language between files: sse-spellcheck-locale.)
 *
 * Now the presentation editor has File > Advanced settings > "Default presentation language"
 * (desktop app, offline, editing only): "Same as the interface" (unset, value 0 - the old
 * behaviour, still the default) or any editor language. It is stored as pe-settings-def-doc-lang
 * (an LCID) and, when the desktop opens a NEW BLANK presentation (editorConfig.newBlank, as
 * #2137's slide size), Main.js calls the existing asc_setDefaultLanguage with it unless the
 * presentation already has that language. Existing files and templates are never touched.
 *
 * What runs: from web-apps the REAL load-time lines of PE Main.js, the REAL language-list builder
 * of PE FileMenuPanels.js over the REAL LanguageInfo.js, the REAL save branch of PE applySettings;
 * from sdkjs (unchanged) the REAL slide asc_setDefaultLanguage / asc_getDefaultLanguage and
 * CPresentation.SetDefaultLanguage / SetLanguage / setDefaultTextStyle / GetDefaultLanguage
 * against a stub presentation, to show the value lands in the presentation's default text style
 * (defaultTextStyle level 9 DefaultRunPr.Lang - what the status-bar language picker also sets).
 *
 * NOT claimed: the settings panel rendering and the combo's search (needs a GUI look); the
 * "modified" mark / undo step that setting the language on a new blank presentation adds (same
 * as #2137's slide size - check in the app); that placeholder text whose layout carries its own
 * lang follows the default (it does not, as with the status-bar picker); spreadsheets;
 * picking the OS language automatically.
 *
 *   RD_WEBAPPS=<web-apps> (default ../web-apps), RD_REPO=<sdkjs> (default ../sdkjs)
 *   BASELINE=1 reads web-apps at WEBAPPS_BASE_REF (parent of the fix) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
// Pinned to the parent of the fix commit, never HEAD.
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '16a617195b^';

function wsrc(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
}
const ssrc = (rel) => fs.readFileSync(path.join(SDKJS, rel), 'utf8');

function blockEnd(text, open) {
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return i + 1;
	}
	throw new Error('unbalanced braces');
}
function stmt(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return text.slice(at, blockEnd(text, text.indexOf('{', at))) + ';';
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

/* --- sdkjs (unchanged): slide asc_setDefaultLanguage on a stub presentation --- */
const slideApi = ssrc('slide/api.js');
const pres = ssrc('slide/Editor/Format/Presentation.js');
function makeSdk(initialLang) {
	function CTextPr() { this.Lang = { Val: undefined }; }
	function CParaPr() { this.DefaultRunPr = null; }
	function style(lang) {
		const s = { levels: [], createDuplicate() { const d = style(); d.levels = this.levels.map((l) => l && { DefaultRunPr: l.DefaultRunPr && { Lang: { Val: l.DefaultRunPr.Lang.Val } } }); return d; } };
		if (lang !== undefined) { s.levels[9] = new CParaPr(); s.levels[9].DefaultRunPr = new CTextPr(); s.levels[9].DefaultRunPr.Lang.Val = lang; }
		return s;
	}
	const doc = {
		defaultTextStyle: style(initialLang), changes: [], actions: 0,
		Document_Is_SelectionLocked: () => false,
		StartAction() { this.actions++; }, FinalizeAction() {},
		RestartSpellCheck() {}, Recalculate() {}, Document_UpdateInterfaceState() {},
	};
	const History = { Add(c) { doc.changes.push(c); } };
	const AscFormat = { TextListStyle: function () { return style(); }, isRealNumber: (n) => typeof n === 'number' && isFinite(n) };
	const AscDFH = { CChangesDrawingsObjectNoId: function () {}, historyitem_Presentation_SetDefaultTextStyle: 1 };
	new Function('CPresentation', 'History', 'AscFormat', 'AscDFH', 'CParaPr', 'CTextPr',
		stmt(pres, 'CPresentation.prototype.setDefaultTextStyle = function') +
		stmt(pres, 'CPresentation.prototype.SetDefaultLanguage = function') +
		stmt(pres, 'CPresentation.prototype.SetLanguage = function') +
		stmt(pres, 'CPresentation.prototype.GetDefaultLanguage = function'))({ prototype: doc }, History, AscFormat, AscDFH, CParaPr, CTextPr);
	function asc_docs_api() { this.WordControl = { m_oLogicDocument: doc }; }
	new Function('asc_docs_api', 'AscCommon', 'AscDFH',
		stmt(slideApi, 'asc_docs_api.prototype.asc_setDefaultLanguage = function') +
		stmt(slideApi, 'asc_docs_api.prototype.asc_getDefaultLanguage = function'))(
		asc_docs_api, { changestype_PresDefaultLang: 1 }, { historydescription_Document_SetDefaultLanguage: 1 });
	return { api: new asc_docs_api(), doc, lang: () => doc.GetDefaultLanguage() };
}

/* --- web-apps: PE Main.js load-time lines --- */
const main = wsrc('apps/presentationeditor/main/app/controller/Main.js');
function runMainLoad(stored, newBlank, sdk, offline = true) {
	const at = main.indexOf('value = parseInt(Common.localStorage.getItem("pe-settings-def-doc-lang"))');
	assert.notStrictEqual(at, -1, 'PE Main.js does not read pe-settings-def-doc-lang');
	const endMarker = 'me.api.asc_setDefaultLanguage(value);';
	const end = main.indexOf(endMarker, at);
	assert.notStrictEqual(end, -1, 'PE Main.js does not call asc_setDefaultLanguage');
	const internal = {};
	const Common = {
		localStorage: { getItem: (k) => (k === 'pe-settings-def-doc-lang' && stored !== undefined ? String(stored) : null) },
		Utils: { InternalSettings: { set: (k, v) => { internal[k] = v; } } },
	};
	new Function('Common', 'me', 'var value;' + main.slice(at, end + endMarker.length))(
		Common, { api: sdk.api, editorConfig: { newBlank }, appOptions: { isDesktopApp: true, isOffline: offline } });
	return internal;
}

const EN_US = 0x0409, EN_GB = 0x0809, FR_FR = 0x040C;
check('new blank presentation: the chosen default language (en-GB) becomes its language', () => {
	const sdk = makeSdk(EN_US);
	runMainLoad(EN_GB, true, sdk);
	assert.strictEqual(sdk.lang(), EN_GB);
	assert.strictEqual(sdk.doc.actions, 1);
});
check('an existing (not new blank) presentation is never touched', () => {
	const sdk = makeSdk(FR_FR);
	runMainLoad(EN_GB, false, sdk);
	assert.strictEqual(sdk.lang(), FR_FR);
	assert.strictEqual(sdk.doc.actions, 0);
});
check('a cloud (not offline) presentation is never touched', () => {
	const sdk = makeSdk(EN_US);
	runMainLoad(EN_GB, true, sdk, false);
	assert.strictEqual(sdk.lang(), EN_US);
});
check('unset ("Same as the interface") leaves the blank template language, no action', () => {
	const sdk = makeSdk(EN_US);
	const internal = runMainLoad(undefined, true, sdk);
	assert.strictEqual(sdk.lang(), EN_US);
	assert.strictEqual(sdk.doc.actions, 0);
	assert.strictEqual(internal['pe-settings-def-doc-lang'], 0);
});
check('already the chosen language: no action (no undo step, no "modified")', () => {
	const sdk = makeSdk(EN_GB);
	runMainLoad(EN_GB, true, sdk);
	assert.strictEqual(sdk.doc.actions, 0);
});

/* --- web-apps: PE settings panel --- */
const panels = wsrc('apps/presentationeditor/main/app/view/FileMenuPanels.js');
check('settings panel offers "Same as the interface" plus the editor languages', () => {
	const at = panels.indexOf('var docLangs = [];');
	assert.notStrictEqual(at, -1, 'no language list in PE FileMenuPanels.js');
	const end = panels.indexOf('docLangs.unshift(', at);
	const code = panels.slice(at, panels.indexOf(';', end) + 1);
	const win = {};
	new Function('window', 'Common', wsrc('apps/common/main/lib/util/LanguageInfo.js'))(win, win.Common = {});
	const _ = { each: (o, f) => Object.keys(o).forEach((k) => f(o[k], k)) };
	const list = new Function('_', 'Common', code + '\nreturn docLangs;').call({ txtDocLangInterface: 'Same as the interface' }, _, win.Common);
	assert.deepStrictEqual(list[0], { value: 0, displayValue: 'Same as the interface', displayValueEn: '' });
	const enGB = list.find((l) => l.value === EN_GB);
	assert(enGB && /United Kingdom|Great Britain/.test(enGB.displayValueEn), 'en-GB missing: ' + JSON.stringify(enGB));
	assert(list.length > 40, 'only ' + list.length + ' languages');
	assert(/id="fms-cmb-doc-lang"/.test(panels), 'no combo slot in the template');
	assert(/\$\('tr\.doc-lang', this\.el\)\[mode\.isEdit && mode\.isDesktopApp && mode\.isOffline/.test(panels), 'row not limited to desktop offline editing');
	assert(/txtDocLang:\s*'[^']+'/.test(panels) && /txtDocLangInterface:\s*'[^']+'/.test(panels), 'strings missing');
});
check('Apply stores the choice (desktop offline editing only)', () => {
	const marker = 'if (this.mode.isEdit && this.mode.isDesktopApp && this.mode.isOffline) {';
	const apply = panels.indexOf(marker, panels.indexOf('applySettings: function'));
	assert.notStrictEqual(apply, -1, 'save branch not found');
	const code = panels.slice(apply, blockEnd(panels, panels.indexOf('{', apply)));
	const run = (mode) => {
		const stored = {};
		const Common = { localStorage: { setBool() {}, setItem: (k, v) => { stored[k] = v; } }, Utils: { InternalSettings: { set() {} } } };
		new Function('Common', code).call({ mode, rbNewFormatOdf: { getValue: () => false }, cmbDocLang: { getValue: () => EN_GB } }, Common);
		return stored;
	};
	assert.strictEqual(run({ isEdit: true, isDesktopApp: true, isOffline: true })['pe-settings-def-doc-lang'], EN_GB);
	assert.strictEqual(run({ isEdit: true, isDesktopApp: true, isOffline: false })['pe-settings-def-doc-lang'], undefined);
});
check('en.json has the two labels', () => {
	const en = JSON.parse(wsrc('apps/presentationeditor/main/locale/en.json'));
	assert(en['PE.Views.FileMenuPanels.Settings.txtDocLang'] && en['PE.Views.FileMenuPanels.Settings.txtDocLangInterface']);
});

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
