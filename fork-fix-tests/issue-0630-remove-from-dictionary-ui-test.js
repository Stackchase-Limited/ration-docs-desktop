/*
 * DesktopEditors #630 - "Remove from dictionary": "Add to dictionary" in the
 * spelling context menu could not be undone; a word added by mistake stayed
 * correct for good. (Native side: issue-0630-remove-from-dictionary/.)
 *
 * Cause: sdkjs had asc_spellCheckAddToDictionary only - nothing asked the
 * desktop for its user dictionary or removed a word - and web-apps had no UI.
 * Fix: sdkjs common/apiBase.js asc_spellCheckGetUserDictionary (task
 * {"type":"list"}, answer -> asc_onSpellCheckUserDictionary) and
 * asc_spellCheckRemoveFromDictionary (task {"type":"remove"} with the word in
 * the raw form "add" stores, then asc_restartCheckSpelling); the
 * asc_nativeOnSpellCheck router hands "list"/"remove" answers on before the
 * spell-results path. web-apps: Common.Views.UserDictionaryDialog and a
 * "Dictionary..." button under "AutoCorrect options..." in the document,
 * presentation and spreadsheet editors (desktop only).
 *
 * What runs: the REAL apiBase.js methods and the REAL asc_nativeOnSpellCheck
 * function body (from _coSpellCheckInit) against a stub AscDesktopEditor;
 * the REAL UserDictionaryDialog.js prototype (define() factory run with stub
 * Common.UI classes) - render, onWords, onDelete, close; the REAL
 * FileMenuPanels userDictionary handlers; plus exports, template rows, the
 * build lists (app_dev.js/app_pack.js) and en.json strings.
 * Claimed: the tasks sent, the event fired, the answers kept away from
 * SpellCheck_CallBack, the dialog lists sorted words and removes the selected
 * one through the api. NOT claimed: the dialog's look (GUI check needed), the
 * native side (separate test).
 *
 *   RD_REPO=<sdkjs> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps)
 *   BASELINE=1 reads sdkjs at BASE_REF and web-apps at WEBAPPS_BASE_REF; it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
// Pinned to the parents of the fix commits, never HEAD.
const BASE_REF = process.env.BASE_REF || '50339e12a4^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '3f20b3a7fc^';

function read(repo, ref, rel) {
	try {
		return process.env.BASELINE
			? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'] })
			: fs.readFileSync(path.join(repo, rel), 'utf8');
	} catch (e) { return ''; }
}
const src = (rel) => read(SDKJS, BASE_REF, rel);
const wsrc = (rel) => read(WEBAPPS, WEBAPPS_BASE_REF, rel);

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function assignment(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) throw new Error(marker + ' not found');
	return block(text, at) + ';';
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

/* --- sdkjs --- */
const base = src('common/apiBase.js');
const tasks = [], events = [], spellResults = [];
const window = { AscDesktopEditor: { SpellCheck: (t) => tasks.push(t) }, Asc: {} };
function baseEditorsApi() {}
let restarts = 0;
baseEditorsApi.prototype.asc_restartCheckSpelling = function () { restarts++; };
baseEditorsApi.prototype.sendEvent = function () { events.push(Array.from(arguments)); };

check('apiBase: asc_spellCheckGetUserDictionary sends the "list" task', () => {
	new Function('baseEditorsApi', 'window', assignment(base, 'baseEditorsApi.prototype.asc_spellCheckGetUserDictionary'))(baseEditorsApi, window);
	assert.strictEqual(new baseEditorsApi().asc_spellCheckGetUserDictionary(), true);
	assert.deepStrictEqual(JSON.parse(tasks.pop()), { type: 'list' });
});
check('apiBase: asc_spellCheckRemoveFromDictionary sends "remove" with the word as "add" stores it, then rechecks', () => {
	new Function('baseEditorsApi', 'window', assignment(base, 'baseEditorsApi.prototype.asc_spellCheckRemoveFromDictionary'))(baseEditorsApi, window);
	new Function('baseEditorsApi', 'window', assignment(base, 'baseEditorsApi.prototype.asc_spellCheckAddToDictionary'))(baseEditorsApi, window);
	const api = new baseEditorsApi();
	api._spellCheckRestart = () => {};
	api.asc_spellCheckAddToDictionary('teh');
	const add = tasks.pop();
	api.asc_spellCheckRemoveFromDictionary('teh');
	const rem = tasks.pop();
	assert.deepStrictEqual(JSON.parse(rem), { type: 'remove', usrWords: ['teh'] });
	assert.strictEqual(rem.slice(rem.indexOf('usrWords')), add.slice(add.indexOf('usrWords')), 'word not sent like add');
	assert.strictEqual(restarts, 1);
	api.asc_spellCheckRemoveFromDictionary('');
	assert.strictEqual(tasks.length, 0, 'empty word sent');
});
check('asc_nativeOnSpellCheck: "list" fires asc_onSpellCheckUserDictionary, "remove" is dropped, spell results still pass', () => {
	const at = base.indexOf('window["asc_nativeOnSpellCheck"] = function(response)');
	assert.notStrictEqual(at, -1);
	const editor = {
		SpellCheckApi: { isRestart: false, onSpellCheck: (r) => spellResults.push(r) },
		sendEvent: function () { events.push(Array.from(arguments)); },
	};
	window.Asc.editor = editor;
	new Function('window', block(base, at) + ';')(window);
	window.asc_nativeOnSpellCheck({ type: 'list', usrWords: ['b', 'a'] });
	window.asc_nativeOnSpellCheck({ type: 'remove' });
	window.asc_nativeOnSpellCheck({ type: 'spell', ParagraphId: '1' });
	assert.deepStrictEqual(events.pop(), ['asc_onSpellCheckUserDictionary', ['b', 'a']]);
	assert.deepStrictEqual(spellResults.map(r => r.type), ['spell']);
});
check('word, slide and cell apis export both methods under their public names', () => {
	for (const rel of ['word/api.js', 'slide/api.js', 'cell/api.js'])
		for (const m of ['asc_spellCheckRemoveFromDictionary', 'asc_spellCheckGetUserDictionary'])
			assert(new RegExp(`\\[["']${m}["']\\]\\s*=\\s*(asc_docs_api\\.prototype|prot)\\.${m}`).test(src(rel)), rel + ' does not export ' + m);
});

