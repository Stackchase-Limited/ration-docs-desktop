/*
 * JS half of issue-0982-save-copy (run by extract_and_run.py; see its docstring).
 * argv: <sdkjs dir> <sdkjs ref or ""> <web-apps dir> <web-apps ref or "">
 * An empty ref reads the working tree.
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
	if (at < 0) throw new Error(marker + ' not found');
	const p = text.indexOf('function', at);
	return text.slice(p, text.indexOf(')', p) + 1) + matched(text, p);
}

let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(66)} ${JSON.stringify(got).padEnd(24)} ${ok ? 'ok' : 'FAILED (want ' + JSON.stringify(want) + ')'}`);
}

/* --- sdkjs: the REAL asc_CDownloadOptions --- */
const win = { Asc: {}, AscCommon: {} };
new Function('window', read(SDKJS, SDKJS_REF, 'common/AdvancedOptions.js'))(win);
const Asc = win.Asc;
const opt = new Asc.asc_CDownloadOptions();
check('sdkjs asc_CDownloadOptions has an exported asc_setIsSaveCopy', typeof opt['asc_setIsSaveCopy'], 'function');

/* --- sdkjs: the REAL DesktopOfflineAppDocumentStartSave of each editor --- */
for (const rel of ['word/Local/api.js', 'cell/Local/api.js', 'slide/Local/api.js', 'visio/Local/api.js']) {
	const fn = fnAt(read(SDKJS, SDKJS_REF, rel), 'window["DesktopOfflineAppDocumentStartSave"] = function');
	const calls = [];
	const editor = {
		sync_StartAction() {}, getAdditionalSaveParams: () => ({}), ['getAdditionalSaveParams']: () => ({}),
		isPdfEditor: () => false, isDocumentRenderer: () => false, getCurrentPage: () => 0, currentPassword: '',
	};
	const window = { AscDesktopEditor: { LocalFileSave: (param) => calls.push(param) } };
	const run = new Function('window', 'editor', 'asc', 'Asc', 'AscCommon', 'isSupportSaveInPDF', 'return ' + fn + ';')(
		window, editor, { editor }, { editor, c_oAscAsyncActionType: {}, c_oAscAsyncAction: {} }, {}, true);
	const copy = new Asc.asc_CDownloadOptions();
	if (copy.asc_setIsSaveCopy) copy.asc_setIsSaveCopy(true); else copy.isSaveCopy = true;
	run(true, undefined, true, undefined, copy);
	run(true, undefined, true, undefined, new Asc.asc_CDownloadOptions());
	run(false, undefined, true, undefined, copy);
	check(rel + ': copy / Save As / plain Save', calls, ['saveas=true;savecopy=true;', 'saveas=true;', '']);
}

/* --- web-apps: the REAL File menu (visibility) and the REAL clickMenuFileItem --- */
for (const ed of ['documenteditor', 'spreadsheeteditor', 'presentationeditor', 'pdfeditor']) {
	const fm = read(WEBAPPS, WEBAPPS_REF, `apps/${ed}/main/app/view/FileMenu.js`);
	const at = fm.indexOf('this.miSaveCopyAs[');
	const stmt = fm.slice(at, fm.indexOf('();', at) + 3);
	const desktop = { canDownload: true, canDownloadOrigin: false, isDesktopApp: true, isOffline: true, canRequestSaveAs: false, saveAsUrl: '' };
	const shown = (mode, isBCSupport) => {
		let state;
		new Function('isBCSupport', stmt).call({ mode, miSaveCopyAs: { show: () => state = 'show', hide: () => state = 'hide' } }, isBCSupport);
		return state;
	};
	check(`${ed}: Save Copy as in desktop / blockchain / online w/o saveAsUrl`,
		[shown(desktop, false), shown(desktop, true), shown(Object.assign({}, desktop, { isDesktopApp: false, isOffline: false }), false)],
		['show', 'hide', 'hide']);

	const lm = read(WEBAPPS, WEBAPPS_REF, `apps/${ed}/main/app/controller/LeftMenu.js`);
	const click = new Function('Asc', 'Common', 'return ' + fnAt(lm, 'clickMenuFileItem: function') + ';')(Asc, {});
	const got = [];
	const ctrl = {
		mode: desktop,
		api: { asc_DownloadAs: (o) => got.push(o && o.isSaveCopy ? 'copy' : 'save as'), asc_Save: () => got.push('save') },
		clickSaveAsFormat: () => got.push('online save copy'),
	};
	let hidden = false;
	click.call(ctrl, { hide: () => hidden = true }, 'save-copy', false);
	click.call(ctrl, { hide() {} }, 'save-desktop', false);
	check(`${ed}: desktop File > Save Copy as, then Save as`, [got, hidden], [['copy', 'save as'], true]);
}

console.log(failures ? 'js FAILED' : 'js ok');
process.exit(failures ? 1 : 0);
