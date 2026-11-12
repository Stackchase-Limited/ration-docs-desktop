/*
 * #143 "Ability to change default language for new document" (with #626 "Default a new
 * document language to system language"): a new blank document always got the language of
 * the blank template picked for the interface language (converter/empty/<lang>/new.docx;
 * en-US for an English interface), and there was no setting to change it - users edited the
 * installed templates by hand.
 *
 * Now the document editor has File > Advanced settings > "Default document language" next
 * to #2090's "Default text direction" (desktop app, offline, editing only): "Same as the
 * interface" (unset, value 0 - what happened before) or any editor language. It is stored as
 * de-settings-def-doc-lang (an LCID) and, when the desktop opens a NEW BLANK document
 * (editorConfig.newBlank, from the blank=true URL parameter, as #2090), Main.js calls the
 * existing asc_setDefaultLanguage with it unless the document already has that language.
 * Existing documents and templates are never touched.
 *
 * What runs: from web-apps the REAL load-time lines of DE Main.js, the REAL language-list
 * builder of FileMenuPanels.js over the REAL LanguageInfo.js, the REAL save branch of
 * FileMenuPanels applySettings; from sdkjs (unchanged) the REAL asc_setDefaultLanguage,
 * CDocument.SetDefaultLanguage/GetDefaultLanguage against a stub document, to show the
 * value lands in the document's default text properties (docDefaults w:lang).
 *
 * NOT claimed: the settings panel rendering and the combo's search (needs a GUI look); the
 * "modified" mark / undo step that setting the language on a new blank document adds (same
 * as #2090's direction - check in the app); presentations/spreadsheets; typing-language
 * detection (Settings > "Spell check language detection") which can still switch the
 * language of new text; picking the OS language automatically (#626) - the user picks it.
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
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '869747e03c^';

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

/* --- sdkjs (unchanged): asc_setDefaultLanguage on a stub document --- */
const wordApi = ssrc('word/api.js');
const wordDoc = ssrc('word/Editor/Document.js');
function makeSdk(initialLang) {
	const doc = {
		styles: { Default: { TextPr: { Lang: { Val: initialLang } } } },
		History: { Add(c) { doc.changes.push(c); } }, changes: [], actions: 0,
		GetStyles() { return this.styles; },
		Document_Is_SelectionLocked: () => false,
		StartAction() { this.actions++; }, FinalizeAction() {},
		RestartSpellCheck() {}, UpdateInterface() {},
	};
	function CChangesDocumentDefaultLanguage(d, o, n) { this.Old = o; this.New = n; }
	new Function('CDocument', 'CChangesDocumentDefaultLanguage',
		stmt(wordDoc, 'CDocument.prototype.SetDefaultLanguage = function') +
		stmt(wordDoc, 'CDocument.prototype.GetDefaultLanguage = function'))({ prototype: doc }, CChangesDocumentDefaultLanguage);
	function asc_docs_api() { this.WordControl = { m_oLogicDocument: doc }; }
	new Function('asc_docs_api', 'AscCommon', 'AscDFH', 'editor',
		stmt(wordApi, 'asc_docs_api.prototype.asc_setDefaultLanguage = function') +
		stmt(wordApi, 'asc_docs_api.prototype.asc_getDefaultLanguage = function'))(
		asc_docs_api, { changestype_Document_SectPr: 1 }, { historydescription_Document_SetDefaultLanguage: 1 }, { WordControl: { m_oLogicDocument: doc } });
	return { api: new asc_docs_api(), doc };
}

/* --- web-apps: Main.js load-time lines --- */
const main = wsrc('apps/documenteditor/main/app/controller/Main.js');
function runMainLoad(stored, newBlank, sdk) {
	const at = main.indexOf('value = parseInt(Common.localStorage.getItem("de-settings-def-doc-lang"))');
	assert.notStrictEqual(at, -1, 'Main.js does not read de-settings-def-doc-lang');
	const endMarker = 'me.api.asc_setDefaultLanguage(value);';
	const end = main.indexOf(endMarker, at);
	assert.notStrictEqual(end, -1, 'Main.js does not call asc_setDefaultLanguage');
	const internal = {};
	const Common = {
		localStorage: { getItem: (k) => (k === 'de-settings-def-doc-lang' && stored !== undefined ? String(stored) : null) },
		Utils: { InternalSettings: { set: (k, v) => { internal[k] = v; } } },
	};
	new Function('Common', 'me', 'var value;' + main.slice(at, end + endMarker.length))(
		Common, { api: sdk.api, editorConfig: { newBlank } });
	return internal;
}