/* --- web-apps: the dialog --- */
check('UserDictionaryDialog: lists the words sorted and removes the selected one through the api', () => {
	const text = wsrc('apps/common/main/lib/view/UserDictionaryDialog.js');
	assert(text, 'no apps/common/main/lib/view/UserDictionaryDialog.js');
	let proto = null;
	const Common = { Views: {}, UI: {}, Utils: { String: { htmlEncode: (s) => s } } };
	Common.UI.Window = { extend: (p) => { proto = p; return p; }, prototype: { initialize() {}, render() {}, close() { this.closed = true; } } };
	class Store {
		constructor(a) { this.models = a; }
		reset(a) { this.models = a.map(o => ({ get: (k) => o[k], value: o.value })); }
		indexOf(r) { return this.models.indexOf(r); }
		remove(r) { this.models.splice(this.models.indexOf(r), 1); }
		get length() { return this.models.length; }
	}
	Common.UI.DataViewStore = Store;
	Common.UI.ListView = function (o) { this.store = o.store; this.sel = null; this.on = () => this; this.getSelectedRec = () => this.sel; this.selectByIndex = (i) => { this.sel = this.store.models[i]; }; };
	Common.UI.Button = function () { this.on = () => this; this.setDisabled = (d) => { this.disabled = d; }; };
	const _ = { extend: Object.assign, bind: (f, t) => f.bind(t), template: () => () => '', map: (a, f) => a.map(f), uniq: (a) => [...new Set(a)] };
	new Function('define', 'Common', '_', text)((deps, f) => f(), Common, _);
	assert(proto && Common.Views.UserDictionaryDialog, 'dialog not defined');
	const calls = [], cbs = {};
	const api = {
		asc_registerCallback: (n, f) => { cbs[n] = f; }, asc_unregisterCallback: (n) => { delete cbs[n]; },
		asc_spellCheckGetUserDictionary: () => calls.push('list'),
		asc_spellCheckRemoveFromDictionary: (w) => calls.push('remove:' + w),
	};
	const dlg = Object.assign(Object.create(proto), { api, getChild: () => ({ find: () => ({ on() {} }) }), getFooterButtons: () => [] });
	proto.render.call(dlg);
	assert.deepStrictEqual(calls, ['list']);
	cbs.asc_onSpellCheckUserDictionary(['teh', 'Acme', 'teh']);
	assert.deepStrictEqual(dlg.wordsList.store.models.map(m => m.value), ['Acme', 'teh']);
	assert.strictEqual(dlg.btnDelete.disabled, true, 'Remove enabled with nothing selected');
	dlg.wordsList.selectByIndex(1);
	dlg.onDelete();
	assert.deepStrictEqual(calls, ['list', 'remove:teh']);
	assert.deepStrictEqual(dlg.wordsList.store.models.map(m => m.value), ['Acme']);
	dlg.close();
	assert(!cbs.asc_onSpellCheckUserDictionary, 'callback left registered after close');
});

/* --- web-apps: the editors --- */
for (const [app, pre, view] of [['documenteditor', 'DE', 'Settings'], ['presentationeditor', 'PE', 'Settings'], ['spreadsheeteditor', 'SSE', 'MainSettingsGeneral']]) {
	check(app + ': "Dictionary..." button opens the dialog (desktop only), file in the build lists, strings', () => {
		const fm = wsrc('apps/' + app + '/main/app/view/FileMenuPanels.js');
		assert(/<tr class="edit user-dict">[\s\S]{0,200}id="fms-btn-user-dict"/.test(fm), 'no button row');
		assert(/\$\('tr\.user-dict', this\.el\)\[mode\.isEdit && mode\.isDesktopApp/.test(fm), 'row not limited to the desktop app');
		const at = fm.indexOf('userDictionary: function()');
		assert.notStrictEqual(at, -1, 'no userDictionary handler');
		let made = null;
		const Common = { Views: { UserDictionaryDialog: function (o) { made = o; this.show = () => { this.shown = true; }; this.isVisible = () => true; } } };
		const handler = new Function('Common', 'return ' + block(fm, fm.indexOf('function', at)))(Common);
		const panel = { api: { id: 1 } };
		handler.call(panel);
		assert(made && made.api === panel.api && panel.dlgUserDictionary.shown, 'dialog not opened with the api');
		for (const f of ['app_dev.js', 'app_pack.js'])
			assert(wsrc('apps/' + app + '/main/' + f).includes("'common/main/lib/view/UserDictionaryDialog'"), f + ' lacks the dialog');
		const en = wsrc('apps/' + app + '/main/locale/en.json');
		assert(en.includes(`"${pre}.Views.FileMenuPanels.${view}.txtUserDictionary"`), 'en.json lacks the button label');
		assert(en.includes('"Common.Views.UserDictionaryDialog.textTitle"'), 'en.json lacks the dialog strings');
	});
}

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
