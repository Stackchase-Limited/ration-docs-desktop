/*
 * #2107 - a plugin installed for all users cannot be uninstalled, and the plugin
 * manager does not say so. UI half (onlyoffice.github.io store = the plugin
 * manager the desktop app ships, {AA2EA9B6-...} + store/).
 *
 * The editor answers RemovePlugin with guid "" when nothing was removed: a
 * plugin installed for all users (desktop-sdk RemovePlugin only touches the
 * user folder - intended, the application folder is not ours to write) or, now
 * that the native side reports it, a user folder we cannot write. The manager
 * handled guid "" like a cancelled removal: hide the loader, say nothing - the
 * click did nothing and said nothing. The plugin side now marks that answer
 * with an error, and the store list and the plugin card show it.
 *
 * Second defect: removing a user copy that updated a plugin installed for all
 * users. The re-read installed list holds the system copy again, but the list
 * was drawn before the re-read finished and never redrawn, so the plugin showed
 * an Install button although it is still installed. It is now redrawn after the
 * re-read.
 *
 * This extracts the real code and runs it against stubs:
 *   sdkjs  pluginMethod_GetInstalledPlugins / pluginMethod_RemovePlugin
 *          (apiBase_plugins.js, unchanged - read from RD_SDKJS, never baseline)
 *   store  plugin/scripts/code.js removePlugin; scripts/code.js
 *          _onMessageRemoved, updateAvailablePlugins, updateListOfPlugins,
 *          _getPluginPlateState, changeAfterInstallUpdateRemove;
 *          scripts/card/plugin-card.js _doRemove; storage.js MarketplaceStorage;
 *          ui.js _makeActionButtons; utils.js isSamePlugins,
 *          convertPluginVersionToNumber.
 * The native folder listing is modelled (what GetInstallPlugins returns for the
 * folders); the native side itself is tested in issue-2107-plugin-remove-native/.
 *
 * Checks:
 *   1. a plugin installed for all users gets no Remove button (guard: already
 *      so before the fix - canRemoved=false from sdkjs);
 *   2. a failed removal reaches the store list and the card as an error;  <- FAILS on baseline
 *   3. after removing a user update over a system plugin, the plugin is shown
 *      installed again (Update, store has a newer one), not Install.        <- FAILS on baseline
 *
 * Env: RD_REPO = onlyoffice.github.io checkout (default ../onlyoffice.github.io),
 *      RD_SDKJS = sdkjs checkout (default ../sdkjs),
 *      BASELINE=1 reads the store files from BASE_REF via git show; must FAIL.
 * NOT claimed: how the error toast looks, CEF message timing between the
 * editor's UpdateInstallPlugins and the store's re-read (needs a GUI check).
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'onlyoffice.github.io');
const SDKJS = process.env.RD_SDKJS || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '34ab06d^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}
/* `name: function(...) {...}` from an object literal -> a function expression */
function method(text, name) {
	return extract(text, name + ': function').replace(new RegExp('^' + name + ':\\s*'), '');
}

const sdkjs = fs.readFileSync(path.join(SDKJS, 'common/apiBase_plugins.js'), 'utf8');
const pluginCode = src('store/plugin/scripts/code.js');
const storeCode = src('store/scripts/code.js');
const cardCode = src('store/scripts/card/plugin-card.js');
const storage = src('store/scripts/marketplace/storage.js');
const ui = src('store/scripts/marketplace/ui.js');
const utils = src('store/scripts/shared/utils.js');

/* --- modelled desktop: plugin folders and what is registered in the editor --- */
const S1 = 'asc.{11111111-0000-0000-0000-000000000001}';   // installed for all users only
const S2 = 'asc.{11111111-0000-0000-0000-000000000002}';   // system v1 + user update v2
const cfg = (guid, name, version, dir) => ({ name, guid, version, baseUrl: `file:///${dir}/${guid.slice(4)}/`,
	variations: [{ description: name, url: 'index.html', isVisual: true, EditorsSupport: ['word'] }] });