const EN_US = 0x0409, EN_CA = 0x1009, FR_FR = 0x040C;
check('new blank document: the chosen default language (en-CA) becomes the document language', () => {
	const sdk = makeSdk(EN_US);
	runMainLoad(EN_CA, true, sdk);
	assert.strictEqual(sdk.doc.styles.Default.TextPr.Lang.Val, EN_CA);
	assert.strictEqual(sdk.doc.actions, 1);
});
check('an existing (not new blank) document is never touched', () => {
	const sdk = makeSdk(FR_FR);
	runMainLoad(EN_CA, false, sdk);
	assert.strictEqual(sdk.doc.styles.Default.TextPr.Lang.Val, FR_FR);
	assert.strictEqual(sdk.doc.actions, 0);
});
check('unset ("Same as the interface") leaves the blank template language, no action', () => {
	const sdk = makeSdk(EN_US);
	const internal = runMainLoad(undefined, true, sdk);
	assert.strictEqual(sdk.doc.styles.Default.TextPr.Lang.Val, EN_US);
	assert.strictEqual(sdk.doc.actions, 0);
	assert.strictEqual(internal['de-settings-def-doc-lang'], 0);
});
check('already the chosen language: no action (no undo step, no "modified")', () => {
	const sdk = makeSdk(EN_CA);
	runMainLoad(EN_CA, true, sdk);
	assert.strictEqual(sdk.doc.actions, 0);
});

/* --- web-apps: settings panel --- */
const panels = wsrc('apps/documenteditor/main/app/view/FileMenuPanels.js');
check('settings panel offers "Same as the interface" plus the editor languages', () => {
	const at = panels.indexOf('var docLangs = [];');
	assert.notStrictEqual(at, -1, 'no language list in FileMenuPanels.js');
	const end = panels.indexOf("docLangs.unshift(", at);
	const code = panels.slice(at, panels.indexOf(';', end) + 1);
	const win = {};
	new Function('window', 'Common', wsrc('apps/common/main/lib/util/LanguageInfo.js'))(win, win.Common = {});
	const _ = { each: (o, f) => Object.keys(o).forEach((k) => f(o[k], k)) };
	const list = new Function('_', 'Common', code + '\nreturn docLangs;').call({ txtDocLangInterface: 'Same as the interface' }, _, win.Common);
	assert.deepStrictEqual(list[0], { value: 0, displayValue: 'Same as the interface', displayValueEn: '' });
	const enCA = list.find((l) => l.value === EN_CA);
	assert(enCA && /Canada/.test(enCA.displayValueEn), 'en-CA missing: ' + JSON.stringify(enCA));
	assert(list.length > 40, 'only ' + list.length + ' languages');
	assert(/id="fms-cmb-doc-lang"/.test(panels), 'no combo slot in the template');
	assert(/txtDocLang:\s*'[^']+'/.test(panels) && /txtDocLangInterface:\s*'[^']+'/.test(panels), 'strings missing');
});
check('Apply stores the choice (desktop offline editing only)', () => {
	const at = panels.indexOf('if (this.mode.isEdit && this.mode.isDesktopApp && this.mode.isOffline) {\n                Common.localStorage.setBool("de-settings-def-text-rtl"');
	assert.notStrictEqual(at, -1, 'save branch not found');
	const code = panels.slice(at, blockEnd(panels, panels.indexOf('{', at)));
	const stored = {};
	const Common = { localStorage: { setBool() {}, setItem: (k, v) => { stored[k] = v; } }, Utils: { InternalSettings: { set() {} } } };
	new Function('Common', code).call({
		mode: { isEdit: true, isDesktopApp: true, isOffline: true },
		rbTextRtl: { getValue: () => false }, cmbDocLang: { getValue: () => EN_CA },
	}, Common);
	assert.strictEqual(stored['de-settings-def-doc-lang'], EN_CA);
});
check('en.json has the two labels', () => {
	const en = JSON.parse(wsrc('apps/documenteditor/main/locale/en.json'));
	assert(en['DE.Views.FileMenuPanels.Settings.txtDocLang'] && en['DE.Views.FileMenuPanels.Settings.txtDocLangInterface']);
});

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
