/*
 * JS half of issue-0517-new-file-save-format (run by extract_and_run.py; see its docstring).
 * argv: <sdkjs dir> <sdkjs ref or ""> <web-apps dir> <web-apps ref or "">
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const [SDKJS, SDKJS_REF, WEBAPPS, WEBAPPS_REF] = process.argv.slice(2);
function read(repo, ref, rel) {
	return ref
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
function matched(text, start) {
	let depth = 0;
	for (let i = text.indexOf('{', start); i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(text.indexOf('{', start), i + 1);
	}
	throw new Error('unbalanced');
}
function fnAt(text, marker) {
	const at = text.indexOf(marker);
	if (at < 0) return null;
	const p = text.indexOf('function', at);
	return text.slice(p, text.indexOf(')', p) + 1) + matched(text, p);
}
let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(66)} ${JSON.stringify(got).padEnd(24)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}

/* the REAL c_oAscFileType */
const defines = read(SDKJS, SDKJS_REF, 'common/commonDefines.js');
const c_oAscFileType = new Function('return ' + matched(defines, defines.indexOf('var c_oAscFileType =')))();

/* --- sdkjs: the REAL asc_setNewFileSaveFormat and DesktopOfflineAppDocumentStartSave --- */
const setter = fnAt(read(SDKJS, SDKJS_REF, 'common/Local/common.js'), 'AscCommon.baseEditorsApi.prototype["asc_setNewFileSaveFormat"] = function');
check('sdkjs api has asc_setNewFileSaveFormat', !!setter, true);
for (const [rel, type] of [['word/Local/api.js', 'ODT'], ['cell/Local/api.js', 'ODS'], ['slide/Local/api.js', 'ODP']]) {
	const fn = fnAt(read(SDKJS, SDKJS_REF, rel), 'window["DesktopOfflineAppDocumentStartSave"] = function');
	const calls = [];
	const editor = {
		sync_StartAction() {}, getAdditionalSaveParams: () => ({}),
		isPdfEditor: () => false, isDocumentRenderer: () => false, getCurrentPage: () => 0, currentPassword: '',
	};
	if (setter) editor.asc_setNewFileSaveFormat = new Function('return ' + setter)();
	const window = { AscDesktopEditor: { LocalFileSave: (param) => calls.push(param) } };
	const run = new Function('window', 'editor', 'asc', 'Asc', 'AscCommon', 'isSupportSaveInPDF', 'return ' + fn + ';')(
		window, editor, { editor }, { editor, c_oAscAsyncActionType: {}, c_oAscAsyncAction: {} }, {}, true);
	run(false, undefined, true);                                   // nothing set: as before
	editor.asc_setNewFileSaveFormat && editor.asc_setNewFileSaveFormat(c_oAscFileType[type]);
	run(false, undefined, true);
	run(true, undefined, true);
	editor.asc_setNewFileSaveFormat && editor.asc_setNewFileSaveFormat(0);
	run(false, undefined, true);
	const n = c_oAscFileType[type];
	check(`${rel}: unset / ${type} save / ${type} Save As / back to 0`, calls, ['', `newformat=${n};`, `saveas=true;newformat=${n};`, '']);
}

/* --- web-apps: the REAL settings load in Main.js and LeftMenu.applySettings --- */
for (const [ed, type] of [['documenteditor', 'ODT'], ['spreadsheeteditor', 'ODS'], ['presentationeditor', 'ODP']]) {
	const got = [];
	const store = {};
	const Common = {
		localStorage: { getBool: (k, d) => k in store ? !!store[k] : !!d },
		Utils: { InternalSettings: { _v: {}, set(k, v) { this._v[k] = v; }, get(k) { return this._v[k]; } } },
	};
	const me = { api: { asc_setNewFileSaveFormat: (t) => got.push(t) } };
	const main = read(WEBAPPS, WEBAPPS_REF, `apps/${ed}/main/app/controller/Main.js`);
	const at = main.indexOf('value = Common.localStorage.getBool("app-settings-new-file-odf");');
	const block = at < 0 ? '' : main.slice(at, main.indexOf(';', main.indexOf('asc_setNewFileSaveFormat(value', at)) + 1);
	const load = new Function('Common', 'Asc', 'me', 'var value;' + block);
	load(Common, { c_oAscFileType }, me);
	store['app-settings-new-file-odf'] = 1;
	load(Common, { c_oAscFileType }, me);

	const lm = read(WEBAPPS, WEBAPPS_REF, `apps/${ed}/main/app/controller/LeftMenu.js`);
	const fn = fnAt(lm, 'applySettings: function(menu)');
	const stmt = (fn.match(/^\s*this\.api\.asc_setNewFileSaveFormat[^\n]*$/m) || [''])[0];
	Common.Utils.InternalSettings.set('app-settings-new-file-odf', false);
	new Function('Common', 'Asc', stmt).call(me, Common, { c_oAscFileType });
	check(`${ed}: load unset, load ODF, apply OOXML`, got, [0, c_oAscFileType[type], 0]);

	const panels = read(WEBAPPS, WEBAPPS_REF, `apps/${ed}/main/app/view/FileMenuPanels.js`);
	const en = JSON.parse(read(WEBAPPS, WEBAPPS_REF, `apps/${ed}/main/locale/en.json`));
	const ui = ['fms-rb-new-format-ooxml', 'fms-rb-new-format-odf', 'setBool("app-settings-new-file-odf"', "$('tr.new-format', this.el)"].every((x) => panels.includes(x))
		&& Object.keys(en).some((k) => /FileMenuPanels\.[A-Za-z]+\.txtNewFormatOdf$/.test(k));
	check(`${ed}: Advanced settings has the setting (radios, stored, en strings)`, ui, true);
}
console.log(failures ? 'js FAILED' : 'js ok');
process.exit(failures ? 1 : 0);
