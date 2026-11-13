/*
 * DesktopEditors #1064 - list of undo steps: the web-apps part of the smallest
 * useful version - the Undo tooltip names the step it undoes, opt-in.
 * (sdkjs asc_getUndoLabel: issue-1064-undo-label/.)
 *
 * Before: the Undo buttons' tooltip was always "Undo (Ctrl+Z)".
 * Now: with File > Advanced settings > "Name the last action in the Undo
 * button tooltip" (<de|pe|sse>-settings-undo-label, OFF by default) the
 * toolbar and header Undo buttons read "Undo: Typing (Ctrl+Z)".
 * Common.Controllers.Shortcuts listens to asc_onCanUndo (asc_onCanUndoChanged
 * in the spreadsheet editor) and 'undolabel:changed' and re-applies the
 * EditUndo hints through its own hint callbacks.
 *
 * What runs: the REAL Shortcuts.js controller (define() factory with a stub
 * Backbone.Controller): setApi registration, updateShortcutHints building the
 * hint, updateUndoLabel with the setting off (hint unchanged, api not asked)
 * and on (label inserted before the shortcut, cleared when nothing to undo).
 * Plus the settings checkbox wiring in the three FileMenuPanels.js (template
 * row, default from localStorage, saved + notification) and en.json strings.
 * NOT claimed: the look of the tooltip / settings row (GUI check needed);
 * native title-bar buttons and the macOS Edit menu are not changed.
 *
 *   RD_WEBAPPS=<web-apps> (default ../web-apps)
 *   BASELINE=1 reads web-apps at WEBAPPS_BASE_REF; it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '8cd5171462^';

function wsrc(rel) {
	try {
		return process.env.BASELINE
			? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'] })
			: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
	} catch (e) { return ''; }
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

function loadShortcuts(appGlobal, storage) {
	const text = wsrc('apps/common/main/lib/controller/Shortcuts.js');
	assert(text, 'no Shortcuts.js');
	const notifications = {};
	const Common = {
		Controllers: {},
		localStorage: { getBool: (k, d) => (k in storage ? !!storage[k] : !!d), getItem: () => null, setItem() {} },
		NotificationCenter: { on: (n, f) => { notifications[n] = f; }, trigger: (n) => notifications[n] && notifications[n]() },
		Utils: { isMac: false },
	};
	const Backbone = { Controller: { extend: (p) => { const C = function () { this.initialize(); }; C.prototype = p; return C; } } };
	const _ = { extend: Object.assign, bind: (f, t) => f.bind(t), find: (a, f) => a.find(f), invert: (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [v, k])) };
	const window = Object.assign({}, appGlobal);
	new Function('define', 'Common', 'Backbone', '_', 'window', text)((deps, f) => f(), Common, Backbone, _, window);
	const ctl = new Common.Controllers.Shortcuts();
	// keep the SDK shortcut plumbing out: only the hint path is under test
	ctl._fillActionsMap = () => {};
	ctl._applyShortcutsInSDK = () => {};
	ctl._eventsTrigger = () => {};
	ctl.getDefaultShortcutActions = () => ({ EditUndo: 1 });
	ctl.actionsMap = { 1: { shortcuts: [{ keys: ['Ctrl', 'Z'], ascShortcut: { asc_IsHidden: () => false } }] } };
	return { ctl, Common, notifications };
}

function fakeApi() {
	const api = { callbacks: {}, label: 'Typing', asked: 0 };
	api.asc_registerCallback = (n, f) => { (api.callbacks[n] = api.callbacks[n] || []).push(f); };
	api.asc_getUndoLabel = () => { api.asked++; return api.label; };
	return api;
}

check('Shortcuts: setting OFF (default) - the Undo hint stays "Undo (Ctrl+Z)" and the api is not asked', () => {
	const { ctl } = loadShortcuts({ DE: {} }, {});
	const api = fakeApi();
	ctl.setApi(api);
	assert(api.callbacks.asc_onCanUndo, 'asc_onCanUndo not listened to');
	const btn = { updateHint(h) { this.hint = h; } };
	ctl.updateShortcutHints({ EditUndo: { btn, label: 'Undo' } });
	assert.strictEqual(btn.hint, 'Undo (Ctrl+Z)');
	api.callbacks.asc_onCanUndo.forEach(f => f(true));
	assert.strictEqual(btn.hint, 'Undo (Ctrl+Z)');
	assert.strictEqual(api.asked, 0, 'api asked with the setting off');
});

check('Shortcuts: setting ON - toolbar and header Undo read "Undo: <step> (Ctrl+Z)" and follow the history', () => {
	const storage = {};
	const { ctl, Common } = loadShortcuts({ DE: {} }, storage);
	const api = fakeApi();
	ctl.setApi(api);
	const toolbar = { updateHint(h) { this.hint = h; } }, header = { updateHint(h) { this.hint = h; } };
	ctl.updateShortcutHints({ EditUndo: { btn: toolbar, label: 'Undo' } });
	ctl.updateShortcutHints({ EditUndo: { btn: header, label: 'Undo' } });
	storage['de-settings-undo-label'] = true;
	Common.NotificationCenter.trigger('undolabel:changed');   // what FileMenuPanels fires on apply
	assert.strictEqual(toolbar.hint, 'Undo: Typing (Ctrl+Z)');
	assert.strictEqual(header.hint, 'Undo: Typing (Ctrl+Z)');
	api.label = 'Insert Table';
	api.callbacks.asc_onCanUndo.forEach(f => f(true));
	assert.strictEqual(toolbar.hint, 'Undo: Insert Table (Ctrl+Z)');
	api.label = null;
	api.callbacks.asc_onCanUndo.forEach(f => f(false));
	assert.strictEqual(header.hint, 'Undo (Ctrl+Z)', 'label kept with nothing to undo');
});

check('Shortcuts: the spreadsheet editor listens to asc_onCanUndoChanged and uses sse-settings-undo-label', () => {
	const { ctl } = loadShortcuts({ SSE: {} }, { 'sse-settings-undo-label': true });
	const api = fakeApi();
	api.label = 'Insert Rows';
	ctl.setApi(api);
	assert(api.callbacks.asc_onCanUndoChanged && !api.callbacks.asc_onCanUndo, 'wrong event');
	const btn = { updateHint(h) { this.hint = h; } };
	ctl.updateShortcutHints({ EditUndo: { btn, label: 'Undo' } });
	api.callbacks.asc_onCanUndoChanged.forEach(f => f(true));
	assert.strictEqual(btn.hint, 'Undo: Insert Rows (Ctrl+Z)');
});

for (const [app, p, ns] of [['documenteditor', 'de', 'DE.Views.FileMenuPanels.Settings'], ['presentationeditor', 'pe', 'PE.Views.FileMenuPanels.Settings'],
	['spreadsheeteditor', 'sse', 'SSE.Views.FileMenuPanels.MainSettingsGeneral']]) {
	check(app + ': Advanced settings checkbox, off unless stored, saved with a notification; en.json', () => {
		const fm = wsrc('apps/' + app + '/main/app/view/FileMenuPanels.js');
		assert(fm.includes('<div id="fms-chb-undo-label"></div>'), 'no settings row');
		assert(/this\.chUndoLabel = new Common\.UI\.CheckBox\(\{\s*el: \$markup\.findById\('#fms-chb-undo-label'\),\s*labelText: this\.txtUndoLabel/.test(fm), 'no checkbox');
		assert(fm.includes(`this.chUndoLabel.setValue(Common.localStorage.getBool("${p}-settings-undo-label"));`), 'not read from storage (default off)');
		assert(new RegExp(`Common\\.localStorage\\.setBool\\("${p}-settings-undo-label", this\\.chUndoLabel\\.isChecked\\(\\)\\);\\s*Common\\.NotificationCenter\\.trigger\\('undolabel:changed'\\);`).test(fm), 'not saved / no notification');
		const en = wsrc('apps/' + app + '/main/locale/en.json');
		assert(en.includes(`"${ns}.txtUndoLabel"`), 'en.json lacks the label');
		JSON.parse(en);
	});
}

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