const sysS1 = cfg(S1, 'S1', '1.0.0', 'app/sdkjs-plugins');
const sysS2 = cfg(S2, 'S2', '1.0.0', 'app/sdkjs-plugins');
const usrS2 = cfg(S2, 'S2', '2.0.0', 'user/sdkjs-plugins');
const disk = { sys: [sysS1], user: [usrS2] };      // S2 v1 is hidden by the newer user copy
let nativeRemoveResult = true;

const window = {
	location: { protocol: 'file:', href: 'file:///app/editors/index.html' },
	AscDesktopEditor: {
		GetInstallPlugins: () => JSON.stringify([
			{ url: 'file:///app/sdkjs-plugins/', pluginsData: disk.sys },
			{ url: 'file:///user/sdkjs-plugins/', pluginsData: disk.user }]),
		PluginUninstall(guid) {
			if (!nativeRemoveResult) return false;
			disk.user = disk.user.filter(p => p.guid !== guid);
			if (guid === S2) disk.sys = [sysS1, sysS2];          // the system copy shows again
			return true;
		},
	},
	g_asc_plugins: {
		get plugins() { return disk.sys.concat(disk.user).map(c => ({ guid: c.guid, serialize: () => c })); },
		systemPlugins: [],
		unregister: () => null,
	},
};
const Api = function() {};
new Function('Api', 'window', 'getLocalStorageItem', 'setLocalStorageItem',
	extract(sdkjs, 'Api.prototype["pluginMethod_GetInstalledPlugins"] = function') + ';\n' +
	extract(sdkjs, 'Api.prototype["pluginMethod_RemovePlugin"] = function') + ';')(Api, window, () => null, () => {});
const editor = new Api();

/* --- the store page --- */
const errors = [];
const buttons = {};
const btn = (text) => ({ textContent: text, onclick: null, classList: { add() {}, remove() {} },
	hasAttribute: () => false, setAttribute() {} });
const Utils = Object.assign({
	getTranslated: (t) => t, getTranslatedMessage: (t) => t, getTranslatedName: (p) => p.name,
}, eval('({isSamePlugins: ' + method(utils, 'isSamePlugins') + ', convertPluginVersionToNumber: ' +
	method(utils, 'convertPluginVersionToNumber') +
	// _makeActionButtons escapes the guid since #1664 (store HTML); older trees have no escapeHtml
	(utils.includes('escapeHtml: function') ? ', escapeHtml: ' + method(utils, 'escapeHtml') : '') + '})'));
const UI = {
	divMain: { textContent: '' },
	_makeActionButtons: eval('(' + method(ui, '_makeActionButtons') + ')'),
	createPluginPlate(guid, isLocal, bg, state) {
		const html = this._makeActionButtons(guid, state);
		buttons[guid] = btn(html ? html.replace(/^.*>([^<>]*)<\/button>$/, '$1') : '');
		return {};
	},
	addPlugin() {}, getPluginButton: (guid) => buttons[guid], toggleLoader() {},
};
const localStorage = { getItem: () => null };
const MarketplaceStorage = new Function('localStorage', 'window',
	extract(storage, 'const MarketplaceStorage = {') + '\nreturn MarketplaceStorage;')(localStorage, { parent: {} });
const MarketplacePluginService = {
	// the plugin answers getInstalled with the editor's GetInstalledPlugins
	updateAvailablePlugins: () => Promise.resolve(editor.pluginMethod_GetInstalledPlugins()),
};

const store = new Function('MarketplaceStorage', 'MarketplacePluginService', 'UI', 'Utils', 'createError',
	'Scale', 'setTimeout', 'isLocal', 'ioUrl', 'guidMarketplace', 'guidSettings', 'editorVersion',
	'independentMode', 'defaultBG', '_loadBackupPlugins', 'updateCategories', 'onClickPluginPlate', 'onClickInstall', 'onClickRemove', '_showEmptyNotification',
	'let founded = [];\n' +
	extract(storeCode, 'function updateAvailablePlugins(') + '\n' +
	extract(storeCode, 'function _onMessageRemoved(') + '\n' +
	extract(storeCode, 'function updateListOfPlugins(') + '\n' +
	extract(storeCode, 'function _getPluginPlateState(') + '\n' +
	extract(storeCode, 'function changeAfterInstallUpdateRemove(') + '\n' +
	'return { updateAvailablePlugins, _onMessageRemoved, updateListOfPlugins };')(
	MarketplaceStorage, MarketplacePluginService, UI, Utils, (e) => errors.push(e && e.message),
	{ updateScroll() {} }, (f) => f(), true, 'https://onlyoffice.github.io/', 'asc.{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}',
	'asc.{8D67F3C5-7736-4BAE-A0F2-8C7127DC4BB8}', 9004000, false, '', () => [], () => {}, () => {}, () => {}, () => {}, () => {});

/* the manager plugin's removePlugin: RemovePlugin goes to the editor, the answer to the store */
const posted = [];
function makeRemovePlugin(guid) {
	return new Function('window', 'postMessage', 'guid',
		'let removeGuid = guid;\n' + extract(pluginCode, 'function removePlugin(') + '\nreturn removePlugin;')(
		{ Asc: { plugin: { executeMethod: (name, args, cb) => cb(editor['pluginMethod_' + name].apply(editor, args)) } } },
		(m) => posted.push(m), guid);
}

const tick = () => new Promise((r) => setImmediate(r));
const failures = [];
async function check(name, f) {
	try { await f(); console.log('ok   ' + name); }
	catch (e) { failures.push(name); console.log('FAIL ' + name + ': ' + e.message); }
}

(async function() {
	MarketplaceStorage.categoryFilter = 'all';
	MarketplaceStorage.setMarketplacePlugins([cfg(S1, 'S1', '1.0.0', 'store'), cfg(S2, 'S2', '2.0.0', 'store')]);
	await store.updateAvailablePlugins();
	store.updateListOfPlugins();

	/* 1. installed for all users: no Remove (guard, true before the fix as well) */
	await check('1. installed for all users: no Remove button', () => {
	assert.strictEqual(buttons[S1].textContent, '', 'S1 (installed for all users) must not offer Remove');
	assert.strictEqual(buttons[S2].textContent, 'Remove', 'the user copy of S2 is removable');
	});

	/* 2. a removal the editor refuses must be reported, in the list and in the card */
	nativeRemoveResult = false;
	await check('2. a refused removal is reported (list and card)', async () => {
	await makeRemovePlugin(S2)(false);
	const failed = posted.pop();
	assert.strictEqual(failed.guid, '', 'the editor reports nothing removed');
	store._onMessageRemoved(failed);
	assert.deepStrictEqual(errors, ['Problem with plugin removal.'],
		'a failed removal must be reported, not silently put back');
	const cardErrors = [];
	const card = { config: { guid: S2 }, backup: false,
		_doRemove: new Function('MarketplacePluginService', 'PluginCardUI', 'createError',
			'return ' + method(cardCode, '_doRemove'))(
			{ doRemove: () => Promise.resolve(failed) }, { toggleLoader() {} }, (e) => cardErrors.push(e && e.message)) };
	await card._doRemove();
	assert.deepStrictEqual(cardErrors, ['Problem with plugin removal.'], 'the plugin card must report it too');
	assert.strictEqual(buttons[S2].textContent, 'Remove', 'nothing was removed: still Remove');
	});

	/* 3. removing the user update reveals the system copy: shown installed (Update to the store's v2) */
	nativeRemoveResult = true;
	await check('3. removing a user update shows the system copy installed again', async () => {
	await makeRemovePlugin(S2)(false);
	const removed = posted.pop();
	assert.strictEqual(removed.guid, S2);
	assert.strictEqual(removed.error, undefined, 'success is not an error');
	store._onMessageRemoved(removed);
	await tick(); await tick();
	assert.ok(MarketplaceStorage.findInstalledPlugin(S2), 'S2 v1 (installed for all users) is installed');
	assert.strictEqual(buttons[S2].textContent, 'Update',
		'the list must show S2 installed again (Update to store v2), not "' + buttons[S2].textContent + '"');
	});
	if (failures.length) throw new Error(failures.length + ' check(s) failed');

	console.log('PASS #2107: plugin manager reports failed removals and shows a revealed system plugin' +
		(process.env.BASELINE ? ' (BASELINE?!)' : ''));
})().catch((e) => {
	console.error('FAIL #2107' + (process.env.BASELINE ? ' [BASELINE ' + BASE_REF + ']' : '') + ': ' + e.message);
	process.exit(1);
});
